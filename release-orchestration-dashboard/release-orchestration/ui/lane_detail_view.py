from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from ui.widgets import btn as _styled_btn

if TYPE_CHECKING:
    from core.models import LaneDetail, StepInstance
    from core.service import ReleaseService

# ── Status display maps ──────────────────────────────────────────────────────

_STATUS_ICONS: dict[str, str] = {
    "PENDING":     "○",
    "IN_PROGRESS": "◐",
    "DONE":        "●",
    "SUSPENDED":   "⏸",
    "BLOCKED":     "✗",
    "SKIPPED":     "—",
    "WAITING":     "◷",
}

_STATUS_COLORS: dict[str, str] = {
    "PENDING":     "#9ba3b8",
    "IN_PROGRESS": "#4f6af5",
    "DONE":        "#22a85a",
    "SUSPENDED":   "#7b8299",
    "BLOCKED":     "#e53935",
    "SKIPPED":     "#b0bace",
    "WAITING":     "#e08c00",
}

_MODE_BG: dict[str, str] = {
    "AUTO":   "#e8f0fe",
    "HYBRID": "#fff4e5",
    "MANUAL": "#f3e8ff",
}
_MODE_FG: dict[str, str] = {
    "AUTO":   "#3b54d4",
    "HYBRID": "#a05a00",
    "MANUAL": "#6b21a8",
}

_LANE_STATUS_BADGE: dict[str, tuple[str, str]] = {
    "ACTIVE":    ("#e8f5e9", "#1b6e38"),
    "WAITING":   ("#fff8e1", "#a05a00"),
    "SUSPENDED": ("#f0f0f0", "#5a6278"),
    "BLOCKED":   ("#ffebee", "#c62828"),
    "DONE":      ("#e8f0fe", "#3b54d4"),
    "CANCELLED": ("#f5f5f5", "#888888"),
}


def _make_badge(text: str, bg: str, fg: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"background:{bg}; color:{fg}; border-radius:4px;"
        f"padding:2px 8px; font-size:11px; font-weight:600;"
    )
    lbl.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    return lbl


# ── Step row ─────────────────────────────────────────────────────────────────

