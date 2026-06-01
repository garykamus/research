from __future__ import annotations

import copy
from typing import Any

from .loader import ConfigStore

# Lane attributes always available as consume sources (no producer needed).
_LANE_ATTRIBUTE_KEYS = {
    "market", "arcad_package", "branch_name", "owner",
    "jira_id", "confluence_page", "package_version",
}


class ResolutionError(Exception):
    def __init__(self, message: str, step_id: str | None = None) -> None:
        super().__init__(message)
        self.step_id = step_id


class LaneResolver:
    def __init__(self, config: ConfigStore) -> None:
        self._config = config

    def resolve(self, market: str, seeded_attributes: dict[str, str]) -> list[dict[str, Any]]:
        """
        Returns ordered list of merged step dicts for the given market.
        Raises ResolutionError on any validation failure.
        """
        binding = self._config.get_market_binding(market)
        template_id = binding.get("use")
        if not template_id:
            raise ResolutionError(f"Market '{market}' has no 'use' template")

        step_ids = self._expand_template(template_id)

        # Apply market composition ops.
        market_add = binding.get("add", [])
        market_skip = binding.get("skip", [])
        market_remove = binding.get("remove", [])
        market_reorder = binding.get("reorder", [])
        market_override = binding.get("override", {})

        step_ids = self._apply_add(step_ids, market_add)
        step_ids = self._apply_skip(step_ids, list(market_skip) + list(market_remove))
        step_ids = self._apply_reorder(step_ids, market_reorder)

        # Validate all step IDs exist.
        for sid in step_ids:
            try:
                self._config.get_step_definition(sid)
            except KeyError:
                raise ResolutionError(
                    f"Market '{market}': step '{sid}' not found in step library", sid
                )

        # Check for duplicate step IDs.
        seen: set[str] = set()
        for sid in step_ids:
            if sid in seen:
                raise ResolutionError(
                    f"Market '{market}': duplicate step id '{sid}' in resolved flow", sid
                )
            seen.add(sid)

        # Build merged step dicts (library def + market override).
        resolved: list[dict[str, Any]] = []
        for order, sid in enumerate(step_ids):
            step_def = copy.deepcopy(self._config.get_step_definition(sid))
            step_def["_step_id"] = sid
            step_def["_order"] = order

            if sid in market_override:
                step_def = self._merge_override(step_def, market_override[sid])

            resolved.append(step_def)

        # Validate value-bag coherence.
        available_keys = set(_LANE_ATTRIBUTE_KEYS) | set(seeded_attributes.keys())
        for step in resolved:
            if step.get("kind") == "external_hold":
                # external_hold adds its capture_fields to the bag on resume.
                for cf in step.get("resume", {}).get("capture_fields", []):
                    available_keys.add(cf["key"])
                continue
            for key in step.get("consumes", []):
                if key not in available_keys:
                    raise ResolutionError(
                        f"Market '{market}': step '{step['_step_id']}' consumes '{key}' "
                        f"but no earlier step produces it and it is not a lane attribute",
                        step["_step_id"],
                    )
            for key in step.get("produces", []):
                available_keys.add(key)

        # Validate external_hold sanity.
        for i, step in enumerate(resolved):
            if step.get("kind") == "external_hold":
                resume = step.get("resume")
                if not resume:
                    raise ResolutionError(
                        f"Market '{market}': external_hold step '{step['_step_id']}' "
                        f"has no 'resume' defined",
                        step["_step_id"],
                    )
                if i == len(resolved) - 1:
                    raise ResolutionError(
                        f"Market '{market}': flow ends on unresolved external_hold "
                        f"step '{step['_step_id']}'",
                        step["_step_id"],
                    )

        # Validate name-alignment: any step producing arcad_package must produce branch_name.
        for step in resolved:
            produces = set(step.get("produces", []))
            if "arcad_package" in produces and "branch_name" not in produces:
                raise ResolutionError(
                    f"Market '{market}': step '{step['_step_id']}' produces 'arcad_package' "
                    f"but not 'branch_name' — both must be produced together",
                    step["_step_id"],
                )
            if "branch_name" in produces and "arcad_package" not in produces:
                raise ResolutionError(
                    f"Market '{market}': step '{step['_step_id']}' produces 'branch_name' "
                    f"but not 'arcad_package' — both must be produced together",
                    step["_step_id"],
                )

        return resolved

    def validate_all_markets(self) -> dict[str, list[str]]:
        """Startup check — validate every market binding. Returns {market: [errors]}."""
        results: dict[str, list[str]] = {}
        for market in self._config.list_markets():
            errors: list[str] = []
            try:
                self.resolve(market, {})
            except ResolutionError as e:
                errors.append(str(e))
            except Exception as e:
                errors.append(f"Unexpected error: {e}")
            results[market] = errors
        return results

    # ── Private helpers ──────────────────────────────────────────────────────

    def _expand_template(self, template_id: str) -> list[str]:
        """Expand template (following extends chain) to an ordered list of step IDs."""
        template = self._config.get_template(template_id)
        if "steps" in template:
            base = list(template["steps"])
        elif "extends" in template:
            base = self._expand_template(template["extends"])
        else:
            raise ResolutionError(
                f"Template '{template_id}' has neither 'steps' nor 'extends'"
            )

        # Apply template-level add operations (extends-based variants).
        for add_op in template.get("add", []):
            base = self._apply_add(base, [add_op])
        for skip_id in template.get("skip", []):
            base = self._apply_skip(base, [skip_id])

        return base

    @staticmethod
    def _apply_add(step_ids: list[str], add_ops: list[dict]) -> list[str]:
        result = list(step_ids)
        for op in add_ops:
            new_step = op["step"]
            if "before" in op:
                anchor = op["before"]
                if anchor not in result:
                    raise ResolutionError(
                        f"Add anchor 'before: {anchor}' not found in flow"
                    )
                idx = result.index(anchor)
                result.insert(idx, new_step)
            elif "after" in op:
                anchor = op["after"]
                if anchor not in result:
                    raise ResolutionError(
                        f"Add anchor 'after: {anchor}' not found in flow"
                    )
                idx = result.index(anchor) + 1
                result.insert(idx, new_step)
            else:
                result.append(new_step)
        return result

    @staticmethod
    def _apply_skip(step_ids: list[str], skip_ids: list[str]) -> list[str]:
        skip_set = set(skip_ids)
        return [s for s in step_ids if s not in skip_set]

    @staticmethod
    def _apply_reorder(step_ids: list[str], reorder_ops: list[dict]) -> list[str]:
        result = list(step_ids)
        for op in reorder_ops:
            step = op["step"]
            if step not in result:
                continue
            result.remove(step)
            if "after" in op:
                anchor = op["after"]
                idx = result.index(anchor) + 1
                result.insert(idx, step)
            elif "before" in op:
                anchor = op["before"]
                idx = result.index(anchor)
                result.insert(idx, step)
        return result

    @staticmethod
    def _merge_override(step_def: dict, override: dict) -> dict:
        """Merge market override into step definition. extra_fields are appended."""
        result = copy.deepcopy(step_def)
        extra_fields = override.pop("extra_fields", [])
        if extra_fields:
            view_config = result.setdefault("view_config", {})
            fields = view_config.setdefault("fields", [])
            fields.extend(extra_fields)
        result.update(override)
        return result
