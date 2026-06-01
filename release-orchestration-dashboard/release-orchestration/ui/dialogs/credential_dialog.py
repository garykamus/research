from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from core.service import ReleaseService


class CredentialEntryDialog(QDialog):
    """
    Enter or update a credential for a single tool.
    Supports auth types: token, basic, form_login.
    """

    def __init__(
        self,
        tool_name: str,
        auth_type: str,
        existing: dict | None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Credentials — {tool_name}")
        self.setMinimumWidth(380)
        self._tool = tool_name
        self._auth_type = auth_type
        self._build_ui(existing or {})

    def _build_ui(self, existing: dict) -> None:
        layout = QVBoxLayout(self)

        info = QLabel(
            f"<b>{self._tool}</b> — auth type: <i>{self._auth_type}</i><br>"
            "Credentials are encrypted with Windows DPAPI and stored locally."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        form = QFormLayout()
        self._fields: dict[str, QLineEdit] = {}

        if self._auth_type == "token":
            w = QLineEdit(existing.get("token", ""))
            w.setEchoMode(QLineEdit.EchoMode.Password)
            w.setPlaceholderText("Paste API token / PAT")
            self._fields["token"] = w
            form.addRow("Token:", w)

        elif self._auth_type in ("basic", "form_login"):
            u = QLineEdit(existing.get("username", ""))
            u.setPlaceholderText("Username")
            self._fields["username"] = u
            form.addRow("Username:", u)

            p = QLineEdit(existing.get("password", ""))
            p.setEchoMode(QLineEdit.EchoMode.Password)
            p.setPlaceholderText("Password")
            self._fields["password"] = p
            form.addRow("Password:", p)

        layout.addLayout(form)

        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.accepted.connect(self._on_save)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def _on_save(self) -> None:
        if self._auth_type == "token" and not self._fields.get("token", QLineEdit()).text().strip():
            QMessageBox.warning(self, "Validation", "Token cannot be empty.")
            return
        self.accept()

    def get_credential(self) -> dict:
        return {k: w.text().strip() for k, w in self._fields.items()}


class CredentialManagerDialog(QDialog):
    """
    Manage all credentials for the current user.
    Lists configured tools; allows adding, updating, and removing credentials.
    """

    def __init__(self, service: ReleaseService, user_id: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Credential Manager")
        self.setMinimumSize(500, 380)
        self._service = service
        self._user_id = user_id
        self._build_ui()
        self._refresh_list()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        header = QLabel(
            "Credentials are encrypted with Windows DPAPI and stored on this machine.\n"
            "Each tool uses either a token (preferred) or username + password."
        )
        header.setWordWrap(True)
        header.setStyleSheet("color: #555; font-size: 12px;")
        layout.addWidget(header)

        self._list = QListWidget()
        self._list.setMinimumHeight(160)
        layout.addWidget(self._list)

        btn_row = QVBoxLayout()
        # Dropdown to pick a tool to add/edit
        tools_cfg = self._service._config.get_tools()
        self._tool_combo = QComboBox()
        for tool_name in sorted(tools_cfg.keys()):
            self._tool_combo.addItem(tool_name)

        add_btn = QPushButton("Add / Update credential")
        add_btn.clicked.connect(self._on_add_update)
        remove_btn = QPushButton("Remove selected")
        remove_btn.clicked.connect(self._on_remove)

        btn_row.addWidget(self._tool_combo)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(remove_btn)
        layout.addLayout(btn_row)

        close_btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_btn.rejected.connect(self.reject)
        layout.addWidget(close_btn)

    def _refresh_list(self) -> None:
        self._list.clear()
        try:
            configured = self._service.list_configured_tools(self._user_id)
            for tool in sorted(configured):
                self._list.addItem(f"✓  {tool}")
        except Exception:
            pass

    def _on_add_update(self) -> None:
        tool_name = self._tool_combo.currentText()
        tools_cfg = self._service._config.get_tools()
        auth_type = tools_cfg.get(tool_name, {}).get("auth", "token")
        existing = self._service.get_credential(self._user_id, tool_name)
        dlg = CredentialEntryDialog(tool_name, auth_type, existing, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            try:
                self._service.set_credential(self._user_id, tool_name, dlg.get_credential())
                self._refresh_list()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save credential:\n{e}")

    def _on_remove(self) -> None:
        items = self._list.selectedItems()
        if not items:
            return
        tool = items[0].text().replace("✓  ", "").strip()
        try:
            self._service.delete_credential(self._user_id, tool)
            self._refresh_list()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to remove credential:\n{e}")
