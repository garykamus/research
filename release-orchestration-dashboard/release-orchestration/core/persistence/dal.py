from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone

from core.models import (
    AuditEntry,
    Lane,
    Override,
    RecordedLink,
    RecordedValue,
    StepInstance,
    User,
    ValueBagEntry,
)

from .database import Database


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


class UserDAL:
    def __init__(self, db: Database) -> None:
        self._db = db

    def _conn(self) -> sqlite3.Connection:
        return self._db.connect()

    def get_or_create_default_user(self, username: str, display_name: str) -> User:
        conn = self._conn()
        row = conn.execute(
            "SELECT id, username, display_name, created_at FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        if row:
            return User(id=row[0], username=row[1], display_name=row[2], created_at=row[3])
        return self.create_user(username, display_name)

    def create_user(self, username: str, display_name: str) -> User:
        conn = self._conn()
        user = User(
            id=_new_id(),
            username=username,
            display_name=display_name,
            created_at=_now_iso(),
        )
        with conn:
            conn.execute(
                "INSERT INTO users (id, username, display_name, created_at) VALUES (?, ?, ?, ?)",
                (user.id, user.username, user.display_name, user.created_at),
            )
        return user

    def get_user(self, user_id: str) -> User | None:
        conn = self._conn()
        row = conn.execute(
            "SELECT id, username, display_name, created_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if not row:
            return None
        return User(id=row[0], username=row[1], display_name=row[2], created_at=row[3])


class LaneDAL:
    def __init__(self, db: Database) -> None:
        self._db = db

    def _conn(self) -> sqlite3.Connection:
        return self._db.connect()

    def insert_lane(self, lane: Lane) -> None:
        conn = self._conn()
        with conn:
            conn.execute(
                """INSERT INTO lanes
                   (id, market, arcad_package, branch_name, owner_user_id,
                    created_by_user_id, created_at, workflow_template_id,
                    status, current_step_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    lane.id, lane.market, lane.arcad_package, lane.branch_name,
                    lane.owner_user_id, lane.created_by_user_id, lane.created_at,
                    lane.workflow_template_id, lane.status, lane.current_step_id,
                ),
            )

    def get_lane(self, lane_id: str) -> Lane | None:
        conn = self._conn()
        row = conn.execute("SELECT * FROM lanes WHERE id = ?", (lane_id,)).fetchone()
        return self._row_to_lane(row) if row else None

    def list_lanes(
        self, market: str | None = None, status: str | None = None
    ) -> list[Lane]:
        conn = self._conn()
        query = "SELECT * FROM lanes WHERE 1=1"
        params: list[str] = []
        if market:
            query += " AND market = ?"
            params.append(market)
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY created_at DESC"
        rows = conn.execute(query, params).fetchall()
        return [self._row_to_lane(r) for r in rows]

    def update_lane_status(
        self, lane_id: str, status: str, current_step_id: str | None
    ) -> None:
        conn = self._conn()
        with conn:
            conn.execute(
                "UPDATE lanes SET status = ?, current_step_id = ? WHERE id = ?",
                (status, current_step_id, lane_id),
            )

    def update_lane_package(
        self, lane_id: str, arcad_package: str, branch_name: str
    ) -> None:
        """Updates both mutable name fields atomically."""
        conn = self._conn()
        with conn:
            conn.execute(
                "UPDATE lanes SET arcad_package = ?, branch_name = ? WHERE id = ?",
                (arcad_package, branch_name, lane_id),
            )

    def get_lane_attributes(self, lane_id: str) -> dict[str, str]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT key, value FROM lane_attributes WHERE lane_id = ?", (lane_id,)
        ).fetchall()
        return {r[0]: r[1] for r in rows}

    def set_lane_attribute(self, lane_id: str, key: str, value: str) -> None:
        conn = self._conn()
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO lane_attributes (lane_id, key, value) VALUES (?, ?, ?)",
                (lane_id, key, value),
            )

    def set_lane_attributes(self, lane_id: str, attrs: dict[str, str]) -> None:
        conn = self._conn()
        with conn:
            for key, value in attrs.items():
                conn.execute(
                    "INSERT OR REPLACE INTO lane_attributes (lane_id, key, value) VALUES (?, ?, ?)",
                    (lane_id, key, value),
                )

    def delete_lane(self, lane_id: str) -> None:
        """
        Hard-delete a lane and all its associated data.
        Cascades to: lane_attributes, step_instances, value_bag, overrides,
        recorded_links, recorded_values, trigger_attempts, audit_entries.
        """
        conn = self._conn()
        with conn:
            for table, col in [
                ("lane_attributes",   "lane_id"),
                ("step_instances",    "lane_id"),
                ("value_bag",         "lane_id"),
                ("overrides",         "lane_id"),
                ("recorded_links",    "lane_id"),
                ("recorded_values",   "lane_id"),
                ("trigger_attempts",  "lane_id"),
                ("audit_entries",     "lane_id"),
            ]:
                conn.execute(f"DELETE FROM {table} WHERE {col} = ?", (lane_id,))
            conn.execute("DELETE FROM lanes WHERE id = ?", (lane_id,))

    @staticmethod
    def _row_to_lane(row: sqlite3.Row) -> Lane:
        return Lane(
            id=row["id"],
            market=row["market"],
            arcad_package=row["arcad_package"],
            branch_name=row["branch_name"],
            owner_user_id=row["owner_user_id"],
            created_by_user_id=row["created_by_user_id"],
            created_at=row["created_at"],
            workflow_template_id=row["workflow_template_id"],
            status=row["status"],
            current_step_id=row["current_step_id"],
        )


class StepInstanceDAL:
    def __init__(self, db: Database) -> None:
        self._db = db

    def _conn(self) -> sqlite3.Connection:
        return self._db.connect()

    def insert_step_instances(self, steps: list[StepInstance]) -> None:
        conn = self._conn()
        with conn:
            for s in steps:
                conn.execute(
                    """INSERT INTO step_instances
                       (id, lane_id, seq_order, definition_ref, label, kind, mode, view,
                        status, auto_result, produces, consumes, trigger_ref, post_actions,
                        view_config, entered_at, completed_at, last_acted_by_user_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        s.id, s.lane_id, s.seq_order, s.definition_ref, s.label,
                        s.kind, s.mode, s.view, s.status, s.auto_result,
                        json.dumps(s.produces), json.dumps(s.consumes),
                        json.dumps(s.trigger_ref), json.dumps(s.post_actions),
                        json.dumps(s.view_config),
                        s.entered_at, s.completed_at, s.last_acted_by_user_id,
                    ),
                )

    def get_step_instance(self, lane_id: str, step_id: str) -> StepInstance | None:
        conn = self._conn()
        row = conn.execute(
            "SELECT * FROM step_instances WHERE lane_id = ? AND id = ?",
            (lane_id, step_id),
        ).fetchone()
        return self._row_to_step(row) if row else None

    def list_step_instances(self, lane_id: str) -> list[StepInstance]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM step_instances WHERE lane_id = ? ORDER BY seq_order",
            (lane_id,),
        ).fetchall()
        return [self._row_to_step(r) for r in rows]

    def update_step_status(
        self,
        lane_id: str,
        step_id: str,
        status: str,
        auto_result: str,
        acted_by: str,
    ) -> None:
        conn = self._conn()
        with conn:
            conn.execute(
                """UPDATE step_instances
                   SET status = ?, auto_result = ?, last_acted_by_user_id = ?
                   WHERE lane_id = ? AND id = ?""",
                (status, auto_result, acted_by, lane_id, step_id),
            )

    def update_step_times(
        self,
        lane_id: str,
        step_id: str,
        entered_at: str | None,
        completed_at: str | None,
    ) -> None:
        conn = self._conn()
        with conn:
            conn.execute(
                """UPDATE step_instances
                   SET entered_at = ?, completed_at = ?
                   WHERE lane_id = ? AND id = ?""",
                (entered_at, completed_at, lane_id, step_id),
            )

    @staticmethod
    def _row_to_step(row: sqlite3.Row) -> StepInstance:
        return StepInstance(
            id=row["id"],
            lane_id=row["lane_id"],
            seq_order=row["seq_order"],
            definition_ref=row["definition_ref"],
            label=row["label"],
            kind=row["kind"],
            mode=row["mode"],
            view=row["view"],
            status=row["status"],
            auto_result=row["auto_result"],
            produces=json.loads(row["produces"]),
            consumes=json.loads(row["consumes"]),
            trigger_ref=json.loads(row["trigger_ref"]),
            post_actions=json.loads(row["post_actions"]),
            view_config=json.loads(row["view_config"]),
            entered_at=row["entered_at"],
            completed_at=row["completed_at"],
            last_acted_by_user_id=row["last_acted_by_user_id"],
        )


class OverrideDAL:
    def __init__(self, db: Database) -> None:
        self._db = db

    def _conn(self) -> sqlite3.Connection:
        return self._db.connect()

    def upsert_override(self, override: Override) -> None:
        conn = self._conn()
        with conn:
            conn.execute(
                """INSERT OR REPLACE INTO overrides
                   (step_instance_id, lane_id, value, reason, who_user_id, applied_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    override.step_instance_id, override.lane_id,
                    override.value, override.reason,
                    override.who_user_id, override.applied_at,
                ),
            )

    def get_override(self, lane_id: str, step_id: str) -> Override | None:
        conn = self._conn()
        row = conn.execute(
            "SELECT * FROM overrides WHERE lane_id = ? AND step_instance_id = ?",
            (lane_id, step_id),
        ).fetchone()
        if not row:
            return None
        return Override(
            step_instance_id=row["step_instance_id"],
            lane_id=row["lane_id"],
            value=row["value"],
            reason=row["reason"],
            who_user_id=row["who_user_id"],
            applied_at=row["applied_at"],
        )

    def get_overrides_for_lane(self, lane_id: str) -> dict[str, Override]:
        """Returns {step_id: Override} for all steps in the lane."""
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM overrides WHERE lane_id = ?", (lane_id,)
        ).fetchall()
        return {
            r["step_instance_id"]: Override(
                step_instance_id=r["step_instance_id"],
                lane_id=r["lane_id"],
                value=r["value"],
                reason=r["reason"],
                who_user_id=r["who_user_id"],
                applied_at=r["applied_at"],
            )
            for r in rows
        }


class ValueBagDAL:
    def __init__(self, db: Database) -> None:
        self._db = db

    def _conn(self) -> sqlite3.Connection:
        return self._db.connect()

    def upsert_value(
        self,
        lane_id: str,
        key: str,
        value: str,
        produced_by: str,
        source: str,
    ) -> None:
        conn = self._conn()
        with conn:
            conn.execute(
                """INSERT OR REPLACE INTO value_bag
                   (lane_id, key, value, produced_by_step_id, source, recorded_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (lane_id, key, value, produced_by, source, _now_iso()),
            )

    def get_bag(self, lane_id: str) -> dict[str, str]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT key, value FROM value_bag WHERE lane_id = ?", (lane_id,)
        ).fetchall()
        return {r[0]: r[1] for r in rows}

    def get_value(self, lane_id: str, key: str) -> str | None:
        conn = self._conn()
        row = conn.execute(
            "SELECT value FROM value_bag WHERE lane_id = ? AND key = ?",
            (lane_id, key),
        ).fetchone()
        return row[0] if row else None


class RecordedLinkDAL:
    def __init__(self, db: Database) -> None:
        self._db = db

    def _conn(self) -> sqlite3.Connection:
        return self._db.connect()

    def insert_link(self, link: RecordedLink) -> None:
        conn = self._conn()
        with conn:
            conn.execute(
                """INSERT INTO recorded_links
                   (id, step_instance_id, lane_id, label, url, recorded_by_user_id, recorded_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    link.id, link.step_instance_id, link.lane_id,
                    link.label, link.url, link.recorded_by_user_id, link.recorded_at,
                ),
            )

    def get_links_for_step(self, lane_id: str, step_id: str) -> list[RecordedLink]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM recorded_links WHERE lane_id = ? AND step_instance_id = ? ORDER BY recorded_at",
            (lane_id, step_id),
        ).fetchall()
        return [self._row_to_link(r) for r in rows]

    def get_links_for_lane(self, lane_id: str) -> list[RecordedLink]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM recorded_links WHERE lane_id = ? ORDER BY recorded_at",
            (lane_id,),
        ).fetchall()
        return [self._row_to_link(r) for r in rows]

    @staticmethod
    def _row_to_link(row: sqlite3.Row) -> RecordedLink:
        return RecordedLink(
            id=row["id"],
            step_instance_id=row["step_instance_id"],
            lane_id=row["lane_id"],
            label=row["label"],
            url=row["url"],
            recorded_by_user_id=row["recorded_by_user_id"],
            recorded_at=row["recorded_at"],
        )


class RecordedValueDAL:
    def __init__(self, db: Database) -> None:
        self._db = db

    def _conn(self) -> sqlite3.Connection:
        return self._db.connect()

    def insert_value(self, rv: RecordedValue) -> None:
        conn = self._conn()
        with conn:
            conn.execute(
                """INSERT INTO recorded_values
                   (id, step_instance_id, lane_id, field_key, value, recorded_by_user_id, recorded_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    rv.id, rv.step_instance_id, rv.lane_id,
                    rv.field_key, rv.value, rv.recorded_by_user_id, rv.recorded_at,
                ),
            )

    def get_values_for_step(self, lane_id: str, step_id: str) -> list[RecordedValue]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM recorded_values WHERE lane_id = ? AND step_instance_id = ? ORDER BY recorded_at",
            (lane_id, step_id),
        ).fetchall()
        return [
            RecordedValue(
                id=r["id"],
                step_instance_id=r["step_instance_id"],
                lane_id=r["lane_id"],
                field_key=r["field_key"],
                value=r["value"],
                recorded_by_user_id=r["recorded_by_user_id"],
                recorded_at=r["recorded_at"],
            )
            for r in rows
        ]


