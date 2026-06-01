from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)
from ui.widgets import btn as _btn

if TYPE_CHECKING:
    from core.models import StepInstance
    from core.service import ReleaseService


class GenericStepView(QWidget):
    """
    Renders any step using view_config.fields.
    Supports field types: text, url, number, dropdown, checkbox, datetime.
    Buttons: Mark Done, Override, Record Link.
    Shows value-flow note (produces / consumes).
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
        self._field_widgets: dict[str, QWidget] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Value-flow note.
        flow_note = self._build_flow_note()
        if flow_note:
            layout.addWidget(flow_note)

        # Fields from view_config.
        fields = self._step.view_config.get("fields", [])
        if fields:
            form = QFormLayout()
            form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
            for field_def in fields:
                widget = self._make_field_widget(field_def)
                self._field_widgets[field_def["key"]] = widget
                form.addRow(field_def.get("label", field_def["key"]) + ":", widget)
            layout.addLayout(form)

        # Status indicator (shown when step is IN_PROGRESS).
        if self._step.status == "IN_PROGRESS":
            self._status_label = QLabel("⏳ Trigger running — polling for result…")
            self._status_label.setStyleSheet("color: #0078d4; font-size: 12px;")
            layout.addWidget(self._status_label)
        elif self._step.status == "BLOCKED":
            self._status_label = QLabel("✗ Trigger failed — check logs or override.")
            self._status_label.setStyleSheet("color: #d32f2f; font-size: 12px;")
            layout.addWidget(self._status_label)

        # Action buttons.
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        trigger_type = self._step.trigger_ref.get("type", "none")
        is_automated = trigger_type != "none"

        if is_automated and self._step.status not in ("DONE", "SKIPPED", "IN_PROGRESS"):
            trigger_btn = _btn("▶ Trigger", "primary")
            trigger_btn.clicked.connect(self._on_trigger)
            btn_row.addWidget(trigger_btn)

        mark_done_btn = _btn("Mark Done", "primary")
        mark_done_btn.clicked.connect(self._on_mark_done)
        btn_row.addWidget(mark_done_btn)

        override_btn = _btn("Override", "ghost")
        override_btn.clicked.connect(self._on_override)
        btn_row.addWidget(override_btn)

        link_btn = _btn("Record Link", "ghost")
        link_btn.clicked.connect(self._on_record_link)
        btn_row.addWidget(link_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)

        # Existing override notice.
        if self._step.override:
            ov_label = QLabel(
                f"Override applied: {self._step.override.value} "
                f'— "{self._step.override.reason}"'
            )
            ov_label.setObjectName("statusWaiting")
            ov_label.setWordWrap(True)
            layout.addWidget(ov_label)

    def _build_flow_note(self) -> QLabel | None:
        parts: list[str] = []
        if self._step.produces:
            parts.append(f"Produces: {', '.join(self._step.produces)}")
        if self._step.consumes:
            parts.append(f"Consumes: {', '.join(self._step.consumes)}")
        if not parts:
            return None
        label = QLabel(" · ".join(parts))
        label.setStyleSheet("color: #666; font-size: 11px;")
        return label

    def _make_field_widget(self, field_def: dict) -> QWidget:
        ftype = field_def.get("type", "text")
        key = field_def["key"]
        current_val = self._bag.get(key, "")

        if ftype in ("text", "url", "number"):
            return QLineEdit(current_val)
        elif ftype == "dropdown":
            w = QComboBox()
            for opt in field_def.get("options", []):
                w.addItem(str(opt))
            if current_val:
                idx = w.findText(current_val)
                if idx >= 0:
                    w.setCurrentIndex(idx)
            return w
        elif ftype == "checkbox":
            w = QCheckBox()
            w.setChecked(current_val.lower() in ("true", "1", "yes"))
            return w
        elif ftype == "datetime":
            w = QDateTimeEdit()
            w.setCalendarPopup(True)
            return w
        return QLineEdit(current_val)

    def _collect_field_values(self) -> dict[str, str]:
        values: dict[str, str] = {}
        for key, widget in self._field_widgets.items():
            if isinstance(widget, QLineEdit):
                values[key] = widget.text().strip()
            elif isinstance(widget, QComboBox):
                values[key] = widget.currentText()
            elif isinstance(widget, QCheckBox):
                values[key] = "true" if widget.isChecked() else "false"
            elif isinstance(widget, QDateTimeEdit):
                values[key] = widget.dateTime().toString("yyyy-MM-ddTHH:mm:ss")
        return {k: v for k, v in values.items() if v}

    def _on_trigger(self) -> None:
        """Fire the step's automated trigger. Checks for missing credentials first."""
        from PySide6.QtWidgets import QMessageBox
        tool_name = self._step.trigger_ref.get("tool", "")
        if not tool_name:
            # fall back to step definition
            try:
                step_def = self._service._config.get_step_definition(self._step.definition_ref)
                tool_name = step_def.get("tool", "")
            except Exception:
                pass

        if tool_name:
            cred = self._service.get_credential(self._acting_user_id, tool_name)
            if not cred:
                reply = QMessageBox.question(
                    self,
                    "Credentials required",
                    f"No credentials configured for <b>{tool_name}</b>.<br>"
                    "Open the Credential Manager now?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if reply == QMessageBox.StandardButton.Yes:
                    from ui.dialogs.credential_dialog import CredentialManagerDialog
                    dlg = CredentialManagerDialog(self._service, self._acting_user_id, parent=self)
                    dlg.exec()
                return

        try:
            self._service.fire_step(self._lane_id, self._step.id, self._acting_user_id)
            self.step_updated.emit()
        except ValueError as e:
            QMessageBox.warning(self, "Trigger failed", str(e))
        except Exception as e:
            QMessageBox.critical(self, "Trigger error", str(e))

    def _on_mark_done(self) -> None:
        field_values = self._collect_field_values()
        try:
            self._service.advance_step(
                self._lane_id, self._step.id, self._acting_user_id,
                recorded_values=field_values if field_values else None,
            )
            self.step_updated.emit()
        except ValueError as e:
            from PySide6.QtWidgets import QMessageBox
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
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "Override failed", str(e))

    def _on_record_link(self) -> None:
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout
        dlg = QDialog(self)
        dlg.setWindowTitle("Record Link")
        lay = QVBoxLayout(dlg)
        form = QFormLayout()
        label_edit = QLineEdit()
        url_edit = QLineEdit()
        form.addRow("Label:", label_edit)
        form.addRow("URL:", url_edit)
        lay.addLayout(form)
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        lay.addWidget(btns)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            label = label_edit.text().strip()
            url = url_edit.text().strip()
            if label and url:
                self._service.record_link(
                    self._lane_id, self._step.id, label, url, self._acting_user_id
                )
                self.step_updated.emit()
