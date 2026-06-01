from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from .base import IntegrationClient


class JenkinsClient(IntegrationClient):
    """
    Jenkins REST API client.

    Supports:
    - Triggering a job (POST to build URL with parameters)
    - Polling last build result (GET .../lastBuild/api/json)
    - Per-market param_map: renames canonical params to job-specific names

    Auth: token → "Authorization: Bearer <token>" header.
    """

    tool_name = "jenkins"

    def __init__(self, base_url: str, token: str | None = None) -> None:
        self._base = base_url.rstrip("/")
        self._token = token

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        return h

    def trigger_job(self, job_url: str, params: dict[str, str], param_map: dict[str, str] | None = None) -> dict:
        """
        POST to job_url to start a build.
        param_map remaps canonical keys → job-specific param names.
        Returns the queued item location (Location header) or empty dict.
        """
        mapped_params = {}
        pm = param_map or {}
        for k, v in params.items():
            mapped_key = pm.get(k, k)
            mapped_params[mapped_key] = v

        # Jenkins buildWithParameters endpoint
        query = "&".join(f"{k}={v}" for k, v in mapped_params.items())
        url = f"{job_url.rstrip('/')}/buildWithParameters"
        if query:
            url = f"{url}?{query}"

        req = urllib.request.Request(url, method="POST", headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                location = resp.headers.get("Location", "")
                return {"queued_url": location, "status_code": resp.status}
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Jenkins trigger failed HTTP {e.code}: {e.read().decode()[:300]}")

    def get_build_result(self, job_url: str) -> dict:
        """GET .../lastBuild/api/json — returns build JSON or raises on failure."""
        url = f"{job_url.rstrip('/')}/lastBuild/api/json"
        req = urllib.request.Request(url, headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Jenkins status check failed HTTP {e.code}: {e.read().decode()[:300]}")

    def get_queue_item(self, queue_url: str) -> dict:
        """GET queued build item to find the actual build number once it starts."""
        url = f"{queue_url.rstrip('/')}/api/json"
        req = urllib.request.Request(url, headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Jenkins queue check failed HTTP {e.code}")

    def rename_package(self, rename_url: str, from_name: str, to_name: str) -> dict:
        """POST to the rename pipeline with FROM/TO parameters."""
        return self.trigger_job(
            rename_url,
            params={"FROM": from_name, "TO": to_name},
        )
