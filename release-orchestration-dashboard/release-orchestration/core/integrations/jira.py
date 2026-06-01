from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from typing import Any

from .base import IntegrationClient


class JiraClient(IntegrationClient):
    """
    Jira REST API v2 client (Cloud + Data Center).
    Auth: token → bearer (Cloud) or basic user:token (Data Center).
    """

    tool_name = "jira"

    def __init__(self, api_base: str, token: str | None = None, username: str | None = None) -> None:
        self._api = api_base.rstrip("/")
        self._token = token
        self._username = username

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json", "Accept": "application/json"}
        if self._username and self._token:
            creds = base64.b64encode(f"{self._username}:{self._token}".encode()).decode()
            h["Authorization"] = f"Basic {creds}"
        elif self._token:
            h["Authorization"] = f"Bearer {self._token}"
        return h

    def _request(self, method: str, path: str, body: dict | None = None) -> Any:
        url = f"{self._api}{path}"
        data = json.dumps(body).encode() if body else None
        req = urllib.request.Request(url, data=data, headers=self._headers(), method=method)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Jira {method} {path} → HTTP {e.code}: {raw[:300]}")

    # ── Issue operations ──────────────────────────────────────────────────

    def get_issue(self, issue_key: str) -> dict:
        return self._request("GET", f"/issue/{issue_key}")

    def get_transitions(self, issue_key: str) -> list[dict]:
        """Returns list of available transitions for the issue."""
        resp = self._request("GET", f"/issue/{issue_key}/transitions")
        return resp.get("transitions", [])

    def transition_issue(self, issue_key: str, transition_id: str) -> None:
        """POST /issue/{key}/transitions — move the issue to a new status."""
        self._request("POST", f"/issue/{issue_key}/transitions", {
            "transition": {"id": transition_id}
        })

    def transition_by_name(self, issue_key: str, transition_name: str) -> bool:
        """
        Transition the issue to the named status (case-insensitive match).
        Returns True on success, False if transition not found.
        """
        transitions = self.get_transitions(issue_key)
        match = next(
            (t for t in transitions if t["name"].lower() == transition_name.lower()),
            None
        )
        if not match:
            return False
        self.transition_issue(issue_key, match["id"])
        return True

    def add_comment(self, issue_key: str, body: str) -> dict:
        """Add a comment to the issue."""
        return self._request("POST", f"/issue/{issue_key}/comment", {"body": body})

    def update_field(self, issue_key: str, fields: dict) -> None:
        """PUT /issue/{key} — update arbitrary fields."""
        self._request("PUT", f"/issue/{issue_key}", {"fields": fields})
