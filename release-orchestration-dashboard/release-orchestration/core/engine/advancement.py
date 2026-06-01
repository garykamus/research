from __future__ import annotations

from core.models import StepInstance


class AdvancementEngine:
    """Pure logic — determines the next eligible step and resulting lane status."""

    def next_eligible_step(
        self, steps: list[StepInstance], current_step_id: str
    ) -> StepInstance | None:
        """
        Returns the next step after current_step_id that is not DONE or SKIPPED.
        Returns None if all remaining steps are DONE/SKIPPED (lane is finished).
        """
        found_current = False
        for step in steps:
            if step.id == current_step_id:
                found_current = True
                continue
            if found_current and step.status not in ("DONE", "SKIPPED"):
                return step
        return None

    def first_eligible_step(self, steps: list[StepInstance]) -> StepInstance | None:
        """Returns the first step not yet DONE or SKIPPED. Used at lane creation."""
        for step in steps:
            if step.status not in ("DONE", "SKIPPED"):
                return step
        return None

    def compute_lane_status(
        self, steps: list[StepInstance], next_step: StepInstance | None
    ) -> str:
        if next_step is None:
            return "DONE"
        if next_step.kind == "external_hold":
            return "SUSPENDED"
        if any(s.status == "BLOCKED" for s in steps):
            return "BLOCKED"
        return "ACTIVE"
