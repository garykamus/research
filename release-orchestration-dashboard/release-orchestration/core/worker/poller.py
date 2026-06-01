from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.service import ReleaseService

logger = logging.getLogger(__name__)


class LanePoller:
    """
    Background daemon thread that periodically checks waiting/in-progress lanes.

    On each tick:
    1. List all ACTIVE, WAITING, and BLOCKED lanes.
    2. For each lane that has an IN_PROGRESS step (automated trigger),
       call service.refresh_status() to live-check the external system.
    3. Log but swallow any per-lane errors so one bad lane can't stop the poller.

    Thread safety: each call to service.refresh_status() uses a fresh DB
    connection (per-thread SQLite — see Database.connect()).
    """

    def __init__(self, service: ReleaseService, interval_seconds: int = 30) -> None:
        self._service = service
        self._interval = interval_seconds
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        # System actor id used for automated state updates.
        self._system_actor = "SYSTEM"

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, name="LanePoller", daemon=True
        )
        self._thread.start()
        logger.debug("LanePoller started (interval=%ds)", self._interval)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        logger.debug("LanePoller stopped")

    def _run(self) -> None:
        # Immediate startup poll so a restart catches up without waiting one full interval.
        try:
            self._poll_once()
        except Exception:
            logger.exception("LanePoller startup poll failed")

        while not self._stop_event.wait(timeout=self._interval):
            try:
                self._poll_once()
            except Exception:
                logger.exception("LanePoller._poll_once raised an unhandled exception")

    def _poll_once(self) -> None:
        """
        Check all non-terminal lanes for IN_PROGRESS steps and live-refresh them.
        Only polls lanes that have at least one IN_PROGRESS automated step —
        never polls all lanes unconditionally (spec §01.3).
        """
        try:
            active_lanes = self._service.list_lanes(status="ACTIVE")
            waiting_lanes = self._service.list_lanes(status="WAITING")
            blocked_lanes = self._service.list_lanes(status="BLOCKED")
        except Exception:
            logger.exception("LanePoller: failed to list lanes")
            return

        candidates = active_lanes + waiting_lanes + blocked_lanes
        if not candidates:
            return

        for lane in candidates:
            try:
                detail = self._service.get_lane_detail(lane.id)
                # Only poll if there's an IN_PROGRESS automated step.
                has_in_progress = any(
                    s.status == "IN_PROGRESS"
                    and s.trigger_ref.get("type", "none") != "none"
                    for s in detail.steps
                )
                if not has_in_progress:
                    continue

                updated_step = self._service.refresh_status(lane.id, self._system_actor)
                if updated_step:
                    logger.info(
                        "LanePoller: lane %s step %s → %s",
                        lane.id[:8], updated_step.id, updated_step.status,
                    )
            except Exception:
                logger.exception("LanePoller: error refreshing lane %s", lane.id[:8])
