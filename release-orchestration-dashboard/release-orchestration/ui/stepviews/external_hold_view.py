from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)
from ui.widgets import btn as _btn

if TYPE_CHECKING:
    from core.models import StepInstance
    from core.service import ReleaseService


class ExternalHoldView(QWidget):
    """
    Renders an external_hold step: shows SUSPENDED status,
    description of what external work is pending,
    and a Resume / Continue button that opens ResumeExternalHoldDialog.
    """

    step_updated = Signal()

    def __init__(
        self,
        step: StepInstance,
        service: ReleaseService,
        lane_id: str,
        acting_user_id: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._step = step
        self._service = service
        self._lane_id = lane_id
        self._acting_user_id = acting_user_id
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        status_label = QLabel("⏸  Lane is SUSPENDED — waiting on external process")
        status_label.setObjectName("statusSuspended")
        layout.addWidget(status_label)

        desc_label = QLabel(
            "This step parks the lane while an external team or process does work "
            "outside the dashboard. Once that work is complete, click Resume."
        )
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("color: #555; font-size: 12px;")
        layout.addWidget(desc_label)

        btn_row = QHBoxLayout()
        resume_btn = _btn("Resume / Continue", "primary")
        resume_btn.clicked.connect(self._on_resume)
        btn_row.addWidget(resume_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

    def _on_resume(self) -> None:
        resume_cfg = self._step.trigger_ref  # step_def.resume stored here in Phase 1
        # The resume config is actually in view_config for Phase 1 (since trigger is 'none').
        # Fetch capture_fields from the step definition via trigger_ref or view_config.
        capture_fields: list[dict] = []
        if hasattr(self._step, "view_config"):
            capture_fields = self._step.view_config.get("capture_fields", [])

        from ui.dialogs.resume_hold_dialog import ResumeExternalHoldDialog
        dlg = ResumeExternalHoldDialog(capture_fields, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            captured = dlg.get_captured_values()
            try:
                self._service.resume_external_hold(
                    self._lane_id, self._step.id, self._acting_user_id,
                    captured_values=captured if captured else None,
                )
                self.step_updated.emit()
            except ValueError as e:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "Resume failed", str(e))
