from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)

if TYPE_CHECKING:
    from core.service import ReleaseService

_CREATION_STEP_ID = "create_arcad_package"


class NewLaneDialog(QDialog):
    """
    Create a new release lane.

    The checkbox "Package already exists" controls whether the
    create_arcad_package step is pre-skipped at lane creation (Approach B):
    - Checked  → skip that step; lane starts at create_pr.
    - Unchecked → keep that step; user triggers or manually marks it done.

    The checkbox is only shown when the market's resolved template includes
    the create_arcad_package step.
    """

    def __init__(self, service: ReleaseService, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("New Release Lane")
        self.setMinimumWidth(440)
        self._service = service
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        title = QLabel("Create a new release lane")
        title.setStyleSheet("font-size: 15px; font-weight: bold;")
        layout.addWidget(title)

        form = QFormLayout()
        form.setSpacing(8)

        self._market_combo = QComboBox()
        markets = self._service.get_config_summary().markets
        for m in markets:
            self._market_combo.addItem(m)
        self._market_combo.currentTextChanged.connect(self._on_market_changed)
        form.addRow("Market:", self._market_combo)

        self._package_edit = QLineEdit()
        self._package_edit.setPlaceholderText("e.g. hotfix-3309")
        form.addRow("ARCAD package name:", self._package_edit)

        self._owner_edit = QLineEdit()
        form.addRow("Owner:", self._owner_edit)

        self._jira_edit = QLineEdit()
        self._jira_edit.setPlaceholderText("e.g. PROJ-1234")
        form.addRow("Jira ID:", self._jira_edit)

        self._confluence_edit = QLineEdit()
        self._confluence_edit.setPlaceholderText("https://confluence/...")
        form.addRow("Confluence page:", self._confluence_edit)

        layout.addLayout(form)

        # Package-existence checkbox — shown only when the template has the
        # create_arcad_package step.
        self._pkg_exists_cb = QCheckBox("Package already exists (skip creation step)")
        self._pkg_exists_cb.setChecked(True)
        self._pkg_exists_cb.setToolTip(
            "Checked: lane starts at Create PR — the ARCAD package and branch\n"
            "already exist in your environment.\n\n"
            "Unchecked: lane starts at Create ARCAD package — use this when\n"
            "you need the dashboard to trigger or record package creation."
        )
        self._pkg_exists_row = self._pkg_exists_cb  # keep ref for show/hide
        layout.addWidget(self._pkg_exists_cb)

        self._btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._btn_box.accepted.connect(self._on_accept)
        self._btn_box.rejected.connect(self.reject)
        layout.addWidget(self._btn_box)

        self._on_market_changed(self._market_combo.currentText())

    def _template_has_creation_step(self, market: str) -> bool:
        """Returns True if the market's resolved template includes create_arcad_package."""
        try:
            from core.config.resolver import LaneResolver
            resolver = LaneResolver(self._service._config)
            steps = resolver.resolve(market, {})
            return any(s["_step_id"] == _CREATION_STEP_ID for s in steps)
        except Exception:
            return False

    def _on_market_changed(self, market: str) -> None:
        try:
            binding = self._service._config.get_market_binding(market)
            self._owner_edit.setText(binding.get("default_owner", ""))
        except Exception:
            pass
        has_creation = self._template_has_creation_step(market)
        self._pkg_exists_cb.setVisible(has_creation)

    def _on_accept(self) -> None:
        if not self._package_edit.text().strip():
            QMessageBox.warning(self, "Validation", "ARCAD package name is required.")
            return
        if not self._jira_edit.text().strip():
            QMessageBox.warning(self, "Validation", "Jira ID is required.")
            return
        self.accept()

    def get_values(self) -> dict:
        """
        Returns creation values. skip_steps is non-empty when the user checked
        "Package already exists".
        """
        market = self._market_combo.currentText()
        skip: list[str] = []
        if self._pkg_exists_cb.isVisible() and self._pkg_exists_cb.isChecked():
            skip = [_CREATION_STEP_ID]
        return {
            "market": market,
            "arcad_package": self._package_edit.text().strip(),
            "owner": self._owner_edit.text().strip(),
            "jira_id": self._jira_edit.text().strip(),
            "confluence_page": self._confluence_edit.text().strip(),
            "skip_steps": skip,
        }
