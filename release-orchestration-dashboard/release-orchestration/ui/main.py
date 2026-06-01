from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

# Ensure the project root is on sys.path whether running from source or frozen exe.
_here = Path(__file__).parent
sys.path.insert(0, str(_here.parent))

from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox, QStackedWidget

from core.config.loader import FileConfigLoader
from core.credentials.stub_store import StubCredentialStore
from core.persistence.context import PersistenceContext
from core.service import ReleaseService
from core.worker.poller import LanePoller

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)

logger = logging.getLogger(__name__)


def get_app_data_dir() -> str:
    if getattr(sys, "frozen", False):
        # Packaged exe: use %APPDATA%\ReleaseOrchestration
        appdata = os.environ.get("APPDATA", str(Path.home()))
        return str(Path(appdata) / "ReleaseOrchestration")
    # Dev mode: .data/ alongside the project root
    return str(_here.parent / ".data")


def get_db_path() -> str:
    data_dir = get_app_data_dir()
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    return str(Path(data_dir) / "release_orch.db")


def get_qss_path() -> str:
    if getattr(sys, "frozen", False):
        return str(Path(sys._MEIPASS) / "ui" / "resources" / "style.qss")
    return str(_here / "resources" / "style.qss")


class MainWindow(QMainWindow):
    def __init__(self, service: ReleaseService, acting_user_id: str) -> None:
        super().__init__()
        self._service = service
        self._acting_user_id = acting_user_id
        self.setWindowTitle("Release Orchestration Dashboard")
        self.resize(1200, 750)
        self._stack = QStackedWidget()
        self.setCentralWidget(self._stack)
        self._show_matrix()

    def _show_matrix(self) -> None:
        from ui.matrix_view import MatrixView
        view = MatrixView(self._service, self._acting_user_id, parent=self)
        view.lane_selected.connect(self._show_lane_detail)
        self._stack.addWidget(view)
        self._stack.setCurrentWidget(view)

    def _show_lane_detail(self, lane_id: str) -> None:
        from ui.lane_detail_view import LaneDetailView
        view = LaneDetailView(
            self._service, lane_id, self._acting_user_id, parent=self
        )
        view.back_requested.connect(self._go_back)
        self._stack.addWidget(view)
        self._stack.setCurrentWidget(view)

    def _go_back(self) -> None:
        current = self._stack.currentWidget()
        if self._stack.count() > 1:
            self._stack.setCurrentIndex(self._stack.count() - 2)
            self._stack.removeWidget(current)
            current.deleteLater()
        # Refresh the matrix view.
        matrix = self._stack.currentWidget()
        if hasattr(matrix, "refresh"):
            matrix.refresh()


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("ReleaseOrchestration")
    app.setOrganizationName("ReleaseOrch")

    # Load stylesheet.
    qss_path = get_qss_path()
    if Path(qss_path).exists():
        with open(qss_path, encoding="utf-8") as f:
            app.setStyleSheet(f.read())

    # Bootstrap core.
    data_dir = get_app_data_dir()
    db_path = get_db_path()

    # First-run setup: shown when the database does not yet exist.
    windows_username = os.environ.get("USERNAME", "developer")
    from ui.dialogs.first_run_dialog import run_first_run_if_needed
    display_name = run_first_run_if_needed(data_dir, db_path, windows_username.capitalize())
    if display_name is None:
        sys.exit(0)

    try:
        ctx = PersistenceContext(db_path)
    except Exception as e:
        QMessageBox.critical(None, "Database error", str(e))
        sys.exit(1)

    try:
        config = FileConfigLoader()
    except Exception as e:
        QMessageBox.critical(None, "Config error", str(e))
        sys.exit(1)

    # Startup validation — catch broken market bindings early.
    from core.config.resolver import LaneResolver
    resolver = LaneResolver(config)
    validation = resolver.validate_all_markets()
    broken = {m: errs for m, errs in validation.items() if errs}
    if broken:
        msg = "Config validation warnings:\n\n"
        for market, errs in broken.items():
            msg += f"  {market}: {'; '.join(errs)}\n"
        QMessageBox.warning(None, "Config warnings", msg)

    # Phase 2: use DPAPI credential store.
    from core.credentials.dpapi_store import DPAPICredentialStore
    creds = DPAPICredentialStore(ctx.credentials)
    service = ReleaseService(ctx, config, creds)

    # Default user — use the confirmed display_name from first-run or normal launch.
    user = ctx.users.get_or_create_default_user(windows_username, display_name)

    # Start background poller.
    poller = LanePoller(service, interval_seconds=30)
    poller.start()

    # Start webhook receiver (localhost only; configure port via env var).
    webhook_port = int(os.environ.get("RELEASE_ORCH_WEBHOOK_PORT", "9876"))
    from core.webhook.receiver import WebhookReceiver
    webhook = WebhookReceiver(service, port=webhook_port)
    try:
        webhook.start()
    except Exception as e:
        logger.warning("Webhook receiver could not start (port %d): %s", webhook_port, e)
        webhook = None

    # Auto-register step views.
    from ui.stepviews.registry import _auto_register
    _auto_register()

    window = MainWindow(service, user.id)
    window.show()

    exit_code = app.exec()
    poller.stop()
    if webhook:
        webhook.stop()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
