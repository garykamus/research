from __future__ import annotations

import json
import re
import socket
import urllib.error
import urllib.request
from typing import Any

from .base import TriggerExecutor, TriggerResult

# Hard ceiling on any single HTTP request. urllib's timeout only covers the
# socket-read phase; the DNS resolution phase is covered by the default set
# here so the engine can never hang indefinitely on a bad host.
_DEFAULT_REQUEST_TIMEOUT = 30
socket.setdefaulttimeout(60)


def _jsonpath_extract(data: Any, path: str) -> Any:
    """
    Minimal JSONPath evaluator supporting:
      $.key          — top-level key
      $.a.b.c        — nested dot access
      $.result != null  — not-null check (returns bool)
      $.result == 'SUCCESS' — equality check (returns bool)
    """
    # Comparison expressions
    m = re.match(r"^([\$\.\w]+)\s*(!=|==)\s*(.+)$", path.strip())
    if m:
        lhs_path, op, rhs_raw = m.group(1), m.group(2), m.group(3).strip()
        rhs = None if rhs_raw == "null" else rhs_raw.strip("'\"")
        val = _resolve_path(data, lhs_path)
        if op == "!=":
            return val != rhs
        elif op == "==":
            return str(val) == str(rhs)
    return _resolve_path(data, path)


def _resolve_path(data: Any, path: str) -> Any:
    """Walk dot-notation path like $.result.url"""
    parts = path.lstrip("$.").split(".")
    cur = data
    for p in parts:
        if not p:
            continue
        if isinstance(cur, dict):
            cur = cur.get(p)
        else:
            return None
    return cur


def _build_headers(auth_type: str, cred: dict | None) -> dict[str, str]:
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if not cred:
        return headers
    if auth_type == "token":
        token = cred.get("token", "")
        headers["Authorization"] = f"Bearer {token}"
    elif auth_type == "basic":
        import base64
        pair = f"{cred.get('username','')}:{cred.get('password','')}".encode()
        headers["Authorization"] = "Basic " + base64.b64encode(pair).decode()
    return headers


def _do_request(
    method: str,
    url: str,
    headers: dict[str, str],
    body: str | None,
    timeout: int = _DEFAULT_REQUEST_TIMEOUT,
) -> tuple[int, Any]:
    """
    Perform one HTTP request. Returns (status_code, parsed_json_or_text).
    Raises TimeoutError if the socket-level timeout expires.
    """
    data = body.encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, raw.decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, raw.decode("utf-8", errors="replace")
    except TimeoutError as e:
        raise TimeoutError(f"Request timed out after {timeout}s: {url}") from e
    except OSError as e:
        # socket.timeout is a subclass of OSError on Python 3.3+
        if "timed out" in str(e).lower():
            raise TimeoutError(f"Request timed out after {timeout}s: {url}") from e
        raise


class HttpExecutor(TriggerExecutor):
    """
    Single REST/HTTP call with optional JSONPath capture into the value bag.

    Config shape:
      trigger:
        type: http
        method: POST
        url_template: "..."
        body_template: '{"key":"val"}'   # optional
        capture:                          # optional
          pr_url: "$.html_url"
        param_map: {}                     # optional per-market param remapping
    """

    trigger_type = "http"

    def execute(self, trigger_config: dict[str, Any], context: dict[str, Any]) -> TriggerResult:
        method = trigger_config.get("method", "POST").upper()
        url = context["_resolved_url"]
        body = context.get("_resolved_body")
        auth_type = context.get("_auth_type", "token")
        cred = context.get("_credential")
        timeout = int(trigger_config.get("timeout_seconds", _DEFAULT_REQUEST_TIMEOUT))

        headers = _build_headers(auth_type, cred)
        try:
            status_code, response = _do_request(method, url, headers, body, timeout=timeout)
        except TimeoutError as exc:
            return TriggerResult(status="FAILED", message=str(exc))

        if status_code >= 400:
            return TriggerResult(
                status="FAILED",
                message=f"HTTP {status_code}: {str(response)[:300]}",
            )

        produced: dict[str, str] = {}
        for bag_key, json_path in trigger_config.get("capture", {}).items():
            val = _jsonpath_extract(response, json_path)
            if val is not None:
                produced[bag_key] = str(val)

        links: list[dict[str, str]] = []
        if "url" in produced:
            links.append({"label": "Result", "url": produced["url"]})

        return TriggerResult(status="SUCCESS", produced=produced, links=links)
