from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from .base import IntegrationClient


class GitHubClient(IntegrationClient):
    """
    GitHub REST API client.

    Supports:
    - Creating a pull request
    - Checking PR merge status (for webhook fallback polling)

    Auth: token → "Authorization: Bearer <token>" + "Accept: application/vnd.github+json"
    """

    tool_name = "github"
    _API_BASE = "https://api.github.com"

    def __init__(self, token: str | None = None, api_base: str | None = None) -> None:
        self._token = token
        self._api = (api_base or self._API_BASE).rstrip("/")

    def _headers(self) -> dict[str, str]:
        h = {
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        return h

    def _request(self, method: str, path: str, body: dict | None = None) -> Any:
        url = f"{self._api}{path}"
        data = json.dumps(body).encode() if body else None
        req = urllib.request.Request(url, data=data, headers=self._headers(), method=method)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"GitHub API {method} {path} failed HTTP {e.code}: {e.read().decode()[:300]}")

    def create_pull_request(
        self, repo: str, head: str, base: str, title: str
    ) -> dict:
        """POST /repos/{repo}/pulls — returns PR JSON with html_url, number."""
        return self._request("POST", f"/repos/{repo}/pulls", {
            "head": head,
            "base": base,
            "title": title,
        })

    def get_pull_request(self, repo: str, pr_number: int) -> dict:
        """GET /repos/{repo}/pulls/{pr_number}"""
        return self._request("GET", f"/repos/{repo}/pulls/{pr_number}")

    def is_pr_merged(self, repo: str, pr_number: int) -> bool:
        """True if the PR has been merged (HTTP 204 = merged, 404 = not merged)."""
        url = f"{self._api}/repos/{repo}/pulls/{pr_number}/merge"
        req = urllib.request.Request(url, headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=15):
                return True
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return False
            raise RuntimeError(f"GitHub merge check failed HTTP {e.code}")
