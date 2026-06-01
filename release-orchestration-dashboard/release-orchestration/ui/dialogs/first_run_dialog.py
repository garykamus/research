from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)


class FirstRunDialog(QDialog):
    """
    Shown on first launch (no database exists yet).

    Collects:
      - The user's display name (defaults to OS username)
      - A confirmation that the data directory location is acceptable

    Does NOT collect credentials here — those are entered per-tool via the
    Credential Manager after first launch. The dialog simply orients the
    developer and verifies the app-data path is writable.
    """

    def __init__(self, data_dir: str, username: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Release Orchestration — First-run setup")
        self.setMinimumWidth(480)
        self._data_dir = data_dir
        self._build_ui(username)

    def _build_ui(self, default_username: str) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        header = QLabel(
            "<b>Welcome to Release Orchestration Dashboard</b><br><br>"
            "This is the first time the app has run on this machine. "
            "Your release state and audit log will be stored in the location shown below. "
            "Credentials are encrypted with Windows DPAPI — they never leave this machine."
        )
        header.setWordWrap(True)
        layout.addWidget(header)

        form = QFormLayout()
        form.setSpacing(8)

        self._name_edit = QLineEdit(default_username)
        self._name_edit.setPlaceholderText("Your display name")
        form.addRow("Your name:", self._name_edit)

        data_lbl = QLabel(self._data_dir)
        data_lbl.setStyleSheet("color: #444; font-size: 12px;")
        data_lbl.setWordWrap(True)
        form.addRow("Data directory:", data_lbl)

        layout.addLayout(form)

        verify_btn = QPushButton("Verify data directory is writable")
        verify_btn.clicked.connect(self._verify_data_dir)
        layout.addWidget(verify_btn)

        note = QLabel(
            "After setup you can add tool credentials via <i>Actions → Manage credentials</i>."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(note)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _verify_data_dir(self) -> None:
        try:
            path = Path(self._data_dir)
            path.mkdir(parents=True, exist_ok=True)
            test_file = path / ".write_test"
            test_file.write_text("ok")
            test_file.unlink()
            QMessageBox.information(self, "OK", f"Directory is writable:\n{self._data_dir}")
        except Exception as exc:
            QMessageBox.critical(self, "Not writable", f"Cannot write to:\n{self._data_dir}\n\n{exc}")

    def _on_accept(self) -> None:
        name = self._name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Name required", "Please enter your display name.")
            return
        self.accept()

    def display_name(self) -> str:
        return self._name_edit.text().strip()


def run_first_run_if_needed(data_dir: str, db_path: str, username: str) -> str | None:
    """
    If the database does not yet exist, show the first-run dialog.

    Returns the confirmed display name on acceptance, or None if the user
    cancelled (caller should exit).

    Safe to call before QApplication.exec() as long as a QApplication exists.
    """
    if Path(db_path).exists():
        return username  # not first run

    dlg = FirstRunDialog(data_dir, username)
    dlg.setWindowModality(Qt.WindowModality.ApplicationModal)
    if dlg.exec() == QDialog.DialogCode.Accepted:
        return dlg.display_name()
    return None
