from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class User:
    id: str
    username: str
    display_name: str
    created_at: str


@dataclass
class Lane:
    id: str
    market: str
    arcad_package: str
    branch_name: str
    owner_user_id: str
    created_by_user_id: str
    created_at: str
    workflow_template_id: str
    status: str
    current_step_id: str | None


@dataclass
class Override:
    step_instance_id: str
    lane_id: str
    value: str
    reason: str
    who_user_id: str
    applied_at: str


@dataclass
class StepInstance:
    id: str
    lane_id: str
    seq_order: int
    definition_ref: str
    label: str
    kind: str
    mode: str
    view: str
    status: str
    auto_result: str
    produces: list[str]
    consumes: list[str]
    trigger_ref: dict[str, Any]
    post_actions: list[dict[str, Any]]
    view_config: dict[str, Any]
    entered_at: str | None
    completed_at: str | None
    last_acted_by_user_id: str | None
    override: Override | None = None

    def compute_effective_status(self) -> str:
        """override.value takes precedence over auto_result."""
        if self.override:
            return self.override.value
        if self.auto_result != "UNKNOWN":
            return self.auto_result
        return self.status


@dataclass
class ValueBagEntry:
    lane_id: str
    key: str
    value: str
    produced_by_step_id: str
    source: str
    recorded_at: str


@dataclass
class RecordedLink:
    id: str
    step_instance_id: str
    lane_id: str
    label: str
    url: str
    recorded_by_user_id: str
    recorded_at: str


@dataclass
class RecordedValue:
    id: str
    step_instance_id: str
    lane_id: str
    field_key: str
    value: str
    recorded_by_user_id: str
    recorded_at: str


@dataclass
class AuditEntry:
    id: str
    lane_id: str
    step_instance_id: str | None
    event_type: str
    actor_user_id: str
    at: str
    detail: dict[str, Any]


@dataclass
class LaneDetail:
    lane: Lane
    attributes: dict[str, str]
    steps: list[StepInstance]
    bag: dict[str, str]
    links: list[RecordedLink]


@dataclass
class LaneActionResult:
    success: bool
    message: str
    updated_attributes: dict[str, str]


@dataclass
class ConfigSummary:
    markets: list[str]
    templates: list[str]
    lane_actions: list[str]