class StepRow(QFrame):
    """One collapsible step row. Click anywhere on the header to expand."""

    step_updated = Signal()

    def __init__(
        self,
        step: StepInstance,
        service: ReleaseService,
        lane_id: str,
        bag: dict[str, str],
        acting_user_id: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._step = step
        self._service = service
        self._lane_id = lane_id
        self._bag = bag
        self._acting_user_id = acting_user_id
        self._expanded = False
        self._expand_widget: QWidget | None = None
        self.setObjectName("stepRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._build_ui()

    # ── Build ────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(12, 8, 12, 8)
        self._outer.setSpacing(0)
        self._outer.addLayout(self._build_collapsed_row())

    def _build_collapsed_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)

        # Status icon
        status = self._step.compute_effective_status()
        icon = QLabel(_STATUS_ICONS.get(self._step.status, "○"))
        color = _STATUS_COLORS.get(self._step.status, "#9ba3b8")
        icon.setStyleSheet(
            f"color:{color}; font-size:15px; min-width:18px; max-width:18px;"
        )
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(icon)

        # Step number
        num = QLabel(f"{self._step.seq_order + 1}.")
        num.setStyleSheet("color:#9ba3b8; min-width:20px; max-width:24px; font-size:11px;")
        row.addWidget(num)

        # Label — fixed width so badges don't get pushed off
        label = QLabel(self._step.label)
        label.setStyleSheet("font-weight:600; font-size:13px;")
        label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        label.setWordWrap(False)
        row.addWidget(label, 1)

        # Mode badge
        bg = _MODE_BG.get(self._step.mode, "#f0f0f0")
        fg = _MODE_FG.get(self._step.mode, "#444")
        row.addWidget(_make_badge(self._step.mode, bg, fg))

        # External hold badge
        if self._step.kind == "external_hold":
            row.addWidget(_make_badge("EXT HOLD", "#e8eaf6", "#3949ab"))

        # Override badge
        if self._step.override:
            row.addWidget(_make_badge("overridden", "#fff4e5", "#a05a00"))

        # Chevron
        self._chevron = QPushButton("›")
        self._chevron.setFlat(True)
        self._chevron.setFixedSize(24, 24)
        self._chevron.setStyleSheet(
            "color:#9ba3b8; font-size:16px; font-weight:700;"
            "background:transparent; border:none; padding:0;"
        )
        self._chevron.clicked.connect(self.toggle_expand)
        row.addWidget(self._chevron)

        return row

    # ── Expand / collapse ────────────────────────────────────────────────────

    def toggle_expand(self) -> None:
        if self._expanded:
            if self._expand_widget:
                self._expand_widget.setVisible(False)
            self._chevron.setText("›")
            self._expanded = False
            self.setObjectName("stepRow")
        else:
            if not self._expand_widget:
                self._expand_widget = self._build_step_view()
                if self._expand_widget:
                    # Separator line
                    sep = QFrame()
                    sep.setFrameShape(QFrame.Shape.HLine)
                    sep.setStyleSheet("color:#e4e8f2; margin: 6px 0 4px 0;")
                    self._outer.addWidget(sep)
                    self._outer.addWidget(self._expand_widget)
            if self._expand_widget:
                self._expand_widget.setVisible(True)
            self._chevron.setText("∨")
            self._expanded = True
            self.setObjectName("stepRowExpanded")
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle_expand()
        super().mousePressEvent(event)

    def _build_step_view(self) -> QWidget | None:
        from ui.stepviews.registry import get_view_class
        if self._step.kind == "external_hold":
            from ui.stepviews.external_hold_view import ExternalHoldView
            v = ExternalHoldView(
                self._step, self._service, self._lane_id,
                self._acting_user_id, parent=self,
            )
            v.step_updated.connect(self.step_updated)
            return v

        view_cls = get_view_class(self._step.view)
        v = view_cls(
            self._step, self._service, self._lane_id,
            self._bag, self._acting_user_id, parent=self,
        )
        if hasattr(v, "step_updated"):
            v.step_updated.connect(self.step_updated)
        return v


# ── Lane detail view ──────────────────────────────────────────────────────────

class LaneDetailView(QWidget):
    back_requested = Signal()

    def __init__(
        self,
        service: ReleaseService,
        lane_id: str,
        acting_user_id: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._lane_id = lane_id
        self._acting_user_id = acting_user_id
        self._build_ui()

    # ── Skeleton ─────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Sticky header panel
        self._header_panel = QWidget()
        self._header_panel.setObjectName("detailHeader")
        self._header_panel.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self._header_layout = QVBoxLayout(self._header_panel)
        self._header_layout.setContentsMargins(16, 10, 16, 10)
        self._header_layout.setSpacing(6)
        outer.addWidget(self._header_panel)

        # Scrollable body
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._body_container = QWidget()
        self._body_container.setStyleSheet("background:#f0f2f7;")
        self._body_layout = QVBoxLayout(self._body_container)
        self._body_layout.setContentsMargins(16, 12, 16, 12)
        self._body_layout.setSpacing(4)
        self._body_layout.addStretch()
        scroll.setWidget(self._body_container)
        outer.addWidget(scroll)

        self.refresh()

    # ── Refresh ───────────────────────────────────────────────────────────────

    def refresh(self) -> None:
        try:
            detail = self._service.get_lane_detail(self._lane_id)
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Cannot load lane: {exc}")
            return
        self._rebuild_header(detail)
        self._rebuild_body(detail)

    # ── Header ────────────────────────────────────────────────────────────────

    def _rebuild_header(self, detail) -> None:
        self._clear_layout(self._header_layout)

        lane = detail.lane
        attrs = detail.attributes

        # ── Row 1: Back · Title · lane-status badge · spacer · Refresh · Actions ──
        row1 = QHBoxLayout()
        row1.setSpacing(8)

        back_btn = _styled_btn("← Back", "flat")
        back_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        back_btn.clicked.connect(self.back_requested)
        row1.addWidget(back_btn)

        # Thin vertical separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet("color:#dde1ee; max-width:1px; margin:2px 4px;")
        row1.addWidget(sep)

        title = QLabel(f"<b>{lane.market}</b>  ·  {lane.arcad_package}")
        title.setStyleSheet("font-size:15px; font-weight:600;")
        title.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        row1.addWidget(title)

        badge_colors = _LANE_STATUS_BADGE.get(lane.status, ("#f0f0f0", "#555"))
        row1.addWidget(_make_badge(lane.status, badge_colors[0], badge_colors[1]))

        row1.addStretch()

        refresh_btn = _styled_btn("⟳  Refresh", "ghost")
        refresh_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        refresh_btn.clicked.connect(self.refresh)
        row1.addWidget(refresh_btn)

        actions_btn = _styled_btn("Actions  ▾", "primary")
        actions_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        actions_btn.clicked.connect(self._show_actions_menu)
        row1.addWidget(actions_btn)

        self._header_layout.addLayout(row1)

        # ── Row 2: progress summary · Jira · Confluence ─────────────────────
        row2 = QHBoxLayout()
        row2.setSpacing(12)

        steps = detail.steps
        done = sum(1 for s in steps if s.status == "DONE")
        total = len(steps)
        skipped = sum(1 for s in steps if s.status == "SKIPPED")

        progress_lbl = QLabel(f"{done}/{total} steps done" + (f"  ·  {skipped} skipped" if skipped else ""))
        progress_lbl.setStyleSheet("color:#6b7490; font-size:12px;")
        row2.addWidget(progress_lbl)

        jira_id = attrs.get("jira_id", "")
        if jira_id:
            row2.addWidget(QLabel("·"))
            jira_lbl = QLabel(f"Jira: <b>{jira_id}</b>")
            jira_lbl.setStyleSheet("color:#4f6af5; font-size:12px;")
            row2.addWidget(jira_lbl)

        conf_page = attrs.get("confluence_page", "")
        if conf_page:
            row2.addWidget(QLabel("·"))
            conf_lbl = QLabel(f'<a href="{conf_page}" style="color:#4f6af5;">Confluence ↗</a>')
            conf_lbl.setOpenExternalLinks(True)
            conf_lbl.setStyleSheet("font-size:12px;")
            row2.addWidget(conf_lbl)

        overrides = sum(1 for s in steps if s.override)
        if overrides:
            row2.addWidget(QLabel("·"))
            ov_lbl = QLabel(f"{overrides} override{'s' if overrides > 1 else ''}")
            ov_lbl.setStyleSheet("color:#a05a00; font-size:12px;")
            row2.addWidget(ov_lbl)

        row2.addStretch()
        self._header_layout.addLayout(row2)

    # ── Body ──────────────────────────────────────────────────────────────────

    def _rebuild_body(self, detail) -> None:
        self._clear_layout(self._body_layout)

        bag = detail.bag
        for i, step in enumerate(detail.steps):
            row = StepRow(
                step, self._service, self._lane_id,
                bag, self._acting_user_id, parent=self,
            )
            row.step_updated.connect(self.refresh)
            self._body_layout.addWidget(row)

            # Connector dot between steps
            if i < len(detail.steps) - 1:
                connector = QLabel("│")
                connector.setStyleSheet(
                    "color:#dde1ee; margin-left:22px; font-size:12px;"
                    "max-height:8px; padding:0;"
                )
                self._body_layout.addWidget(connector)

        self._body_layout.addStretch()

    # ── Actions menu ──────────────────────────────────────────────────────────

    def _show_actions_menu(self) -> None:
        menu = QMenu(self)
        rename_act = menu.addAction("✏  Rename package…")
        rename_act.triggered.connect(self._on_rename)
        menu.addSeparator()
        export_act = menu.addAction("⬇  Export audit log (CSV)…")
        export_act.triggered.connect(self._on_export_audit)
        menu.addSeparator()
        creds_act = menu.addAction("🔑  Manage credentials…")
        creds_act.triggered.connect(self._on_manage_credentials)
        menu.addSeparator()
        delete_act = menu.addAction("🗑  Delete lane…")
        delete_act.triggered.connect(self._on_delete_lane)
        sender = self.sender()
        menu.exec(sender.mapToGlobal(sender.rect().bottomLeft()))

    def _on_rename(self) -> None:
        lane = self._service.get_lane(self._lane_id)
        from ui.dialogs.rename_dialog import RenamePackageDialog
        dlg = RenamePackageDialog(lane.arcad_package, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_name, reason = dlg.get_values()
            try:
                result = self._service.invoke_lane_action(
                    self._lane_id, "rename_package",
                    inputs={"new_name": new_name},
                    reason=reason,
                    acting_user_id=self._acting_user_id,
                )
                if result.success:
                    self.refresh()
                else:
                    QMessageBox.warning(self, "Rename failed", result.message)
            except Exception as e:
                QMessageBox.critical(self, "Error", str(e))

    def _on_export_audit(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            self, "Export audit log", f"audit_{self._lane_id[:8]}.csv", "CSV files (*.csv)"
        )
        if not path:
            return
        try:
            csv_text = self._service.export_audit_csv(self._lane_id)
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(csv_text)
            QMessageBox.information(self, "Exported", f"Audit log saved to:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Export failed", str(e))

    def _on_manage_credentials(self) -> None:
        from ui.dialogs.credential_dialog import CredentialManagerDialog
        dlg = CredentialManagerDialog(self._service, self._acting_user_id, parent=self)
        dlg.exec()

    def _on_delete_lane(self) -> None:
        lane = self._service.get_lane(self._lane_id)
        reply = QMessageBox.question(
            self,
            "Delete lane",
            f"Permanently delete lane <b>{lane.market} / {lane.arcad_package}</b>?<br><br>"
            "This removes all steps, audit history, and recorded values. "
            "This action cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self._service.delete_lane(self._lane_id, self._acting_user_id)
            self.back_requested.emit()
        except Exception as e:
            QMessageBox.critical(self, "Delete failed", str(e))

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _clear_layout(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                LaneDetailView._clear_layout(item.layout())
