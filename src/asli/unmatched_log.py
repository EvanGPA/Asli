"""Counts dish names that matched nothing in the databank (spec 5.2)."""

import sqlite3
from pathlib import Path


class UnmatchedLog:
    def __init__(self, path: str | Path):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._execute(
            "CREATE TABLE IF NOT EXISTS unmatched (name TEXT PRIMARY KEY, count INTEGER NOT NULL)"
        )

    def record(self, name: str) -> None:
        key = name.strip().lower()
        if not key:
            return
        self._execute(
            "INSERT INTO unmatched (name, count) VALUES (?, 1) "
            "ON CONFLICT(name) DO UPDATE SET count = count + 1",
            (key,),
        )

    def most_common(self, limit: int = 20) -> list[tuple[str, int]]:
        rows = self._execute(
            "SELECT name, count FROM unmatched ORDER BY count DESC, name LIMIT ?", (limit,)
        )
        return [(name, count) for name, count in rows]

    def _execute(self, sql: str, params: tuple = ()) -> list[tuple]:
        conn = sqlite3.connect(self._path)
        try:
            with conn:
                return conn.execute(sql, params).fetchall()
        finally:
            conn.close()
