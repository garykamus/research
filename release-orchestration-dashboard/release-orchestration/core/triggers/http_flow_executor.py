from __future__ import annotations

import time
import re
from typing import Any

from .base import TriggerExecutor, TriggerResult
from .http_executor import _build_headers, _do_request, _jsonpath_extract, _resolve_path


def _parse_duration(s: str) -> int:
    """Parse '30s', '20m', '2h' → seconds."""
    m = re.match(r"^(\d+)(s|m|h)$", s.strip())
    if not m:
        raise ValueError(f"Invalid duration: {s!r}")
    n, unit = int(m.group(1)), m.group(2)
    return n * {"s": 1, "m": 60, "h": 3600}[unit]


class HttpFlowExecutor(TriggerExecutor):
    """
    Sequence of steps: call → poll(until condition, timeout) → capture.

    Config shape:
      trigger:
        type: http_flow
        steps:
          - call:  "POST {url}"
          - poll:  "GET {url}/lastBuild/api/json"
            until: "$.result != null"
            timeout: 30m
            interval: 30s
          - capture:
              build_url: "$.url"
              build_result: "$.result"
    """

    trigger_type = "http_flow"

    def execute(self, trigger_config: dict[str, Any], context: dict[str, Any]) -> TriggerResult:
        auth_type = context.get("_auth_type", "token")
        cred = context.get("_credential")
        headers = _build_headers(auth_type, cred)
        steps = trigger_config.get("steps", [])

        last_response: Any = None
        produced: dict[str, str] = {}

        for step in steps:
            if "call" in step:
                method, url = self._parse_method_url(step["call"], context)
                body = context.get("_resolved_body")
                try:
                    status_code, last_response = _do_request(method, url, headers, body)
                except TimeoutError as exc:
                    return TriggerResult(status="FAILED", message=str(exc))
                if status_code >= 400:
                    return TriggerResult(
                        status="FAILED",
                        message=f"Call failed HTTP {status_code}: {str(last_response)[:300]}",
                    )

            elif "poll" in step:
                method, url = self._parse_method_url(step["poll"], context)
                until_expr = step.get("until", "$.result != null")
                timeout_s = _parse_duration(step.get("timeout", "30m"))
                interval_s = _parse_duration(step.get("interval", "30s"))
                deadline = time.monotonic() + timeout_s
                success = False
                while time.monotonic() < deadline:
                    try:
                        status_code, last_response = _do_request(method, url, headers, None, timeout=15)
                    except TimeoutError:
                        time.sleep(interval_s)
                        continue
                    if status_code < 400 and _jsonpath_extract(last_response, until_expr):
                        success = True
                        break
                    time.sleep(interval_s)
                if not success:
                    return TriggerResult(
                        status="FAILED",
                        message=f"Poll timed out after {step.get('timeout','30m')}: condition '{until_expr}' never met",
                    )

            elif "capture" in step:
                for bag_key, json_path in step["capture"].items():
                    val = _resolve_path(last_response, json_path)
                    if val is not None:
                        produced[bag_key] = str(val)

        links: list[dict[str, str]] = []
        for key in ("build_url", "url", "html_url"):
            if key in produced:
                links.append({"label": key.replace("_", " ").title(), "url": produced[key]})
                break

        return TriggerResult(status="SUCCESS", produced=produced, links=links)

    @staticmethod
    def _parse_method_url(expr: str, context: dict[str, Any]) -> tuple[str, str]:
        """Parse 'POST https://...' or 'GET https://...' with context substitution."""
        parts = expr.strip().split(None, 1)
        method = parts[0].upper() if len(parts) > 1 else "GET"
        url = parts[1] if len(parts) > 1 else parts[0]
        # Resolve {placeholders} in URL
        for k, v in context.items():
            if not k.startswith("_"):
                url = url.replace(f"{{{k}}}", str(v))
        return method, url
