from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDateTimeEdit,
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


class CrCreationView(QWidget):
    """
    Custom view for the create_cr step (ServiceNow CR creation).

    Renders configurable fields from view_config.fields (base + per-market
    extra_fields via override), validates required fields, then:
    - If servicenow_tier == rest: fires fire_step() which calls the SNOW API.
    - If servicenow_tier == deep_link: opens a pre-filled SNOW URL in the
      user's browser (no password stored); user pastes back the CR number.

    Captures cr_no and cr_url into the value bag on success.
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

    def _snow_tier(self) -> str:
        """Resolve servicenow_tier from lane's market config."""
        try:
            attrs = self._service.get_lane_detail(self._lane_id).attributes
            market = attrs.get("market", "")
            binding = self._service._config.get_market_binding(market)
            tools = self._service._config.get_tools()
            # Per-market override takes priority; fallback to tools.yaml
            tier = binding.get("servicenow_tier",
                               tools.get("servicenow", {}).get("fallback", "deep_link"))
            return tier
        except Exception:
            return "deep_link"

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(12, 10, 12, 10)

        tier = self._snow_tier()

        # Already-captured banner
        if self._bag.get("cr_no"):
            done_lbl = QLabel(f"✓  CR recorded: <b>{self._bag['cr_no']}</b>")
            done_lbl.setStyleSheet(
                "background:#e8f5e9; color:#1b6e38; border-radius:6px;"
                "padding:6px 10px; font-size:12px;"
            )
            layout.addWidget(done_lbl)

        # Mode indicator
        mode_txt = "REST API (automated)" if tier == "rest" else "Deep link — fill in browser, paste back"
        mode_lbl = QLabel(f"Mode: <b>{mode_txt}</b>")
        mode_lbl.setStyleSheet("color:#6b7490; font-size:11px;")
        layout.addWidget(mode_lbl)

        # CR fields
        group = QGroupBox("Change Request details")
        form = QFormLayout(group)
        form.setSpacing(6)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        fields = self._step.view_config.get("fields", [])
        for field_def in fields:
            widget = self._make_field_widget(field_def)
            self._field_widgets[field_def["key"]] = widget
            label_txt = field_def.get("label", field_def["key"])
            if field_def.get("required"):
                label_txt = f'<span style="color:#e53935;">*</span> {label_txt}'
            lbl = QLabel(label_txt)
            lbl.setTextFormat(Qt.TextFormat.RichText)
            form.addRow(lbl, widget)

        layout.addWidget(group)

        # Action buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        if tier == "rest":
            create_btn = _btn("▶  Create CR via API", "primary")
            create_btn.clicked.connect(self._on_create_api)
            btn_row.addWidget(create_btn)
        else:
            open_btn = _btn("🔗  Open ServiceNow", "primary",
                            "Opens a pre-filled ServiceNow URL in your browser")
            open_btn.clicked.connect(self._on_open_deep_link)
            btn_row.addWidget(open_btn)

            paste_btn = _btn("⌨  Paste CR number", "ghost",
                             "After creating the CR in your browser, record the number here")
            paste_btn.clicked.connect(self._on_paste_cr)
            btn_row.addWidget(paste_btn)

        mark_done_btn = _btn("✓  Mark Done", "ghost",
                             "Mark this step complete (use only if CR is already recorded)")
        mark_done_btn.clicked.connect(self._on_mark_done)
        btn_row.addWidget(mark_done_btn)

        override_btn = _btn("Override", "ghost")
        override_btn.clicked.connect(self._on_override)
        btn_row.addWidget(override_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)

        if self._step.override:
            ov = QLabel(
                f'Override: {self._step.override.value} — "{self._step.override.reason}"'
            )
            ov.setStyleSheet(
                "background:#fff4e5; color:#a05a00; border-radius:4px;"
                "padding:4px 8px; font-size:11px;"
            )
            ov.setWordWrap(True)
            layout.addWidget(ov)

    def _make_field_widget(self, field_def: dict) -> QWidget:
        ftype = field_def.get("type", "text")
        key = field_def["key"]
        current = self._bag.get(key, "")
        if ftype == "datetime":
            w = QDateTimeEdit()
            w.setCalendarPopup(True)
            return w
        elif ftype == "dropdown":
            w = QComboBox()
            for opt in field_def.get("options", []):
                w.addItem(str(opt))
            if current:
                idx = w.findText(current)
                if idx >= 0:
                    w.setCurrentIndex(idx)
            return w
        else:
            w = QLineEdit(current)
            w.setPlaceholderText(field_def.get("label", key))
            return w

    def _collect_field_values(self) -> dict[str, str]:
        values: dict[str, str] = {}
        for key, widget in self._field_widgets.items():
            if isinstance(widget, QLineEdit):
                val = widget.text().strip()
            elif isinstance(widget, QComboBox):
                val = widget.currentText()
            elif isinstance(widget, QDateTimeEdit):
                val = widget.dateTime().toString("yyyy-MM-ddTHH:mm:ss")
            else:
                val = ""
            if val:
                values[key] = val
        return values

    def _validate_required(self) -> bool:
        fields = self._step.view_config.get("fields", [])
        missing = []
        for f in fields:
            if f.get("required"):
                widget = self._field_widgets.get(f["key"])
                val = ""
                if isinstance(widget, QLineEdit):
                    val = widget.text().strip()
                elif isinstance(widget, QComboBox):
                    val = widget.currentText()
                if not val:
                    missing.append(f.get("label", f["key"]))
        if missing:
            QMessageBox.warning(self, "Required fields", "Required: " + ", ".join(missing))
            return False
        return True

    def _on_create_api(self) -> None:
        if not self._validate_required():
            return
        field_values = self._collect_field_values()
        try:
            self._service.fire_step(self._lane_id, self._step.id, self._acting_user_id)
            if field_values:
                self._service.advance_step(
                    self._lane_id, self._step.id, self._acting_user_id,
                    recorded_values=field_values,
                )
            self.step_updated.emit()
        except Exception as e:
            QMessageBox.critical(self, "CR creation failed", str(e))

    def _on_open_deep_link(self) -> None:
        """Build a pre-filled ServiceNow URL and open it in the system browser."""
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        try:
            attrs = self._service.get_lane_detail(self._lane_id).attributes
            market = attrs.get("market", "")
            binding = self._service._config.get_market_binding(market)
            tools = self._service._config.get_tools()
            snow_base = tools.get("servicenow", {}).get("base", "")
            if not snow_base:
                # Try to extract from api URL
                api_url = tools.get("servicenow", {}).get("api", "")
                snow_base = api_url.split("/api/")[0] if "/api/" in api_url else api_url

            from core.integrations.servicenow import ServiceNowClient
            fields = self._collect_field_values()
            # Seed with lane context
            fields.setdefault("short_description",
                f"Release {attrs.get('arcad_package','')} to {market}")
            url = ServiceNowClient.build_deep_link(snow_base, fields)
            QDesktopServices.openUrl(QUrl(url))
            QMessageBox.information(
                self, "Opened in browser",
                "ServiceNow opened in your browser.\n"
                "After creating the CR, use 'Paste CR number' to record it here."
            )
        except Exception as e:
            QMessageBox.warning(self, "Deep link error", str(e))

    def _on_paste_cr(self) -> None:
        """User pastes the CR number and optionally CR URL after manual creation."""
        from PySide6.QtWidgets import QDialog, QDialogButtonBox
        dlg = QDialog(self)
        dlg.setWindowTitle("Record CR details")
        lay = QVBoxLayout(dlg)
        form = QFormLayout()
        cr_no_edit = QLineEdit()
        cr_no_edit.setPlaceholderText("e.g. CHG0012345")
        cr_url_edit = QLineEdit()
        cr_url_edit.setPlaceholderText("https://snow.example.com/now/change/CHG0012345")
        form.addRow("CR Number *:", cr_no_edit)
        form.addRow("CR URL:", cr_url_edit)
        lay.addLayout(form)
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        lay.addWidget(btns)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            cr_no = cr_no_edit.text().strip()
            cr_url = cr_url_edit.text().strip()
            if not cr_no:
                QMessageBox.warning(self, "Validation", "CR Number is required.")
                return
            recorded = {"cr_no": cr_no}
            if cr_url:
                recorded["cr_url"] = cr_url
            try:
                self._service.advance_step(
                    self._lane_id, self._step.id, self._acting_user_id,
                    recorded_values=recorded,
                )
                self.step_updated.emit()
            except Exception as e:
                QMessageBox.critical(self, "Error", str(e))

    def _on_mark_done(self) -> None:
        field_values = self._collect_field_values()
        try:
            self._service.advance_step(
                self._lane_id, self._step.id, self._acting_user_id,
                recorded_values=field_values if field_values else None,
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
