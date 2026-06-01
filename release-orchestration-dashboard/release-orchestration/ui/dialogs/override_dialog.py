from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QTextEdit,
    QVBoxLayout,
)


class OverrideDialog(QDialog):
    """
    Override a step's result.
    Requires a non-empty reason before OK is enabled (attributability mandate).
    """

    def __init__(self, step_label: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Override: {step_label}")
        self.setMinimumWidth(380)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        info = QLabel(
            "Override forces a result regardless of automation. "
            "A reason is mandatory for audit."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #555; font-size: 12px;")
        layout.addWidget(info)

        form = QFormLayout()

        self._value_combo = QComboBox()
        self._value_combo.addItems(["DONE", "FAILED", "BLOCKED"])
        form.addRow("Override to:", self._value_combo)

        self._reason_edit = QTextEdit()
        self._reason_edit.setPlaceholderText("Explain why this override is necessary…")
        self._reason_edit.setMaximumHeight(80)
        self._reason_edit.textChanged.connect(self._update_ok_button)
        form.addRow("Reason (required):", self._reason_edit)

        layout.addLayout(form)

        self._btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._btn_box.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        self._btn_box.accepted.connect(self.accept)
        self._btn_box.rejected.connect(self.reject)
        layout.addWidget(self._btn_box)

    def _update_ok_button(self) -> None:
        has_reason = bool(self._reason_edit.toPlainText().strip())
        self._btn_box.button(QDialogButtonBox.StandardButton.Ok).setEnabled(has_reason)

    def get_values(self) -> tuple[str, str]:
        return self._value_combo.currentText(), self._reason_edit.toPlainText().strip()
