"""Exceptions shared by the database layer and the command line."""

from __future__ import annotations


class DatabaseError(Exception):
    """The database is missing or unreachable, or the query could not run."""


class TargetError(ValueError):
    """The --db value is not a path or a supported database URL."""
