from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from core.models import AuditEntry
from core.persistence.dal import AuditDAL


def _new_id() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AuditWriter:
    """Centralises audit-entry creation. Every call writes exactly one entry."""

    def __init__(self, dal: AuditDAL) -> None:
        self._dal = dal

    def _write(
        self,
        lane_id: str,
        event_type: str,
        actor: str,
        detail: dict[str, Any],
        step_id: str | None = None,
    ) -> None:
        self._dal.insert_entry(
            AuditEntry(
                id=_new_id(),
                lane_id=lane_id,
                step_instance_id=step_id,
                event_type=event_type,
                actor_user_id=actor,
                at=_now(),
                detail=detail,
            )
        )

    def lane_created(self, lane_id: str, actor: str, detail: dict) -> None:
        self._write(lane_id, "LANE_CREATED", actor, detail)

    def step_triggered(self, lane_id: str, step_id: str, actor: str) -> None:
        self._write(lane_id, "STEP_TRIGGERED", actor, {}, step_id)

    def step_result(
        self, lane_id: str, step_id: str, actor: str, status: str, detail: dict
    ) -> None:
        self._write(lane_id, "STEP_RESULT", actor, {"status": status, **detail}, step_id)

    def override_applied(
        self, lane_id: str, step_id: str, actor: str, value: str, reason: str
    ) -> None:
        self._write(
            lane_id, "OVERRIDE_APPLIED", actor,
            {"override_value": value, "reason": reason}, step_id,
        )

    def value_recorded(
        self, lane_id: str, step_id: str, actor: str, key: str, source: str
    ) -> None:
        self._write(
            lane_id, "VALUE_RECORDED", actor,
            {"key": key, "source": source}, step_id,
        )

    def link_recorded(self, lane_id: str, step_id: str, actor: str, label: str) -> None:
        self._write(lane_id, "LINK_RECORDED", actor, {"label": label}, step_id)

    def status_changed(
        self, lane_id: str, actor: str, old_status: str, new_status: str,
        step_id: str | None = None,
    ) -> None:
        self._write(
            lane_id, "STATUS_CHANGED", actor,
            {"old": old_status, "new": new_status}, step_id,
        )

    def lane_suspended(self, lane_id: str, step_id: str, actor: str) -> None:
        self._write(lane_id, "LANE_SUSPENDED", actor, {}, step_id)

    def lane_resumed(
        self, lane_id: str, step_id: str, actor: str, captured_keys: list[str]
    ) -> None:
        self._write(
            lane_id, "LANE_RESUMED", actor,
            {"captured_keys": captured_keys}, step_id,
        )

    def lane_action_invoked(
        self, lane_id: str, action_id: str, actor: str, reason: str
    ) -> None:
        self._write(
            lane_id, "LANE_ACTION_INVOKED", actor,
            {"action_id": action_id, "reason": reason},
        )

    def attribute_changed(
        self, lane_id: str, actor: str, changes: dict[str, tuple[str, str]]
    ) -> None:
        self._write(
            lane_id, "ATTRIBUTE_CHANGED", actor,
            {"changes": {k: {"from": v[0], "to": v[1]} for k, v in changes.items()}},
        )

    def lane_deleted(self, lane_id: str, actor: str) -> None:
        self._write(lane_id, "LANE_DELETED", actor, {})
