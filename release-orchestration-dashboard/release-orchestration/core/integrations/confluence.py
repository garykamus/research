from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .base import IntegrationClient


class ConfluenceClient(IntegrationClient):
    """
    Confluence REST API client (Cloud + Data Center).
    Auth: token → "Authorization: Bearer <token>" (Cloud)
          or basic(user:token) for Data Center.
    """

    tool_name = "confluence"

    def __init__(self, api_base: str, token: str | None = None, username: str | None = None) -> None:
        self._api = api_base.rstrip("/")
        self._token = token
        self._username = username  # needed for Data Center basic auth

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json", "Accept": "application/json"}
        if self._username and self._token:
            # Data Center / Server: basic auth with user:token
            creds = base64.b64encode(f"{self._username}:{self._token}".encode()).decode()
            h["Authorization"] = f"Basic {creds}"
        elif self._token:
            # Cloud: bearer token
            h["Authorization"] = f"Bearer {self._token}"
        return h

    def _request(self, method: str, path: str, body: dict | None = None) -> Any:
        url = f"{self._api}{path}"
        data = json.dumps(body).encode() if body else None
        req = urllib.request.Request(url, data=data, headers=self._headers(), method=method)
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Confluence {method} {path} → HTTP {e.code}: {raw[:300]}")

    # ── Page operations ───────────────────────────────────────────────────

    def get_page(self, page_id: str) -> dict:
        """GET /content/<page_id>?expand=body.storage,version"""
        return self._request("GET", f"/content/{page_id}?expand=body.storage,version")

    def update_page(self, page_id: str, title: str, body_html: str, current_version: int) -> dict:
        """
        PUT /content/<page_id> — replaces the page body.
        Requires the current version number for optimistic locking.
        """
        return self._request("PUT", f"/content/{page_id}", {
            "version": {"number": current_version + 1},
            "title": title,
            "type": "page",
            "body": {"storage": {"value": body_html, "representation": "storage"}},
        })

    def append_to_page(self, page_id: str, new_content_html: str) -> dict:
        """
        Fetch the current page body and append new_content_html to it.
        Returns the updated page dict.
        """
        page = self.get_page(page_id)
        title = page.get("title", "Release page")
        version = page["version"]["number"]
        existing_body = page["body"]["storage"]["value"]
        updated_body = existing_body + "\n" + new_content_html
        return self.update_page(page_id, title, updated_body, version)

    def build_release_table_html(self, lane_attrs: dict, bag: dict) -> str:
        """
        Build an HTML table summarising a release — written into the Confluence page.
        Uses whatever values are available in lane_attrs + bag.
        """
        rows = [
            ("ARCAD Package", lane_attrs.get("arcad_package", "")),
            ("Market", lane_attrs.get("market", "")),
            ("Jira ID", lane_attrs.get("jira_id", "")),
            ("PR", bag.get("pr_url", "")),
            ("Build URL", bag.get("build_url", "")),
            ("Build result", bag.get("build_result", "")),
            ("CR Number", bag.get("cr_no", "")),
            ("CR URL", bag.get("cr_url", "")),
            ("SAST URL", bag.get("sast_url", "")),
            ("Cyber URL", bag.get("cyber_url", "")),
            ("G3 URL", bag.get("g3_url", "")),
        ]
        tr_rows = "".join(
            f"<tr><td><b>{label}</b></td><td>"
            + (f'<a href="{val}">{val}</a>' if val.startswith("http") else val)
            + "</td></tr>"
            for label, val in rows if val
        )
        return (
            f"<h2>Release: {lane_attrs.get('arcad_package','')}</h2>"
            f"<table><tbody>{tr_rows}</tbody></table>"
        )

    # ── Deep-link ─────────────────────────────────────────────────────────

    @staticmethod
    def build_deep_link(base_url: str, page_id: str) -> str:
        """Link to the Confluence page for the user to edit manually."""
        return f"{base_url.rstrip('/')}/pages/viewpage.action?pageId={page_id}"
