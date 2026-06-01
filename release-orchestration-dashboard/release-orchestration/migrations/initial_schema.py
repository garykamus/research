"""Migration 1: initial schema — tables created by ALL_DDL; nothing extra needed."""

MIGRATION_ID = 1


def up(conn) -> None:
    # Tables are already created via ALL_DDL in Database._run_migrations.
    # This migration exists as a version marker.
    pass


def down(conn) -> None:
    tables = [
        "audit_entries", "recorded_values", "recorded_links",
        "value_bag", "overrides", "step_instances",
        "lane_attributes", "lanes", "users", "schema_version",
    ]
    for t in tables:
        conn.execute(f"DROP TABLE IF EXISTS {t}")
