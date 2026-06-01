"""Migration 2: add trigger_attempts and credentials tables."""

MIGRATION_ID = 2


def up(conn) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trigger_attempts (
            id               TEXT PRIMARY KEY,
            lane_id          TEXT NOT NULL REFERENCES lanes(id),
            step_instance_id TEXT NOT NULL,
            attempt          INTEGER NOT NULL DEFAULT 1,
            fired_at         TEXT NOT NULL,
            external_ref     TEXT,
            status           TEXT NOT NULL DEFAULT 'IN_FLIGHT',
            UNIQUE (lane_id, step_instance_id, attempt)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS credentials (
            user_id    TEXT NOT NULL,
            tool_name  TEXT NOT NULL,
            blob       TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (user_id, tool_name)
        )
    """)


def down(conn) -> None:
    conn.execute("DROP TABLE IF EXISTS trigger_attempts")
    conn.execute("DROP TABLE IF EXISTS credentials")
