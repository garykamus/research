from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from ui.widgets import btn as _btn

if TYPE_CHECKING:
    from core.models import StepInstance
    from core.service import ReleaseService

# Bag keys that are evidence candidates — label, key pairs.
_EVIDENCE_FIELDS = [
    ("CR Number",           "cr_no"),
    ("CR URL",              "cr_url"),
    ("Build URL",           "build_url"),
    ("Build result",        "build_result"),
    ("SAST URL",            "sast_url"),
    ("Cyber scan URL",      "cyber_url"),
    ("G3 URL",              "g3_url"),
    ("Test evidence URL",   "test_evidence_url"),
    ("Regression URL",      "regression_url"),
    ("PR URL",              "pr_url"),
]


class EvidenceUpdateView(QWidget):
    """
    Custom view for the update_evidence step.

    Shows all captured bag values with checkboxes. The user chooses which
    ones to publish to the CR audit page. Then triggers the update
    (REST if permitted, else deep-link / manual mark-done).
    """

    step_updated = Signal()

    def __init__(
        self,
        step: StepInstance,
        service: ReleaseService,
        lane_id: str,
        bag: dict[str, str],
        acting_user_id: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._step = step
        self._service = service
        self._lane_id = lane_id
        self._bag = bag
        self._acting_user_id = acting_user_id
        self._checkboxes: dict[str, QCheckBox] = {}
        self._extra_fields: dict[str, QLineEdit] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(8, 8, 8, 8)

        layout.addWidget(QLabel(
            "Select which captured values to publish to the CR audit page:"
        ))

        # Evidence checklist from bag
        group = QGroupBox("Available evidence")
        vbox = QVBoxLayout(group)

        has_any = False
        for label, key in _EVIDENCE_FIELDS:
            val = self._bag.get(key, "")
            if not val:
                continue
            has_any = True
            row = QHBoxLayout()
            cb = QCheckBox(f"{label}:")
            cb.setChecked(True)
            self._checkboxes[key] = cb
            row.addWidget(cb)
            val_lbl = QLabel(f'<a href="{val}">{val[:60]}</a>' if val.startswith("http") else val[:60])
            val_lbl.setOpenExternalLinks(True)
            val_lbl.setStyleSheet("color: #1a73e8; font-size: 12px;")
            row.addWidget(val_lbl)
            row.addStretch()
            vbox.addLayout(row)

        if not has_any:
            vbox.addWidget(QLabel("No evidence values captured yet. Run prior steps first."))

        layout.addWidget(group)

        # Extra fields from view_config (test_evidence_url, regression_url)
        extra_fields = self._step.view_config.get("fields", [])
        if extra_fields:
            extra_group = QGroupBox("Additional evidence URLs")
            form = QFormLayout(extra_group)
            for field_def in extra_fields:
                key = field_def["key"]
                edit = QLineEdit(self._bag.get(key, ""))
                edit.setPlaceholderText(field_def.get("label", key))
                self._extra_fields[key] = edit
                form.addRow(field_def.get("label", key) + ":", edit)
            layout.addWidget(extra_group)

        # Preview
        preview_btn = _btn("Preview evidence note", "ghost")
        preview_btn.clicked.connect(self._on_preview)
        layout.addWidget(preview_btn)

        # Action buttons
        btn_row = QHBoxLayout()
        publish_btn = _btn("▶ Publish to CR", "primary")
        publish_btn.clicked.connect(self._on_publish)
        btn_row.addWidget(publish_btn)

        mark_done_btn = _btn("Mark Done", "ghost")
        mark_done_btn.clicked.connect(self._on_mark_done)
        btn_row.addWidget(mark_done_btn)

        override_btn = _btn("Override", "ghost")
        override_btn.clicked.connect(self._on_override)
        btn_row.addWidget(override_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)

    def _collect_selected(self) -> dict[str, str]:
        selected = {}
        for key, cb in self._checkboxes.items():
            if cb.isChecked() and key in self._bag:
                selected[key] = self._bag[key]
        for key, edit in self._extra_fields.items():
            val = edit.text().strip()
            if val:
                selected[key] = val
        return selected

    def _on_preview(self) -> None:
        selected = self._collect_selected()
        if not selected:
            QMessageBox.information(self, "Preview", "No evidence selected.")
            return
        lines = [f"• {k}: {v}" for k, v in selected.items()]
        QMessageBox.information(self, "Evidence preview", "\n".join(lines))

    def _on_publish(self) -> None:
        selected = self._collect_selected()
        if not selected:
            QMessageBox.warning(self, "Nothing selected", "Select at least one evidence item.")
            return
        try:
            trigger_type = self._step.trigger_ref.get("type", "none")
            if trigger_type != "none":
                self._service.fire_step(self._lane_id, self._step.id, self._acting_user_id)
            self._service.advance_step(
                self._lane_id, self._step.id, self._acting_user_id,
                recorded_values=selected,
            )
            self.step_updated.emit()
        except Exception as e:
            QMessageBox.critical(self, "Publish failed", str(e))

    def _on_mark_done(self) -> None:
        selected = self._collect_selected()
        try:
            self._service.advance_step(
                self._lane_id, self._step.id, self._acting_user_id,
                recorded_values=selected if selected else None,
            )
            self.step_updated.emit()
        except ValueError as e:
            QMessageBox.warning(self, "Cannot advance", str(e))

    def _on_override(self) -> None:
        from ui.dialogs.override_dialog import OverrideDialog
        dlg = OverrideDialog(self._step.label, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            value, reason = dlg.get_values()
            try:
                self._service.override_step(
                    self._lane_id, self._step.id, value, reason, self._acting_user_id
                )
                self.step_updated.emit()
            except ValueError as e:
                QMessageBox.warning(self, "Override failed", str(e))