class AuditDAL:
    def __init__(self, db: Database) -> None:
        self._db = db

    def _conn(self) -> sqlite3.Connection:
        return self._db.connect()

    def insert_entry(self, entry: AuditEntry) -> None:
        conn = self._conn()
        with conn:
            conn.execute(
                """INSERT INTO audit_entries
                   (id, lane_id, step_instance_id, event_type, actor_user_id, at, detail)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry.id, entry.lane_id, entry.step_instance_id,
                    entry.event_type, entry.actor_user_id, entry.at,
                    json.dumps(entry.detail),
                ),
            )

    def get_entries(self, lane_id: str) -> list[AuditEntry]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM audit_entries WHERE lane_id = ? ORDER BY at",
            (lane_id,),
        ).fetchall()
        return [
            AuditEntry(
                id=r["id"],
                lane_id=r["lane_id"],
                step_instance_id=r["step_instance_id"],
                event_type=r["event_type"],
                actor_user_id=r["actor_user_id"],
                at=r["at"],
                detail=json.loads(r["detail"]),
            )
            for r in rows
        ]

    def export_for_lane(self, lane_id: str) -> list[dict]:
        """
        Return all audit entries for a lane as flat dicts suitable for CSV export.
        detail is serialised as a JSON string so each row has uniform columns.
        """
        entries = self.get_entries(lane_id)
        return [
            {
                "id": e.id,
                "lane_id": e.lane_id,
                "step_instance_id": e.step_instance_id or "",
                "event_type": e.event_type,
                "actor_user_id": e.actor_user_id or "",
                "at": e.at,
                "detail": json.dumps(e.detail),
            }
            for e in entries
        ]

    def export_all(self) -> list[dict]:
        """Return audit entries for ALL lanes — used by compliance bulk export."""
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM audit_entries ORDER BY lane_id, at"
        ).fetchall()
        return [
            {
                "id": r["id"],
                "lane_id": r["lane_id"],
                "step_instance_id": r["step_instance_id"] or "",
                "event_type": r["event_type"],
                "actor_user_id": r["actor_user_id"] or "",
                "at": r["at"],
                "detail": r["detail"],
            }
            for r in rows
        ]


class TriggerAttemptDAL:
    """Idempotency store — tracks fired trigger attempts per (lane, step, attempt#)."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def _conn(self) -> sqlite3.Connection:
        return self._db.connect()

    def record_attempt(
        self,
        lane_id: str,
        step_id: str,
        attempt: int,
        external_ref: str | None = None,
    ) -> str:
        """Insert a new IN_FLIGHT attempt. Returns the attempt id."""
        attempt_id = _new_id()
        conn = self._conn()
        with conn:
            conn.execute(
                """INSERT OR IGNORE INTO trigger_attempts
                   (id, lane_id, step_instance_id, attempt, fired_at, external_ref, status)
                   VALUES (?, ?, ?, ?, ?, ?, 'IN_FLIGHT')""",
                (attempt_id, lane_id, step_id, attempt, _now_iso(), external_ref),
            )
        return attempt_id

    def get_latest_attempt(self, lane_id: str, step_id: str) -> dict | None:
        conn = self._conn()
        row = conn.execute(
            """SELECT * FROM trigger_attempts
               WHERE lane_id = ? AND step_instance_id = ?
               ORDER BY attempt DESC LIMIT 1""",
            (lane_id, step_id),
        ).fetchone()
        if not row:
            return None
        return dict(row)

    def update_status(self, attempt_id: str, status: str, external_ref: str | None = None) -> None:
        conn = self._conn()
        with conn:
            if external_ref is not None:
                conn.execute(
                    "UPDATE trigger_attempts SET status = ?, external_ref = ? WHERE id = ?",
                    (status, external_ref, attempt_id),
                )
            else:
                conn.execute(
                    "UPDATE trigger_attempts SET status = ? WHERE id = ?",
                    (status, attempt_id),
                )

    def already_fired(self, lane_id: str, step_id: str) -> bool:
        """True if any IN_FLIGHT or COMPLETED attempt exists — prevents double-fire."""
        conn = self._conn()
        row = conn.execute(
            """SELECT COUNT(*) FROM trigger_attempts
               WHERE lane_id = ? AND step_instance_id = ?
               AND status IN ('IN_FLIGHT', 'COMPLETED')""",
            (lane_id, step_id),
        ).fetchone()
        return (row[0] > 0)


class CredentialDAL:
    """
    Stores encrypted credential blobs per (user_id, tool_name).
    Blob is encrypted by the CredentialStore before being handed here.
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    def _conn(self) -> sqlite3.Connection:
        return self._db.connect()

    def upsert(self, user_id: str, tool_name: str, blob: str) -> None:
        conn = self._conn()
        with conn:
            conn.execute(
                """INSERT OR REPLACE INTO credentials (user_id, tool_name, blob, updated_at)
                   VALUES (?, ?, ?, ?)""",
                (user_id, tool_name, blob, _now_iso()),
            )

    def get(self, user_id: str, tool_name: str) -> str | None:
        conn = self._conn()
        row = conn.execute(
            "SELECT blob FROM credentials WHERE user_id = ? AND tool_name = ?",
            (user_id, tool_name),
        ).fetchone()
        return row[0] if row else None

    def delete(self, user_id: str, tool_name: str) -> None:
        conn = self._conn()
        with conn:
            conn.execute(
                "DELETE FROM credentials WHERE user_id = ? AND tool_name = ?",
                (user_id, tool_name),
            )

    def list_tools(self, user_id: str) -> list[str]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT tool_name FROM credentials WHERE user_id = ?", (user_id,)
        ).fetchall()
        return [r[0] for r in rows]
