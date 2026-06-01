from __future__ import annotations

from core.config.loader import ConfigStore
from core.credentials.base import CredentialStore
from core.engine.lifecycle import LaneEngine
from core.models import (
    AuditEntry,
    ConfigSummary,
    Lane,
    LaneActionResult,
    LaneDetail,
    RecordedLink,
    RecordedValue,
    StepInstance,
)
from core.persistence.context import PersistenceContext


class ReleaseService:
    """
    Facade the UI calls in-process.
    Contains no business logic — delegates entirely to LaneEngine and DALs.
    No PySide6 imports.
    """

    def __init__(
        self,
        ctx: PersistenceContext,
        config: ConfigStore,
        credentials: CredentialStore,
    ) -> None:
        self._ctx = ctx
        self._config = config
        self._credentials = credentials
        self._engine = LaneEngine(ctx, config, credentials)

    # ── Lane CRUD ────────────────────────────────────────────────────────────

    def create_lane(
        self,
        market: str,
        arcad_package: str,
        owner_user_id: str,
        jira_id: str,
        confluence_page: str,
        created_by_user_id: str,
        skip_steps: list[str] | None = None,
    ) -> Lane:
        return self._engine.create_lane(
            market, arcad_package, owner_user_id, jira_id, confluence_page,
            created_by_user_id, skip_steps=skip_steps,
        )

    def delete_lane(self, lane_id: str, acting_user_id: str) -> None:
        """Hard-delete a lane and all associated data. Writes a final audit entry first."""
        from core.engine.audit import AuditWriter
        # Write tombstone audit entry before deleting so the record exists if
        # external systems need it (export before delete is the user's responsibility).
        AuditWriter(self._ctx.audit).lane_deleted(lane_id, acting_user_id)
        self._ctx.lanes.delete_lane(lane_id)

    def get_lane(self, lane_id: str) -> Lane:
        lane = self._ctx.lanes.get_lane(lane_id)
        if not lane:
            raise ValueError(f"Lane '{lane_id}' not found")
        return lane

    def list_lanes(
        self, market: str | None = None, status: str | None = None
    ) -> list[Lane]:
        return self._ctx.lanes.list_lanes(market=market, status=status)

    def get_lane_detail(self, lane_id: str) -> LaneDetail:
        return self._engine.get_lane_detail(lane_id)

    # ── Step operations ──────────────────────────────────────────────────────

    def fire_step(
        self,
        lane_id: str,
        step_id: str,
        acting_user_id: str,
    ) -> StepInstance:
        """Fire the step's automated trigger. Idempotent."""
        return self._engine.fire_step(lane_id, step_id, acting_user_id)

    def advance_step(
        self,
        lane_id: str,
        step_id: str,
        acting_user_id: str,
        recorded_values: dict[str, str] | None = None,
        recorded_links: list[dict[str, str]] | None = None,
    ) -> StepInstance:
        return self._engine.advance_step(
            lane_id, step_id, acting_user_id, recorded_values, recorded_links
        )

    def skip_step(
        self, lane_id: str, step_id: str, acting_user_id: str, reason: str
    ) -> StepInstance:
        return self._engine.skip_step(lane_id, step_id, acting_user_id, reason)

    def override_step(
        self,
        lane_id: str,
        step_id: str,
        value: str,
        reason: str,
        acting_user_id: str,
    ) -> StepInstance:
        return self._engine.override_step(lane_id, step_id, value, reason, acting_user_id)

    # ── Recording ────────────────────────────────────────────────────────────

    def record_link(
        self,
        lane_id: str,
        step_id: str,
        label: str,
        url: str,
        acting_user_id: str,
    ) -> RecordedLink:
        import uuid
        from datetime import datetime, timezone
        from core.engine.audit import AuditWriter

        link = RecordedLink(
            id=str(uuid.uuid4()),
            step_instance_id=step_id,
            lane_id=lane_id,
            label=label,
            url=url,
            recorded_by_user_id=acting_user_id,
            recorded_at=datetime.now(timezone.utc).isoformat(),
        )
        self._ctx.links.insert_link(link)
        AuditWriter(self._ctx.audit).link_recorded(lane_id, step_id, acting_user_id, label)
        return link

    def record_value(
        self,
        lane_id: str,
        step_id: str,
        field_key: str,
        value: str,
        acting_user_id: str,
    ) -> RecordedValue:
        import uuid
        from datetime import datetime, timezone
        from core.engine.audit import AuditWriter

        rv = RecordedValue(
            id=str(uuid.uuid4()),
            step_instance_id=step_id,
            lane_id=lane_id,
            field_key=field_key,
            value=value,
            recorded_by_user_id=acting_user_id,
            recorded_at=datetime.now(timezone.utc).isoformat(),
        )
        self._ctx.recorded_values.insert_value(rv)
        AuditWriter(self._ctx.audit).value_recorded(lane_id, step_id, acting_user_id, field_key, "manual")
        return rv

    # ── External hold ────────────────────────────────────────────────────────

    def resume_external_hold(
        self,
        lane_id: str,
        step_id: str,
        acting_user_id: str,
        captured_values: dict[str, str] | None = None,
    ) -> StepInstance:
        return self._engine.resume_external_hold(
            lane_id, step_id, acting_user_id, captured_values
        )

    # ── Lane-level actions ───────────────────────────────────────────────────

    def invoke_lane_action(
        self,
        lane_id: str,
        action_id: str,
        inputs: dict[str, str],
        reason: str,
        acting_user_id: str,
    ) -> LaneActionResult:
        return self._engine.invoke_lane_action(
            lane_id, action_id, inputs, reason, acting_user_id
        )

    # ── Audit ────────────────────────────────────────────────────────────────

    def get_audit_log(self, lane_id: str) -> list[AuditEntry]:
        return self._ctx.audit.get_entries(lane_id)

    def refresh_status(self, lane_id: str, acting_user_id: str) -> StepInstance | None:
        """Live re-check for IN_PROGRESS steps. Called by UI Refresh and poller."""
        return self._engine.refresh_lane_status(lane_id, acting_user_id)

    def get_credential(self, user_id: str, tool_name: str) -> dict | None:
        return self._credentials.get_credential(user_id, tool_name)

    def set_credential(self, user_id: str, tool_name: str, credential: dict) -> None:
        self._credentials.set_credential(user_id, tool_name, credential)

    def delete_credential(self, user_id: str, tool_name: str) -> None:
        self._credentials.delete_credential(user_id, tool_name)

    def list_configured_tools(self, user_id: str) -> list[str]:
        if hasattr(self._credentials, "list_configured_tools"):
            return self._credentials.list_configured_tools(user_id)
        return self._ctx.credentials.list_tools(user_id)

    # ── Audit export ─────────────────────────────────────────────────────────

    def export_audit_csv(self, lane_id: str | None = None) -> str:
        """
        Return a CSV string of audit entries for one lane (or all lanes if
        lane_id is None). Columns: id, lane_id, step_instance_id,
        event_type, actor_user_id, at, detail.

        Suitable for writing to a .csv file for compliance export.
        """
        import csv
        import io

        rows = (
            self._ctx.audit.export_for_lane(lane_id)
            if lane_id
            else self._ctx.audit.export_all()
        )
        fieldnames = ["id", "lane_id", "step_instance_id", "event_type",
                      "actor_user_id", "at", "detail"]
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        return buf.getvalue()

    # ── Config introspection for UI dropdowns ────────────────────────────────

    def get_config_summary(self) -> ConfigSummary:
        return ConfigSummary(
            markets=self._config.list_markets(),
            templates=self._config.list_templates(),
            lane_actions=list(self._config.get_lane_actions().keys()),
        )
