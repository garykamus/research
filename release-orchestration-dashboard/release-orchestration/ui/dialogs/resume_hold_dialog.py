from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)


class ResumeExternalHoldDialog(QDialog):
    """
    Resume an external_hold step.
    Renders capture_fields from the step's resume config as form fields.
    """

    def __init__(self, capture_fields: list[dict], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Resume — External Work Complete")
        self.setMinimumWidth(380)
        self._capture_fields = capture_fields
        self._field_widgets: dict[str, QLineEdit] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        info = QLabel(
            "Record the outputs of the external work before resuming the lane."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #555; font-size: 12px;")
        layout.addWidget(info)

        if self._capture_fields:
            form = QFormLayout()
            for field_def in self._capture_fields:
                edit = QLineEdit()
                edit.setPlaceholderText(field_def.get("label", field_def.get("key", "")))
                self._field_widgets[field_def["key"]] = edit
                form.addRow(field_def.get("label", field_def["key"]) + ":", edit)
            layout.addLayout(form)
        else:
            layout.addWidget(QLabel("No capture fields defined — click Confirm to resume."))

        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.button(QDialogButtonBox.StandardButton.Ok).setText("Confirm & Resume")
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def get_captured_values(self) -> dict[str, str]:
        return {
            key: widget.text().strip()
            for key, widget in self._field_widgets.items()
            if widget.text().strip()
        }
