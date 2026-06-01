from __future__ import annotations

from typing import Any

from .base import TriggerExecutor, TriggerResult


class WebhookExecutor(TriggerExecutor):
    """
    Webhook trigger — no outbound call. The lane parks in WAITING and advances
    when the webhook receiver delivers the matching event (see core/webhook/).

    execute() is a no-op that signals the engine to transition the step to
    IN_PROGRESS/WAITING so the poller and webhook receiver can advance it.
    """

    trigger_type = "webhook"

    def execute(self, trigger_config: dict[str, Any], context: dict[str, Any]) -> TriggerResult:
        # No outbound action. Return WAITING so the engine parks the step.
        return TriggerResult(
            status="WAITING",
            message="Waiting for inbound webhook event",
        )
