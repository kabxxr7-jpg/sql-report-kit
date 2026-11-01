#!/usr/bin/env python3
"""Start, stop or inspect a throwaway MariaDB server that lives inside this repository folder.

    python scripts/local-mariadb.py start    # initialise .local-db/mariadb on first use, then start it
    python scripts/local-mariadb.py status
    python scripts/local-mariadb.py stop     # clean shutdown, then a hard kill only if it does not exit
    python scripts/local-mariadb.py destroy  # stop and delete the data directory

It never reads the system my.cnf (--no-defaults), listens on 127.0.0.1:3308 only and has its own socket,
pid file and error log under .local-db/mariadb/. The current OS user is made the administrator: it can log in over that socket as the MariaDB user
of the same name, with no password. This is a test server for the suite, not a pattern for running a real database.

The MariaDB binaries are found from SQLREPORT_MARIADB_BASEDIR, then the `mariadbd` on PATH, then the
usual Homebrew locations. Nothing is installed or upgraded by this script.
"""

from __future__ import annotations

import argparse
import getpass
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOME = ROOT / ".local-db" / "mariadb"
DATA = HOME / "data"
SOCKET = HOME / "mariadb.sock"
PIDFILE = HOME / "mariadb.pid"
LOGFILE = HOME / "error.log"
PORT = 3308
BIND = "127.0.0.1"


def find_basedir() -> Path:
    candidates = []
    if os.environ.get("SQLREPORT_MARIADB_BASEDIR"):
        candidates.append(Path(os.environ["SQLREPORT_MARIADB_BASEDIR"]))
    on_path = shutil.which("mariadbd")
    if on_path:
        candidates.append(Path(on_path).resolve().parent.parent)
    candidates += [Path("/opt/homebrew/opt/mariadb"), Path("/usr/local/opt/mariadb"), Path("/usr")]
    for base in candidates:
        if (base / "bin" / "mariadbd").exists():
            return base
    sys.exit("error: mariadbd not found (set SQLREPORT_MARIADB_BASEDIR)")


def read_pid() -> int | None:
    try:
        pid = int(PIDFILE.read_text().strip())
    except (OSError, ValueError):
        return None
    try:
        os.kill(pid, 0)
    except OSError:
        return None
    return pid


def admin(base: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    cmd = [str(base / "bin" / "mariadb-admin"), "--no-defaults", f"--socket={SOCKET}", f"--user={getpass.getuser()}", *args]
    return subprocess.run(cmd, capture_output=True, text=True, check=check, timeout=30)


def ping(base: Path) -> bool:
    try:
        return admin(base, "ping", check=False).returncode == 0
    except subprocess.TimeoutExpired:
        return False


def start() -> int:
    base = find_basedir()
    if read_pid():
        print(f"already running (pid {read_pid()}) on {BIND}:{PORT}")
        return 0
    HOME.mkdir(parents=True, exist_ok=True)
    if not (DATA / "mysql").exists():
        DATA.mkdir(parents=True, exist_ok=True)
        user = getpass.getuser()
        init = subprocess.run(
            [
                str(base / "bin" / "mariadb-install-db"), "--no-defaults", f"--basedir={base}", f"--datadir={DATA}",
                "--auth-root-authentication-method=socket", f"--auth-root-socket-user={user}", "--skip-test-db",
            ],
            capture_output=True, text=True, timeout=300,
        )
        if init.returncode != 0:
            print(init.stdout[-2000:], init.stderr[-2000:], file=sys.stderr)
            return 1
        print(f"initialised {DATA}")
    log = open(LOGFILE, "ab")
    proc = subprocess.Popen(
        [
            str(base / "bin" / "mariadbd"), "--no-defaults", f"--basedir={base}", f"--datadir={DATA}",
            f"--socket={SOCKET}", f"--pid-file={PIDFILE}", f"--port={PORT}", f"--bind-address={BIND}",
            "--skip-name-resolve", "--character-set-server=utf8mb4", "--collation-server=utf8mb4_bin",
            "--innodb-buffer-pool-size=64M", "--max-connections=40",
        ],
        stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True,
    )
    for _ in range(120):
        if proc.poll() is not None:
            print(f"mariadbd exited early with {proc.returncode}; see {LOGFILE}", file=sys.stderr)
            return 1
        if ping(base):
            print(f"started (pid {proc.pid}) on {BIND}:{PORT}, socket {SOCKET}")
            return 0
        time.sleep(0.5)
    print("timed out waiting for the server; stopping it", file=sys.stderr)
    stop()
    return 1


def stop() -> int:
    base = find_basedir()
    pid = read_pid()
    if not pid:
        print("not running")
        return 0
    try:
        admin(base, "shutdown", check=False)
    except subprocess.TimeoutExpired:
        pass
    for _ in range(60):
        if not read_pid():
            print("stopped")
            return 0
        time.sleep(0.5)
    os.kill(pid, signal.SIGKILL)
    time.sleep(1)
    print("did not exit after a clean shutdown request; killed")
    return 0 if not read_pid() else 1


def status() -> int:
    pid = read_pid()
    if not pid:
        print("not running")
        return 1
    print(f"running, pid {pid}, {BIND}:{PORT}, socket {SOCKET}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=["start", "stop", "status", "destroy"])
    action = parser.parse_args().action
    if action == "start":
        return start()
    if action == "stop":
        return stop()
    if action == "status":
        return status()
    code = stop()
    shutil.rmtree(HOME, ignore_errors=True)
    print(f"removed {HOME}")
    return code


if __name__ == "__main__":
    sys.exit(main())
