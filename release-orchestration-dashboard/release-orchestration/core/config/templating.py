from __future__ import annotations

import re
from typing import Any


class TemplateResolutionError(Exception):
    def __init__(self, unresolved: list[str]) -> None:
        super().__init__(f"Unresolved placeholders: {unresolved}")
        self.unresolved = unresolved


class TemplateResolver:
    """
    Resolves {placeholder} strings from a combined namespace of:
    - lane attributes
    - value bag
    - market config (market.urls.build_url → {market.build_url}, etc.)
    - tool config  (tool.jenkins.base → {tool.jenkins.base})

    Used at step fire time (Phase 2+) and to render link_buttons in the UI.
    """

    _PLACEHOLDER_RE = re.compile(r"\{([^}]+)\}")

    def build_context(
        self,
        lane_attrs: dict[str, str],
        bag: dict[str, str],
        market_cfg: dict[str, Any],
        tools_cfg: dict[str, Any],
    ) -> dict[str, str]:
        ctx: dict[str, str] = {}
        ctx.update(lane_attrs)
        ctx.update(bag)

        # Flatten market config: market.urls.build_url → market.build_url
        for key, val in (market_cfg.get("urls") or {}).items():
            ctx[f"market.{key}"] = str(val)
        for key, val in (market_cfg.get("portal") or {}).items():
            if isinstance(val, dict):
                for sub_key, sub_val in val.items():
                    ctx[f"market.portal.{key}.{sub_key}"] = str(sub_val)
            else:
                ctx[f"market.portal.{key}"] = str(val)
        for key, val in market_cfg.items():
            if key not in ("urls", "portal", "override", "add", "skip", "reorder"):
                ctx[f"market.{key}"] = str(val)

        # Flatten tool config: tool.jenkins.base → tool.jenkins.base
        for tool_name, tool_def in tools_cfg.items():
            if isinstance(tool_def, dict):
                for attr, val in tool_def.items():
                    ctx[f"tool.{tool_name}.{attr}"] = str(val)

        return ctx

    def resolve(self, template: str, context: dict[str, str]) -> str:
        """
        Resolve all {key} placeholders. Raises TemplateResolutionError if any remain.
        """
        unresolved: list[str] = []

        def replacer(match: re.Match) -> str:
            key = match.group(1)
            if key in context:
                return context[key]
            unresolved.append(key)
            return match.group(0)

        result = self._PLACEHOLDER_RE.sub(replacer, template)
        if unresolved:
            raise TemplateResolutionError(unresolved)
        return result

    def resolve_partial(self, template: str, context: dict[str, str]) -> str:
        """
        Resolve what is available; leave unresolved placeholders in place.
        Used for rendering link_buttons where some values may not yet exist.
        """
        def replacer(match: re.Match) -> str:
            key = match.group(1)
            return context.get(key, match.group(0))

        return self._PLACEHOLDER_RE.sub(replacer, template)
