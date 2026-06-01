from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from .schema import ALL_DDL, SCHEMA_VERSION


class Database:
    """
    Manages SQLite connections and migration lifecycle.
    Each caller gets a per-thread connection (WAL mode).
    No sqlite3 types leak outside this module.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._local = threading.local()
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        # Run migrations on the calling thread's connection.
        conn = self.connect()
        self._run_migrations(conn)

    def connect(self) -> sqlite3.Connection:
        """Return the per-thread connection, creating it if needed."""
        if not getattr(self._local, "conn", None):
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return self._local.conn

    def _run_migrations(self, conn: sqlite3.Connection) -> None:
        from .migrations import MIGRATIONS

        # Apply schema DDL tables (idempotent — IF NOT EXISTS).
        with conn:
            for ddl in ALL_DDL:
                conn.execute(ddl)

        current = self._get_schema_version(conn)
        for version, migration_fn in MIGRATIONS:
            if version > current:
                with conn:
                    migration_fn(conn)
                self._set_schema_version(conn, version)

    def _get_schema_version(self, conn: sqlite3.Connection) -> int:
        row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
        return row[0] if row else 0

    def _set_schema_version(self, conn: sqlite3.Connection, version: int) -> None:
        with conn:
            existing = conn.execute(
                "SELECT COUNT(*) FROM schema_version"
            ).fetchone()[0]
            if existing:
                conn.execute("UPDATE schema_version SET version = ?", (version,))
            else:
                conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
