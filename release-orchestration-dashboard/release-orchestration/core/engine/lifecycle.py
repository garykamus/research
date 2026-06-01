from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from core.config.loader import ConfigStore
from core.config.resolver import LaneResolver
from core.config.templating import TemplateResolver
from core.credentials.base import CredentialStore
from core.models import (
    Lane,
    LaneActionResult,
    LaneDetail,
    Override,
    RecordedLink,
    RecordedValue,
    StepInstance,
)
from core.persistence.context import PersistenceContext
from core.triggers.registry import TriggerExecutorRegistry

from .advancement import AdvancementEngine
from .audit import AuditWriter
from .value_bag import ValueBagValidator


def _new_id() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class LaneEngine:
    """
    Central engine. Called by ReleaseService.
    All methods write audit entries. All DB access via PersistenceContext.
    No PySide6 imports anywhere in this file.
    """

    def __init__(
        self,
        ctx: PersistenceContext,
        config: ConfigStore,
        credentials: CredentialStore | None = None,
    ) -> None:
        self._ctx = ctx
        self._config = config
        self._credentials = credentials
        self._resolver = LaneResolver(config)
        self._advancer = AdvancementEngine()
        self._bag_validator = ValueBagValidator()
        self._trigger_registry = TriggerExecutorRegistry()
        self._template_resolver = TemplateResolver()

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
        """
        skip_steps: step IDs to pre-mark SKIPPED at creation (Approach B).
        Used when the user ticks "Package already exists" — skips create_arcad_package
        so the lane starts directly at create_pr.
        """
        skip_set = set(skip_steps or [])

        seeded = {
            "market": market,
            "arcad_package": arcad_package,
            "branch_name": arcad_package,
            "jira_id": jira_id,
            "confluence_page": confluence_page,
        }
        resolved_steps = self._resolver.resolve(market, seeded)

        binding = self._config.get_market_binding(market)
        template_id = binding.get("use", "backbone")
        owner_display = binding.get("default_owner", "")

        lane_id = _new_id()
        now = _now()
        lane = Lane(
            id=lane_id,
            market=market,
            arcad_package=arcad_package,
            branch_name=arcad_package,
            owner_user_id=owner_user_id,
            created_by_user_id=created_by_user_id,
            created_at=now,
            workflow_template_id=template_id,
            status="ACTIVE",
            current_step_id=None,
        )
        self._ctx.lanes.insert_lane(lane)

        # Lane attributes (the full KV set for templating).
        attrs = {
            "market": market,
            "arcad_package": arcad_package,
            "branch_name": arcad_package,
            "owner": owner_display,
            "jira_id": jira_id,
            "confluence_page": confluence_page,
        }
        self._ctx.lanes.set_lane_attributes(lane_id, attrs)

        # Build and insert StepInstance rows.
        # Steps in skip_set are pre-marked SKIPPED at creation.
        step_instances: list[StepInstance] = []
        for step_def in resolved_steps:
            step_id = step_def["_step_id"]
            pre_skipped = step_id in skip_set
            si = StepInstance(
                id=step_id,
                lane_id=lane_id,
                seq_order=step_def["_order"],
                definition_ref=step_id,
                label=step_def.get("label", step_id),
                kind=step_def.get("kind", "standard"),
                mode=step_def.get("mode", "MANUAL"),
                view=step_def.get("view", "generic"),
                status="SKIPPED" if pre_skipped else "PENDING",
                auto_result="UNKNOWN",
                produces=step_def.get("produces", []),
                consumes=step_def.get("consumes", []),
                trigger_ref=step_def.get("trigger", {"type": "none"}),
                post_actions=step_def.get("post_actions", []),
                view_config=step_def.get("view_config", {}),
                entered_at=None,
                completed_at=now if pre_skipped else None,
                last_acted_by_user_id=created_by_user_id if pre_skipped else None,
            )
            step_instances.append(si)
        self._ctx.steps.insert_step_instances(step_instances)

        # Audit pre-skipped steps.
        audit = AuditWriter(self._ctx.audit)
        for si in step_instances:
            if si.status == "SKIPPED":
                audit.status_changed(
                    lane_id, created_by_user_id, "PENDING", "SKIPPED", si.id
                )

        # Set current step and initial lane status.
        first = self._advancer.first_eligible_step(step_instances)
        lane_status = self._advancer.compute_lane_status(step_instances, first)
        current_step_id = first.id if first else None
        self._ctx.lanes.update_lane_status(lane_id, lane_status, current_step_id)

        if first and first.kind == "external_hold":
            self._ctx.steps.update_step_status(
                lane_id, first.id, "SUSPENDED", "UNKNOWN", created_by_user_id
            )
            audit.lane_suspended(lane_id, first.id, created_by_user_id)

        audit.lane_created(lane_id, created_by_user_id, {
            "market": market,
            "arcad_package": arcad_package,
            "template": template_id,
            "step_count": len(step_instances),
            "pre_skipped": list(skip_set),
        })

        lane.status = lane_status
        lane.current_step_id = current_step_id
        return lane

    def get_lane_detail(self, lane_id: str) -> LaneDetail:
        lane = self._ctx.lanes.get_lane(lane_id)
        if not lane:
            raise ValueError(f"Lane '{lane_id}' not found")
        attrs = self._ctx.lanes.get_lane_attributes(lane_id)
        steps = self._ctx.steps.list_step_instances(lane_id)
        overrides = self._ctx.overrides.get_overrides_for_lane(lane_id)
        for step in steps:
            step.override = overrides.get(step.id)
        bag = self._ctx.bag.get_bag(lane_id)
        links = self._ctx.links.get_links_for_lane(lane_id)
        return LaneDetail(lane=lane, attributes=attrs, steps=steps, bag=bag, links=links)

    def advance_step(
        self,
        lane_id: str,
        step_id: str,
        acting_user_id: str,
        recorded_values: dict[str, str] | None = None,
        recorded_links: list[dict[str, str]] | None = None,
    ) -> StepInstance:
        step = self._ctx.steps.get_step_instance(lane_id, step_id)
        if not step:
            raise ValueError(f"Step '{step_id}' not found in lane '{lane_id}'")
        if step.status in ("DONE", "SKIPPED"):
            raise ValueError(f"Step '{step_id}' is already {step.status}")

        bag = self._ctx.bag.get_bag(lane_id)
        attrs = self._ctx.lanes.get_lane_attributes(lane_id)

        # Consume-gating: all required values must be present.
        missing = self._bag_validator.validate_consumes(step, bag, attrs)
        if missing:
            raise ValueError(
                f"Step '{step_id}' cannot proceed: missing required value(s): "
                + ", ".join(f"'{k}'" for k in missing)
            )

        audit = AuditWriter(self._ctx.audit)
        now = _now()

        # Write recorded values and promote produces to value bag.
        rv_dict = recorded_values or {}
        promoted = self._bag_validator.promote_to_bag(step, rv_dict, self._ctx, acting_user_id)
        for key in promoted:
            audit.value_recorded(lane_id, step_id, acting_user_id, key, "manual")

        # Persist any non-produces recorded values as RecordedValue rows.
        for field_key, value in rv_dict.items():
            if field_key not in step.produces:
                rv = RecordedValue(
                    id=_new_id(),
                    step_instance_id=step_id,
                    lane_id=lane_id,
                    field_key=field_key,
                    value=value,
                    recorded_by_user_id=acting_user_id,
                    recorded_at=now,
                )
                self._ctx.recorded_values.insert_value(rv)

        # Write recorded links.
        for link_data in (recorded_links or []):
            link = RecordedLink(
                id=_new_id(),
                step_instance_id=step_id,
                lane_id=lane_id,
                label=link_data.get("label", ""),
                url=link_data.get("url", ""),
                recorded_by_user_id=acting_user_id,
                recorded_at=now,
            )
            self._ctx.links.insert_link(link)
            audit.link_recorded(lane_id, step_id, acting_user_id, link.label)

        # Mark step DONE.
        self._ctx.steps.update_step_status(lane_id, step_id, "DONE", "SUCCESS", acting_user_id)
        self._ctx.steps.update_step_times(
            lane_id, step_id,
            entered_at=step.entered_at or now,
            completed_at=now,
        )
        audit.step_result(lane_id, step_id, acting_user_id, "DONE", {
            "produced": promoted,
        })

        # Advance lane.
        self._advance_lane(lane_id, step_id, acting_user_id)

        # Fire post-actions (side-effects on manual completion too).
        bag_at_done = self._ctx.bag.get_bag(lane_id)
        attrs_at_done = self._ctx.lanes.get_lane_attributes(lane_id)
        binding = self._config.get_market_binding(attrs_at_done.get("market", ""))
        tools_cfg = self._config.get_tools()
        post_ctx = self._template_resolver.build_context(attrs_at_done, bag_at_done, binding, tools_cfg)
        self._fire_post_actions(step, "DONE", post_ctx, acting_user_id, audit)

        step.status = "DONE"
        step.auto_result = "SUCCESS"
        step.completed_at = now
        return step

    def skip_step(
        self, lane_id: str, step_id: str, acting_user_id: str, reason: str
    ) -> StepInstance:
        step = self._ctx.steps.get_step_instance(lane_id, step_id)
        if not step:
            raise ValueError(f"Step '{step_id}' not found in lane '{lane_id}'")
        if step.status in ("DONE", "SKIPPED"):
            raise ValueError(f"Step '{step_id}' is already {step.status}")

        audit = AuditWriter(self._ctx.audit)
        old_status = step.status
        self._ctx.steps.update_step_status(lane_id, step_id, "SKIPPED", "UNKNOWN", acting_user_id)
        audit.status_changed(lane_id, acting_user_id, old_status, "SKIPPED", step_id)
        self._advance_lane(lane_id, step_id, acting_user_id)

        step.status = "SKIPPED"
        return step

    def override_step(
        self,
        lane_id: str,
        step_id: str,
        value: str,
        reason: str,
        acting_user_id: str,
    ) -> StepInstance:
        if not reason or not reason.strip():
            raise ValueError("Override requires a non-empty reason (attributability mandate)")

        step = self._ctx.steps.get_step_instance(lane_id, step_id)
        if not step:
            raise ValueError(f"Step '{step_id}' not found in lane '{lane_id}'")

        ov = Override(
            step_instance_id=step_id,
            lane_id=lane_id,
            value=value,
            reason=reason.strip(),
            who_user_id=acting_user_id,
            applied_at=_now(),
        )
        self._ctx.overrides.upsert_override(ov)
        AuditWriter(self._ctx.audit).override_applied(lane_id, step_id, acting_user_id, value, reason)

        # If the override makes the step effectively done, advance the lane.
        if value == "DONE":
            self._advance_lane(lane_id, step_id, acting_user_id)

        step.override = ov
        return step

    def resume_external_hold(
        self,
        lane_id: str,
        step_id: str,
        acting_user_id: str,
        captured_values: dict[str, str] | None = None,
    ) -> StepInstance:
        step = self._ctx.steps.get_step_instance(lane_id, step_id)
        if not step:
            raise ValueError(f"Step '{step_id}' not found in lane '{lane_id}'")
        if step.kind != "external_hold":
            raise ValueError(f"Step '{step_id}' is not an external_hold step")
        if step.status != "SUSPENDED":
            raise ValueError(f"Step '{step_id}' is not SUSPENDED (currently: {step.status})")

        audit = AuditWriter(self._ctx.audit)
        now = _now()
        captured_keys: list[str] = []

        # Write captured values into the bag.
        for key, val in (captured_values or {}).items():
            self._ctx.bag.upsert_value(lane_id, key, val, step_id, "manual")
            audit.value_recorded(lane_id, step_id, acting_user_id, key, "manual")
            captured_keys.append(key)

        # Mark step DONE.
        self._ctx.steps.update_step_status(lane_id, step_id, "DONE", "SUCCESS", acting_user_id)
        self._ctx.steps.update_step_times(lane_id, step_id, entered_at=now, completed_at=now)
        audit.lane_resumed(lane_id, step_id, acting_user_id, captured_keys)

        # Advance lane.
        self._advance_lane(lane_id, step_id, acting_user_id)

        step.status = "DONE"
        step.completed_at = now
        return step

    def invoke_lane_action(
        self,
        lane_id: str,
        action_id: str,
        inputs: dict[str, str],
        reason: str,
        acting_user_id: str,
    ) -> LaneActionResult:
        if not reason or not reason.strip():
            raise ValueError("Lane action requires a non-empty reason (attributability mandate)")

        actions = self._config.get_lane_actions()
        if action_id not in actions:
            raise ValueError(f"Unknown lane action: '{action_id}'")

        action_def = actions[action_id]
        lane = self._ctx.lanes.get_lane(lane_id)
        if not lane:
            raise ValueError(f"Lane '{lane_id}' not found")

        audit = AuditWriter(self._ctx.audit)
        audit.lane_action_invoked(lane_id, action_id, acting_user_id, reason.strip())

        # Fire the trigger if it's not `none`.
        trigger_cfg = action_def.get("trigger", {"type": "none"})
        trigger_type = trigger_cfg.get("type", "none")

        if trigger_type != "none":
            attrs = self._ctx.lanes.get_lane_attributes(lane_id)
            bag = self._ctx.bag.get_bag(lane_id)
            binding = self._config.get_market_binding(attrs.get("market", ""))
            tools_cfg = self._config.get_tools()
            template_ctx = self._template_resolver.build_context(attrs, bag, binding, tools_cfg)
            # Merge inputs into context for {new_name} etc.
            template_ctx.update(inputs)

            resolved_url = self._template_resolver.resolve_partial(
                trigger_cfg.get("url_template", ""), template_ctx
            )

            cred: dict | None = None
            auth_type = "token"
            tool_name = action_def.get("tool", "jenkins")
            if self._credentials:
                cred = self._credentials.get_credential(acting_user_id, tool_name)
                auth_type = tools_cfg.get(tool_name, {}).get("auth", "token")

            exec_context: dict[str, Any] = {
                **template_ctx,
                "_resolved_url": resolved_url,
                "_resolved_body": None,
                "_auth_type": auth_type,
                "_credential": cred,
            }
            executor = self._trigger_registry.get(trigger_type)
            try:
                result = executor.execute(trigger_cfg, exec_context)
            except Exception as exc:
                return LaneActionResult(
                    success=False,
                    message=f"Action trigger failed: {exc}",
                    updated_attributes={},
                )
            if result.status != "SUCCESS":
                return LaneActionResult(
                    success=False,
                    message=f"Action trigger returned {result.status}: {result.message}",
                    updated_attributes={},
                )

        # Apply on_success.update_lane attribute updates.
        on_success = action_def.get("on_success", {})
        update_attrs = on_success.get("update_lane", {})

        # Resolve simple {input_key} placeholders from inputs.
        resolved_attrs: dict[str, str] = {}
        for attr_key, attr_val in update_attrs.items():
            val = attr_val
            for input_key, input_val in inputs.items():
                val = val.replace(f"{{{input_key}}}", input_val)
            resolved_attrs[attr_key] = val

        # Enforce name-alignment for rename actions.
        if "arcad_package" in resolved_attrs or "branch_name" in resolved_attrs:
            pkg = resolved_attrs.get("arcad_package", "")
            branch = resolved_attrs.get("branch_name", pkg)
            if pkg != branch:
                return LaneActionResult(
                    success=False,
                    message=f"Name alignment violation: arcad_package '{pkg}' ≠ branch_name '{branch}'",
                    updated_attributes={},
                )
            # Atomic update — both fields together.
            changes: dict[str, tuple[str, str]] = {}
            if "arcad_package" in resolved_attrs:
                changes["arcad_package"] = (lane.arcad_package, resolved_attrs["arcad_package"])
            if "branch_name" in resolved_attrs:
                changes["branch_name"] = (lane.branch_name, resolved_attrs["branch_name"])

            self._ctx.lanes.update_lane_package(
                lane_id,
                resolved_attrs.get("arcad_package", lane.arcad_package),
                resolved_attrs.get("branch_name", lane.branch_name),
            )
            self._ctx.lanes.set_lane_attributes(lane_id, resolved_attrs)
            audit.attribute_changed(lane_id, acting_user_id, changes)
        else:
            self._ctx.lanes.set_lane_attributes(lane_id, resolved_attrs)
            changes = {k: ("", v) for k, v in resolved_attrs.items()}
            if changes:
                audit.attribute_changed(lane_id, acting_user_id, changes)

        return LaneActionResult(
            success=True,
            message=f"Action '{action_id}' applied successfully",
            updated_attributes=resolved_attrs,
        )

    def fire_step(
        self,
        lane_id: str,
        step_id: str,
        acting_user_id: str,
    ) -> StepInstance:
        """
        Fire a step's trigger (http / http_flow / webhook / none).

        - Idempotency: if this step was already fired IN_FLIGHT or COMPLETED,
          returns the current step without re-firing.
        - Resolves credentials for the step's tool from the CredentialStore.
        - Resolves {placeholder} URLs/bodies from lane attributes + bag + config.
        - Records a trigger_attempt BEFORE calling the executor (crash-safe).
        - On SUCCESS: writes produced values to bag, marks step DONE, advances lane.
        - On FAILED: marks step BLOCKED, surfaces error.
        - On WAITING (webhook): marks step IN_PROGRESS and parks lane.
        """
        step = self._ctx.steps.get_step_instance(lane_id, step_id)
        if not step:
            raise ValueError(f"Step '{step_id}' not found in lane '{lane_id}'")
        # Already completed or skipped — return silently (idempotent).
        if step.status in ("DONE", "SKIPPED"):
            return step

        # Idempotency guard — already fired and in-flight or completed.
        if self._ctx.trigger_attempts.already_fired(lane_id, step_id):
            return step

        bag = self._ctx.bag.get_bag(lane_id)
        attrs = self._ctx.lanes.get_lane_attributes(lane_id)

        missing = self._bag_validator.validate_consumes(step, bag, attrs)
        if missing:
            raise ValueError(
                f"Step '{step_id}' cannot fire: missing required value(s): "
                + ", ".join(f"'{k}'" for k in missing)
            )

        trigger_cfg = step.trigger_ref
        trigger_type = trigger_cfg.get("type", "none")
        audit = AuditWriter(self._ctx.audit)
        now = _now()

        # Resolve credential for the step's tool.
        cred: dict | None = None
        auth_type = "token"
        tool_name = ""
        # step definition has a 'tool' field stored in view_config or we check config
        step_def = self._config.get_step_definition(step.definition_ref)
        tool_name = step_def.get("tool", "")
        if tool_name and self._credentials:
            cred = self._credentials.get_credential(acting_user_id, tool_name)
            tools = self._config.get_tools()
            auth_type = tools.get(tool_name, {}).get("auth", "token")

        # Build template context.
        binding = self._config.get_market_binding(attrs.get("market", ""))
        tools_cfg = self._config.get_tools()
        template_ctx = self._template_resolver.build_context(attrs, bag, binding, tools_cfg)

        # Resolve URL and body templates.
        resolved_url = ""
        if "url_template" in trigger_cfg:
            resolved_url = self._template_resolver.resolve_partial(
                trigger_cfg["url_template"], template_ctx
            )
        resolved_body: str | None = None
        if "body_template" in trigger_cfg:
            resolved_body = self._template_resolver.resolve_partial(
                trigger_cfg["body_template"], template_ctx
            )

        # Apply per-market param_map for Jenkins jobs.
        param_map = binding.get("override", {}).get(step_id, {}).get("param_map", {})

        # Build executor context.
        exec_context: dict[str, Any] = {
            **template_ctx,
            "_resolved_url": resolved_url,
            "_resolved_body": resolved_body,
            "_auth_type": auth_type,
            "_credential": cred,
            "_param_map": param_map,
        }

        # Record attempt BEFORE firing (crash-safe idempotency).
        attempt_num = 1
        prev = self._ctx.trigger_attempts.get_latest_attempt(lane_id, step_id)
        if prev:
            attempt_num = prev["attempt"] + 1
        attempt_id = self._ctx.trigger_attempts.record_attempt(
            lane_id, step_id, attempt_num
        )

        # Mark step IN_PROGRESS.
        self._ctx.steps.update_step_status(lane_id, step_id, "IN_PROGRESS", "UNKNOWN", acting_user_id)
        self._ctx.steps.update_step_times(lane_id, step_id, entered_at=now, completed_at=None)
        audit.step_triggered(lane_id, step_id, acting_user_id)

        # Execute the trigger.
        executor = self._trigger_registry.get(trigger_type)
        try:
            result = executor.execute(trigger_cfg, exec_context)
        except Exception as exc:
            self._ctx.trigger_attempts.update_status(attempt_id, "FAILED")
            self._ctx.steps.update_step_status(lane_id, step_id, "BLOCKED", "FAILED", acting_user_id)
            audit.step_result(lane_id, step_id, acting_user_id, "BLOCKED", {"error": str(exc)})
            self._ctx.lanes.update_lane_status(lane_id, "BLOCKED", step_id)
            step.status = "BLOCKED"
            step.auto_result = "FAILED"
            return step

        if result.status == "SUCCESS":
            self._ctx.trigger_attempts.update_status(attempt_id, "COMPLETED")
            # Write produced values to bag.
            for key, val in result.produced.items():
                self._ctx.bag.upsert_value(lane_id, key, val, step_id, "api")
                audit.value_recorded(lane_id, step_id, acting_user_id, key, "api")
            # Write any links.
            for link_data in result.links:
                link = RecordedLink(
                    id=_new_id(), step_instance_id=step_id, lane_id=lane_id,
                    label=link_data.get("label", ""), url=link_data.get("url", ""),
                    recorded_by_user_id=acting_user_id, recorded_at=now,
                )
                self._ctx.links.insert_link(link)
                audit.link_recorded(lane_id, step_id, acting_user_id, link.label)
            # Mark DONE and advance.
            self._ctx.steps.update_step_status(lane_id, step_id, "DONE", "SUCCESS", acting_user_id)
            self._ctx.steps.update_step_times(lane_id, step_id, entered_at=now, completed_at=_now())
            audit.step_result(lane_id, step_id, acting_user_id, "DONE", {"produced": list(result.produced)})
            self._advance_lane(lane_id, step_id, acting_user_id)
            step.status = "DONE"
            step.auto_result = "SUCCESS"
            # Fire post-actions (side-effects on completion).
            self._fire_post_actions(step, "DONE", exec_context, acting_user_id, audit)

        elif result.status in ("WAITING", "MANUAL"):
            # Webhook or none-trigger step — stays IN_PROGRESS; user or poller will advance.
            self._ctx.trigger_attempts.update_status(attempt_id, "IN_FLIGHT")
            lane_status = "WAITING" if result.status == "WAITING" else "ACTIVE"
            self._ctx.lanes.update_lane_status(lane_id, lane_status, step_id)
            step.status = "IN_PROGRESS"

        else:  # FAILED
            self._ctx.trigger_attempts.update_status(attempt_id, "FAILED")
            self._ctx.steps.update_step_status(lane_id, step_id, "BLOCKED", "FAILED", acting_user_id)
            audit.step_result(lane_id, step_id, acting_user_id, "BLOCKED", {"message": result.message})
            self._ctx.lanes.update_lane_status(lane_id, "BLOCKED", step_id)
            step.status = "BLOCKED"
            step.auto_result = "FAILED"

        return step

    def refresh_lane_status(
        self, lane_id: str, acting_user_id: str
    ) -> StepInstance | None:
        """
        Live re-check for lanes with IN_PROGRESS steps.
        Called by the poller and by the UI's Refresh button.
        Returns the updated step if state changed, else None.
        """
        lane = self._ctx.lanes.get_lane(lane_id)
        if not lane or lane.status not in ("ACTIVE", "WAITING", "BLOCKED"):
            return None

        steps = self._ctx.steps.list_step_instances(lane_id)
        in_progress = [s for s in steps if s.status == "IN_PROGRESS"]
        if not in_progress:
            return None

        step = in_progress[0]
        trigger_type = step.trigger_ref.get("type", "none")

        # Only poll http_flow and webhook steps — they have external state.
        if trigger_type not in ("http_flow", "http", "webhook"):
            return None

        bag = self._ctx.bag.get_bag(lane_id)
        attrs = self._ctx.lanes.get_lane_attributes(lane_id)
        binding = self._config.get_market_binding(attrs.get("market", ""))
        tools_cfg = self._config.get_tools()
        template_ctx = self._template_resolver.build_context(attrs, bag, binding, tools_cfg)

        cred: dict | None = None
        auth_type = "token"
        step_def = self._config.get_step_definition(step.definition_ref)
        tool_name = step_def.get("tool", "")
        if tool_name and self._credentials:
            cred = self._credentials.get_credential(acting_user_id, tool_name)
            auth_type = tools_cfg.get(tool_name, {}).get("auth", "token")

        # For webhook / http steps with a poll URL, check live status.
        poll_url_key = f"{step.id}_poll_url"
        poll_url = bag.get(poll_url_key, "")
        if not poll_url and "url_template" in step.trigger_ref:
            poll_url = self._template_resolver.resolve_partial(
                step.trigger_ref["url_template"], template_ctx
            )

        if not poll_url:
            return None

        from core.triggers.http_executor import _do_request, _build_headers, _jsonpath_extract
        headers = _build_headers(auth_type, cred)
        try:
            status_code, response = _do_request("GET", poll_url, headers, None, timeout=10)
        except Exception:
            return None

        if status_code >= 400:
            return None

        # Check if result field indicates completion.
        result_val = _jsonpath_extract(response, "$.result")
        if result_val is None:
            return None  # Still running

        audit = AuditWriter(self._ctx.audit)
        now = _now()
        success = str(result_val).upper() in ("SUCCESS", "STABLE")
        new_auto = "SUCCESS" if success else "FAILED"
        new_status = "DONE" if success else "BLOCKED"

        # Capture any bag values from the response.
        for bag_key, json_path in step.trigger_ref.get("capture", {}).items():
            val = _jsonpath_extract(response, json_path)
            if val is not None:
                self._ctx.bag.upsert_value(lane_id, bag_key, str(val), step.id, "api")
                audit.value_recorded(lane_id, step.id, "SYSTEM", bag_key, "api")

        # Use None for the FK (last_acted_by_user_id); "SYSTEM" is an audit-only label.
        self._ctx.steps.update_step_status(lane_id, step.id, new_status, new_auto, None)
        self._ctx.steps.update_step_times(lane_id, step.id, entered_at=step.entered_at, completed_at=now)
        audit.step_result(lane_id, step.id, "SYSTEM", new_status, {"auto_result": new_auto})

        if success:
            self._advance_lane(lane_id, step.id, "SYSTEM")

        attempt = self._ctx.trigger_attempts.get_latest_attempt(lane_id, step.id)
        if attempt:
            self._ctx.trigger_attempts.update_status(
                attempt["id"], "COMPLETED" if success else "FAILED"
            )

        step.status = new_status
        step.auto_result = new_auto
        return step

    def _fire_post_actions(
        self,
        step: StepInstance,
        when_status: str,
        context: dict[str, Any],
        acting_user_id: str,
        audit: "AuditWriter",
    ) -> None:
        """
        Fire any post_actions declared on the step that match `when_status`.
        Uses the same trigger types and templating as regular steps.
        A post-action failure is surfaced in the audit but does NOT block lane advancement.
        """
        for pa in step.post_actions:
            if pa.get("when", "DONE").upper() != when_status.upper():
                continue
            do = pa.get("do", {})
            trigger_type = do.get("type", "none")
            if trigger_type == "none":
                continue

            # Resolve URL / body
            resolved_url = self._template_resolver.resolve_partial(
                do.get("url_template", ""), context
            )
            resolved_body: str | None = None
            if "body_template" in do:
                resolved_body = self._template_resolver.resolve_partial(
                    do["body_template"], context
                )

            exec_ctx = {
                **context,
                "_resolved_url": resolved_url,
                "_resolved_body": resolved_body,
                "_auth_type": "token",
                "_credential": None,
            }

            executor = self._trigger_registry.get(trigger_type)
            try:
                result = executor.execute(do, exec_ctx)
                audit._write(
                    step.lane_id, "POST_ACTION_FIRED", acting_user_id,
                    {"trigger_type": trigger_type, "status": result.status,
                     "message": result.message},
                    step.id,
                )
            except Exception as exc:
                audit._write(
                    step.lane_id, "POST_ACTION_FIRED", acting_user_id,
                    {"trigger_type": trigger_type, "status": "FAILED", "error": str(exc)},
                    step.id,
                )

    # ── Private helpers ──────────────────────────────────────────────────────

    def _advance_lane(self, lane_id: str, completed_step_id: str, actor: str) -> None:
        """After a step completes, determine the next step and update lane state."""
        steps = self._ctx.steps.list_step_instances(lane_id)
        overrides = self._ctx.overrides.get_overrides_for_lane(lane_id)
        for s in steps:
            s.override = overrides.get(s.id)

        next_step = self._advancer.next_eligible_step(steps, completed_step_id)
        new_status = self._advancer.compute_lane_status(steps, next_step)
        new_current = next_step.id if next_step else None

        self._ctx.lanes.update_lane_status(lane_id, new_status, new_current)

        if next_step and next_step.kind == "external_hold":
            # None is safe for last_acted_by_user_id when actor is "SYSTEM" (not a real user FK).
            dal_actor = None if actor == "SYSTEM" else actor
            self._ctx.steps.update_step_status(
                lane_id, next_step.id, "SUSPENDED", "UNKNOWN", dal_actor
            )
            AuditWriter(self._ctx.audit).lane_suspended(lane_id, next_step.id, actor)
