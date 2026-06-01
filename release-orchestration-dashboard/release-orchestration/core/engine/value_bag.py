from __future__ import annotations

from core.models import StepInstance
from core.persistence.context import PersistenceContext

_LANE_ATTRIBUTE_KEYS = {
    "market", "arcad_package", "branch_name", "owner",
    "jira_id", "confluence_page", "package_version",
}


class ValueBagValidator:
    """Validates step consumes before firing and promotes produced values into the bag."""

    def validate_consumes(
        self,
        step: StepInstance,
        bag: dict[str, str],
        lane_attributes: dict[str, str],
    ) -> list[str]:
        """Returns list of missing keys. Empty list means OK to proceed."""
        combined = set(_LANE_ATTRIBUTE_KEYS) | set(lane_attributes.keys()) | set(bag.keys())
        return [key for key in step.consumes if key not in combined]

    def promote_to_bag(
        self,
        step: StepInstance,
        recorded_values: dict[str, str],
        ctx: PersistenceContext,
        acting_user: str,
    ) -> list[str]:
        """
        For each key in step.produces that appears in recorded_values,
        write it into the value_bag with source=manual.
        Returns the list of keys actually promoted.
        """
        promoted: list[str] = []
        for key in step.produces:
            if key in recorded_values:
                ctx.bag.upsert_value(
                    step.lane_id, key, recorded_values[key],
                    step.id, "manual",
                )
                promoted.append(key)
        return promoted
