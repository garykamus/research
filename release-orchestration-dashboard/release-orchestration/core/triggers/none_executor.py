from __future__ import annotations

from typing import Any

from .base import TriggerExecutor, TriggerResult


class NoneExecutor(TriggerExecutor):
    """
    Manual step — no automated trigger.
    The engine never calls execute() for none-type triggers directly;
    advancement happens via advance_step() with user-supplied values.
    This executor exists to complete the registry.
    """

    trigger_type = "none"

    def execute(self, trigger_config: dict[str, Any], context: dict[str, Any]) -> TriggerResult:
        return TriggerResult(status="MANUAL", message="Manual step — no automated trigger")
