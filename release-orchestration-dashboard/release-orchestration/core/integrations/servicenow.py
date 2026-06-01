from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .base import IntegrationClient


class ServiceNowClient(IntegrationClient):
    """
    ServiceNow REST API client — Tier 1 (REST) or Tier 3 (deep-link).

    Tier is configured per-market via `servicenow_tier: rest | deep_link`
    in the market YAML (default: the fallback in tools.yaml).

    REST operations use the Table API (api/now/table/...).
    Auth: token → "Authorization: Bearer <token>" header.
    """

    tool_name = "servicenow"

    def __init__(self, api_base: str, token: str | None = None) -> None:
        self._api = api_base.rstrip("/")
        self._token = token

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json", "Accept": "application/json"}
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        return h

    def _request(self, method: str, path: str, body: dict | None = None) -> Any:
        url = f"{self._api}{path}"
        data = json.dumps(body).encode() if body else None
        req = urllib.request.Request(url, data=data, headers=self._headers(), method=method)
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"ServiceNow {method} {path} → HTTP {e.code}: {raw[:300]}")

    # ── Change Request (CRUD) ──────────────────────────────────────────────

    def create_change_request(self, payload: dict) -> dict:
        """
        POST /table/change_request
        Returns dict with at least: number (CR number), sys_id, sys_url (link).
        """
        resp = self._request("POST", "/table/change_request", payload)
        result = resp.get("result", {})
        return {
            "cr_no": result.get("number", ""),
            "sys_id": result.get("sys_id", ""),
            "cr_url": result.get("sys_url", result.get("link", "")),
        }

    def get_change_request(self, cr_no: str) -> dict:
        """GET /table/change_request?sysparm_query=number=<cr_no>"""
        path = f"/table/change_request?sysparm_query=number%3D{cr_no}&sysparm_limit=1"
        resp = self._request("GET", path)
        results = resp.get("result", [])
        return results[0] if results else {}

    def update_change_request(self, sys_id: str, payload: dict) -> dict:
        """PATCH /table/change_request/<sys_id>"""
        return self._request("PATCH", f"/table/change_request/{sys_id}", payload)

    def submit_change_request(self, sys_id: str) -> dict:
        """
        Transition CR to 'assess' / 'submitted' state.
        ServiceNow state values: -5=new, -4=assess, -3=authorize, ...
        """
        return self.update_change_request(sys_id, {"state": "-4"})

    def get_cr_approval_state(self, sys_id: str) -> str:
        """
        Returns the approval field value: requested | approved | rejected.
        Used by the poller to detect when a CR is approved.
        """
        resp = self._request(
            "GET",
            f"/table/change_request/{sys_id}?sysparm_fields=approval,state"
        )
        result = resp.get("result", {})
        return result.get("approval", "")

    # ── Evidence / work notes ─────────────────────────────────────────────

    def add_work_note(self, sys_id: str, note: str) -> dict:
        """Append a work note to the CR — used for evidence update."""
        return self.update_change_request(sys_id, {"work_notes": note})

    # ── Deep-link (Tier 3) ────────────────────────────────────────────────

    @staticmethod
    def build_deep_link(base_url: str, cr_fields: dict) -> str:
        """
        Build a pre-filled URL that opens ServiceNow's CR creation form
        in the user's own browser. No password stored or sent.

        e.g. https://snow.example.com/now/change/create?
               short_description=Release+pkg-001&assignment_group=...
        """
        params = {k: v for k, v in cr_fields.items() if v}
        query = urllib.parse.urlencode(params)
        return f"{base_url.rstrip('/')}/now/change/create?{query}"

    @staticmethod
    def build_cr_deep_link(base_url: str, cr_no: str) -> str:
        """Link directly to an existing CR by number."""
        return f"{base_url.rstrip('/')}/now/change/{cr_no}"
