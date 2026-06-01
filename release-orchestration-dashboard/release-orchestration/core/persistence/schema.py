SCHEMA_VERSION = 1

CREATE_SCHEMA_VERSION = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
)
"""

CREATE_USERS = """
CREATE TABLE IF NOT EXISTS users (
    id           TEXT PRIMARY KEY,
    username     TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    created_at   TEXT NOT NULL
)
"""

CREATE_LANES = """
CREATE TABLE IF NOT EXISTS lanes (
    id                   TEXT PRIMARY KEY,
    market               TEXT NOT NULL,
    arcad_package        TEXT NOT NULL,
    branch_name          TEXT NOT NULL,
    owner_user_id        TEXT NOT NULL REFERENCES users(id),
    created_by_user_id   TEXT NOT NULL REFERENCES users(id),
    created_at           TEXT NOT NULL,
    workflow_template_id TEXT NOT NULL,
    status               TEXT NOT NULL DEFAULT 'ACTIVE',
    current_step_id      TEXT
)
"""

CREATE_LANE_ATTRIBUTES = """
CREATE TABLE IF NOT EXISTS lane_attributes (
    lane_id TEXT NOT NULL REFERENCES lanes(id),
    key     TEXT NOT NULL,
    value   TEXT NOT NULL,
    PRIMARY KEY (lane_id, key)
)
"""

CREATE_STEP_INSTANCES = """
CREATE TABLE IF NOT EXISTS step_instances (
    id                    TEXT NOT NULL,
    lane_id               TEXT NOT NULL REFERENCES lanes(id),
    seq_order             INTEGER NOT NULL,
    definition_ref        TEXT NOT NULL,
    label                 TEXT NOT NULL,
    kind                  TEXT NOT NULL DEFAULT 'standard',
    mode                  TEXT NOT NULL,
    view                  TEXT NOT NULL DEFAULT 'generic',
    status                TEXT NOT NULL DEFAULT 'PENDING',
    auto_result           TEXT NOT NULL DEFAULT 'UNKNOWN',
    produces              TEXT NOT NULL DEFAULT '[]',
    consumes              TEXT NOT NULL DEFAULT '[]',
    trigger_ref           TEXT NOT NULL DEFAULT '{}',
    post_actions          TEXT NOT NULL DEFAULT '[]',
    view_config           TEXT NOT NULL DEFAULT '{}',
    entered_at            TEXT,
    completed_at          TEXT,
    last_acted_by_user_id TEXT REFERENCES users(id),
    PRIMARY KEY (id, lane_id)
)
"""

CREATE_OVERRIDES = """
CREATE TABLE IF NOT EXISTS overrides (
    step_instance_id TEXT NOT NULL,
    lane_id          TEXT NOT NULL,
    value            TEXT NOT NULL,
    reason           TEXT NOT NULL,
    who_user_id      TEXT NOT NULL REFERENCES users(id),
    applied_at       TEXT NOT NULL,
    PRIMARY KEY (step_instance_id, lane_id),
    FOREIGN KEY (step_instance_id, lane_id) REFERENCES step_instances(id, lane_id)
)
"""

CREATE_VALUE_BAG = """
CREATE TABLE IF NOT EXISTS value_bag (
    lane_id             TEXT NOT NULL REFERENCES lanes(id),
    key                 TEXT NOT NULL,
    value               TEXT NOT NULL,
    produced_by_step_id TEXT NOT NULL,
    source              TEXT NOT NULL,
    recorded_at         TEXT NOT NULL,
    PRIMARY KEY (lane_id, key)
)
"""

CREATE_RECORDED_LINKS = """
CREATE TABLE IF NOT EXISTS recorded_links (
    id                  TEXT PRIMARY KEY,
    step_instance_id    TEXT NOT NULL,
    lane_id             TEXT NOT NULL,
    label               TEXT NOT NULL,
    url                 TEXT NOT NULL,
    recorded_by_user_id TEXT NOT NULL REFERENCES users(id),
    recorded_at         TEXT NOT NULL,
    FOREIGN KEY (step_instance_id, lane_id) REFERENCES step_instances(id, lane_id)
)
"""

CREATE_RECORDED_VALUES = """
CREATE TABLE IF NOT EXISTS recorded_values (
    id                  TEXT PRIMARY KEY,
    step_instance_id    TEXT NOT NULL,
    lane_id             TEXT NOT NULL,
    field_key           TEXT NOT NULL,
    value               TEXT NOT NULL,
    recorded_by_user_id TEXT NOT NULL REFERENCES users(id),
    recorded_at         TEXT NOT NULL,
    FOREIGN KEY (step_instance_id, lane_id) REFERENCES step_instances(id, lane_id)
)
"""

CREATE_AUDIT_ENTRIES = """
CREATE TABLE IF NOT EXISTS audit_entries (
    id               TEXT PRIMARY KEY,
    lane_id          TEXT NOT NULL REFERENCES lanes(id),
    step_instance_id TEXT,
    event_type       TEXT NOT NULL,
    actor_user_id    TEXT NOT NULL,
    at               TEXT NOT NULL,
    detail           TEXT NOT NULL DEFAULT '{}'
)
"""

CREATE_TRIGGER_ATTEMPTS = """
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
"""

CREATE_CREDENTIAL_STORE = """
CREATE TABLE IF NOT EXISTS credentials (
    user_id   TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    blob      TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, tool_name)
)
"""

SCHEMA_VERSION = 2

ALL_DDL = [
    CREATE_SCHEMA_VERSION,
    CREATE_USERS,
    CREATE_LANES,
    CREATE_LANE_ATTRIBUTES,
    CREATE_STEP_INSTANCES,
    CREATE_OVERRIDES,
    CREATE_VALUE_BAG,
    CREATE_RECORDED_LINKS,
    CREATE_RECORDED_VALUES,
    CREATE_AUDIT_ENTRIES,
    CREATE_TRIGGER_ATTEMPTS,
    CREATE_CREDENTIAL_STORE,
]
