from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.service import ReleaseService

logger = logging.getLogger(__name__)


class WebhookReceiver:
    """
    Lightweight HTTP server that listens for inbound webhook events from
    Jenkins (build complete) and GitHub (PR merged).

    Runs in a daemon thread alongside the app. Binds to localhost only —
    expects Jenkins/GitHub to reach it via a tunnel (e.g. ngrok) or
    internal network routing.

    Endpoint: POST /webhook
    Body (JSON):
      {
        "event":     "build_complete" | "pr_merged" | ...,
        "lane_id":   "<lane_id>",          # optional — direct correlation
        "branch":    "<branch_name>",      # used to correlate when lane_id absent
        "build_url": "<url>",              # captured into bag
        "result":    "SUCCESS" | "FAILED"  # build result
      }

    On a recognised event the receiver calls service.refresh_status() or
    service.resume_external_hold() as appropriate.
    """

    def __init__(self, service: ReleaseService, host: str = "127.0.0.1", port: int = 9876) -> None:
        self._service = service
        self._host = host
        self._port = port
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        service = self._service

        class _Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                if self.path != "/webhook":
                    self.send_response(404)
                    self.end_headers()
                    return
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    body = self.rfile.read(length)
                    payload = json.loads(body)
                except Exception:
                    self.send_response(400)
                    self.end_headers()
                    return
                try:
                    _dispatch(service, payload)
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b'{"ok":true}')
                except Exception:
                    logger.exception("Webhook dispatch error")
                    self.send_response(500)
                    self.end_headers()

            def log_message(self, fmt, *args) -> None:
                logger.debug("Webhook: " + fmt, *args)

        self._server = HTTPServer((self._host, self._port), _Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="WebhookReceiver",
            daemon=True,
        )
        self._thread.start()
        logger.info("WebhookReceiver listening on %s:%d/webhook", self._host, self._port)

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
        logger.info("WebhookReceiver stopped")


def _dispatch(service: ReleaseService, payload: dict[str, Any]) -> None:
    """Route an inbound webhook to the right service call."""
    event = payload.get("event", "")
    lane_id = payload.get("lane_id")
    branch = payload.get("branch", "")

    # If lane_id not given, find the lane by branch name.
    if not lane_id and branch:
        lanes = service.list_lanes()
        for lane in lanes:
            if lane.branch_name == branch:
                lane_id = lane.id
                break

    if not lane_id:
        logger.warning("Webhook event '%s' could not be correlated to a lane (branch=%s)", event, branch)
        return

    if event in ("build_complete", "jenkins_build"):
        _handle_build_event(service, lane_id, payload)
    elif event in ("pr_merged", "github_pr"):
        _handle_pr_event(service, lane_id, payload)
    elif event == "resume_external_hold":
        _handle_resume_event(service, lane_id, payload)
    else:
        logger.warning("Unknown webhook event: %s", event)


def _handle_build_event(service: ReleaseService, lane_id: str, payload: dict) -> None:
    """Jenkins build complete — refresh the IN_PROGRESS step."""
    result = payload.get("result", "UNKNOWN").upper()
    build_url = payload.get("build_url", "")
    if build_url:
        # Inject the build URL into the bag via refresh.
        try:
            detail = service.get_lane_detail(lane_id)
            in_progress = [s for s in detail.steps if s.status == "IN_PROGRESS"]
            if in_progress and build_url:
                service.record_value(
                    lane_id, in_progress[0].id, "build_url", build_url, "SYSTEM"
                )
        except Exception:
            pass
    service.refresh_status(lane_id, "SYSTEM")
    logger.info("Webhook build_complete processed for lane %s (result=%s)", lane_id[:8], result)


def _handle_pr_event(service: ReleaseService, lane_id: str, payload: dict) -> None:
    """GitHub PR merged — advance the step that's waiting on the PR."""
    service.refresh_status(lane_id, "SYSTEM")
    logger.info("Webhook pr_merged processed for lane %s", lane_id[:8])


def _handle_resume_event(service: ReleaseService, lane_id: str, payload: dict) -> None:
    """External hold manual resume via webhook."""
    try:
        detail = service.get_lane_detail(lane_id)
        hold_steps = [s for s in detail.steps if s.kind == "external_hold" and s.status == "SUSPENDED"]
        if hold_steps:
            captured = {k: v for k, v in payload.items()
                        if k not in ("event", "lane_id", "branch")}
            service.resume_external_hold(lane_id, hold_steps[0].id, "SYSTEM", captured)
            logger.info("Webhook resumed external_hold on lane %s", lane_id[:8])
    except Exception:
        logger.exception("Webhook resume_external_hold failed for lane %s", lane_id[:8])
