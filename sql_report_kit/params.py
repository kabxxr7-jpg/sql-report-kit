"""Validate and coerce user-supplied parameter strings. Nothing here builds SQL."""

from __future__ import annotations

import re
from datetime import date

from .queries import Query

MAX_TEXT_LENGTH = 200
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
MONTH_RE = re.compile(r"\d{4}-(0[1-9]|1[0-2])")
INT_RE = re.compile(r"-?\d{1,12}")


class ParamError(ValueError):
    """The user supplied a parameter that is unknown, missing or the wrong shape."""


def _coerce(name: str, type_spec: str, value: str) -> object:
    base, _, bounds = type_spec.partition(":")
    if base == "text":
        if len(value) > MAX_TEXT_LENGTH:
            raise ParamError(f"{name}: text is longer than {MAX_TEXT_LENGTH} characters")
        return value
    if base == "int":
        if not INT_RE.fullmatch(value):
            raise ParamError(f"{name}: expected a whole number, got {value!r}")
        number = int(value)
        if bounds:
            low, _, high = bounds.partition("..")
            if number < int(low) or number > int(high):
                raise ParamError(f"{name}: must be between {low} and {high}, got {number}")
        return number
    if base == "date":
        if not DATE_RE.fullmatch(value):
            raise ParamError(f"{name}: expected a date like 2025-03-31, got {value!r}")
        try:
            date.fromisoformat(value)
        except ValueError:
            raise ParamError(f"{name}: {value!r} is not a real calendar date") from None
        return value
    if base == "month":
        if not MONTH_RE.fullmatch(value):
            raise ParamError(f"{name}: expected a month like 2025-03, got {value!r}")
        return value
    raise ParamError(f"{name}: unsupported type {type_spec!r}")


def resolve_params(query: Query, supplied: dict[str, str]) -> dict[str, object]:
    """Return the full {name: value} mapping to bind, applying defaults and checking types."""
    known = {p.name: p for p in query.params}
    unknown = sorted(set(supplied) - set(known))
    if unknown:
        valid = ", ".join(sorted(known)) or "none"
        raise ParamError(f"unknown parameter(s) {', '.join(unknown)} for {query.name} (valid: {valid})")

    resolved: dict[str, object] = {}
    for param in query.params:
        if param.name in supplied:
            raw = supplied[param.name]
        elif param.required:
            raise ParamError(f"{param.name} is required for {query.name}: {param.help}")
        else:
            raw = param.default
        resolved[param.name] = _coerce(param.name, param.type, raw)
    return resolved


def parse_param_args(items: list[str]) -> dict[str, str]:
    """Turn ['k=v', ...] from the command line into a dict. A key given twice is an error."""
    supplied: dict[str, str] = {}
    for item in items:
        key, sep, value = item.partition("=")
        if not sep or not key:
            raise ParamError(f"--param expects key=value, got {item!r}")
        if key in supplied:
            raise ParamError(f"parameter {key} was given more than once")
        supplied[key] = value
    return supplied
