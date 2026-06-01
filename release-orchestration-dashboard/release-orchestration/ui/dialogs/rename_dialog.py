from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QTextEdit,
    QVBoxLayout,
)


class RenamePackageDialog(QDialog):
    """
    Rename ARCAD package + branch (lane-level action).
    Both new_name and reason must be filled before OK is enabled.
    """

    def __init__(self, current_name: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Rename ARCAD Package + Branch")
        self.setMinimumWidth(400)
        self._build_ui(current_name)

    def _build_ui(self, current_name: str) -> None:
        layout = QVBoxLayout(self)

        info = QLabel(
            f"Current name: <b>{current_name}</b><br>"
            "Renaming updates both the ARCAD package and the market-repo branch together."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        form = QFormLayout()

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("New package / branch name")
        self._name_edit.textChanged.connect(self._update_ok_button)
        form.addRow("New name:", self._name_edit)

        self._reason_edit = QTextEdit()
        self._reason_edit.setPlaceholderText("Reason for rename…")
        self._reason_edit.setMaximumHeight(70)
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
        ok = bool(self._name_edit.text().strip()) and bool(
            self._reason_edit.toPlainText().strip()
        )
        self._btn_box.button(QDialogButtonBox.StandardButton.Ok).setEnabled(ok)

    def get_values(self) -> tuple[str, str]:
        return self._name_edit.text().strip(), self._reason_edit.toPlainText().strip()
