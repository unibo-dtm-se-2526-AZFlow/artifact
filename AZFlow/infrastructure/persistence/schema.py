"""Helpers for loading and applying the PostgreSQL schema"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from psycopg import Connection

_SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def schema_sql() -> str:
    """Return the check-in schema SQL"""
    return _SCHEMA_PATH.read_text(encoding="utf-8")


def apply_schema(conn: "Connection") -> None:
    """Apply the check-in schema to a PostgreSQL connection"""
    with conn.cursor() as cursor:
        cursor.execute(schema_sql())
