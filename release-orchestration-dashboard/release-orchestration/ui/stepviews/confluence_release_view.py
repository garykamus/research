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
    QVBoxLayout,
    QWidget,
)
from ui.widgets import btn as _btn

if TYPE_CHECKING:
    from core.models import StepInstance
    from core.service import ReleaseService

_RELEASE_FIELDS = [
    ("ARCAD Package",    "arcad_package", True),   # (label, key, from_attrs)
    ("Market",           "market",        True),
    ("Jira ID",          "jira_id",       True),
    ("PR URL",           "pr_url",        False),
    ("Build URL",        "build_url",     False),
    ("Build result",     "build_result",  False),
    ("CR Number",        "cr_no",         False),
    ("CR URL",           "cr_url",        False),
    ("SAST URL",         "sast_url",      False),
    ("G3 URL",           "g3_url",        False),
]


class ConfluenceReleaseView(QWidget):
    """
    Custom view for the update_confluence_release step.

    Lets the user choose/preview which values to publish to the Confluence
    release page. Uses Confluence REST API (Tier 1) if a token credential is
    configured; otherwise opens the Confluence page in the browser (Tier 3).
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
        self._attrs: dict[str, str] = {}
        try:
            self._attrs = service.get_lane_detail(lane_id).attributes
        except Exception:
            pass
        self._build_ui()

    def _resolve_value(self, key: str, from_attrs: bool) -> str:
        if from_attrs:
            return self._attrs.get(key, "")
        return self._bag.get(key, "")

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(8, 8, 8, 8)

        layout.addWidget(QLabel(
            "Choose fields to publish to the Confluence release page:"
        ))

        group = QGroupBox("Fields to include")
        vbox = QVBoxLayout(group)

        for label, key, from_attrs in _RELEASE_FIELDS:
            val = self._resolve_value(key, from_attrs)
            if not val:
                continue
            row = QHBoxLayout()
            cb = QCheckBox(f"{label}:")
            cb.setChecked(True)
            self._checkboxes[key] = cb
            row.addWidget(cb)
            display = f'<a href="{val}">{val[:55]}</a>' if val.startswith("http") else val[:55]
            lbl = QLabel(display)
            lbl.setOpenExternalLinks(True)
            lbl.setStyleSheet("font-size: 12px;")
            row.addWidget(lbl)
            row.addStretch()
            vbox.addLayout(row)

        if not self._checkboxes:
            vbox.addWidget(QLabel("No release values available yet. Complete prior steps."))

        layout.addWidget(group)

        # Confluence page ID field (may be pre-filled from confluence_page attr)
        conf_page = self._attrs.get("confluence_page", "")
        form = QFormLayout()
        self._page_edit = QLineEdit(conf_page)
        self._page_edit.setPlaceholderText("https://confluence.example.com/pages/... or page ID")
        form.addRow("Confluence page:", self._page_edit)
        layout.addLayout(form)

        # Preview
        preview_btn = _btn("Preview table", "ghost")
        preview_btn.clicked.connect(self._on_preview)
        layout.addWidget(preview_btn)

        # Action buttons
        btn_row = QHBoxLayout()

        publish_btn = _btn("▶ Publish via API", "primary")
        publish_btn.clicked.connect(self._on_publish_api)
        btn_row.addWidget(publish_btn)

        open_btn = _btn("🔗 Open Confluence page", "ghost")
        open_btn.clicked.connect(self._on_open_page)
        btn_row.addWidget(open_btn)

        mark_done_btn = _btn("Mark Done", "ghost")
        mark_done_btn.clicked.connect(self._on_mark_done)
        btn_row.addWidget(mark_done_btn)

        override_btn = _btn("Override", "ghost")
        override_btn.clicked.connect(self._on_override)
        btn_row.addWidget(override_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)

    def _collect_selected(self) -> dict[str, str]:
        result = {}
        for (label, key, from_attrs) in _RELEASE_FIELDS:
            if key in self._checkboxes and self._checkboxes[key].isChecked():
                result[key] = self._resolve_value(key, from_attrs)
        return {k: v for k, v in result.items() if v}

    def _on_preview(self) -> None:
        selected = self._collect_selected()
        if not selected:
            QMessageBox.information(self, "Preview", "No fields selected.")
            return
        lines = [f"• {k}: {v}" for k, v in selected.items()]
        QMessageBox.information(self, "Confluence page preview", "\n".join(lines))

    def _on_publish_api(self) -> None:
        """Push selected fields to Confluence via REST API."""
        selected = self._collect_selected()
        if not selected:
            QMessageBox.warning(self, "Nothing to publish", "Select at least one field.")
            return
        page_ref = self._page_edit.text().strip()
        if not page_ref:
            QMessageBox.warning(self, "Page required", "Enter the Confluence page URL or ID.")
            return

        # Extract page ID from URL if needed
        page_id = page_ref.split("pageId=")[-1] if "pageId=" in page_ref else page_ref
        try:
            cred = self._service.get_credential(self._acting_user_id, "confluence")
            if not cred:
                QMessageBox.warning(
                    self, "No credentials",
                    "Configure Confluence credentials via Actions → Manage credentials."
                )
                return

            tools = self._service._config.get_tools()
            api_base = tools.get("confluence", {}).get("api", "")
            from core.integrations.confluence import ConfluenceClient
            client = ConfluenceClient(api_base, token=cred.get("token"), username=cred.get("username"))
            html = client.build_release_table_html(self._attrs, self._bag)
            client.append_to_page(page_id, html)

            self._service.advance_step(
                self._lane_id, self._step.id, self._acting_user_id,
                recorded_links=[{"label": "Confluence page", "url": page_ref}],
            )
            self.step_updated.emit()
            QMessageBox.information(self, "Published", "Release table appended to Confluence page.")
        except Exception as e:
            QMessageBox.critical(self, "Publish failed", str(e))

    def _on_open_page(self) -> None:
        """Open the Confluence page in the user's browser (Tier 3 fallback)."""
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        page_ref = self._page_edit.text().strip() or self._attrs.get("confluence_page", "")
        if not page_ref:
            QMessageBox.warning(self, "No page", "Enter or configure a Confluence page URL.")
            return
        QDesktopServices.openUrl(QUrl(page_ref))
        QMessageBox.information(
            self, "Opened in browser",
            "Confluence page opened. Click 'Mark Done' once you have updated the page."
        )

    def _on_mark_done(self) -> None:
        try:
            self._service.advance_step(
                self._lane_id, self._step.id, self._acting_user_id,
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
