from __future__ import annotations

from typing import Any

from .base import TriggerExecutor, TriggerResult


class BrowserExecutor(TriggerExecutor):
    """Phase 3 — Playwright browser automation. Excluded from Phase 1 packaging."""

    trigger_type = "browser"

    def execute(self, trigger_config: dict[str, Any], context: dict[str, Any]) -> TriggerResult:
        raise NotImplementedError(
            "browser trigger executor not implemented until Phase 3 "
            "(Playwright excluded from current build)"
        )
