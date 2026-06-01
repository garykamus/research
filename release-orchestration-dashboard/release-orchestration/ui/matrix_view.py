from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QSizePolicy,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from ui.widgets import btn as _btn

if TYPE_CHECKING:
    from core.models import Lane, LaneDetail
    from core.service import ReleaseService

_STATUS_COLORS: dict[str, str] = {
    "PENDING":     "#d0d5e8",
    "IN_PROGRESS": "#4f6af5",
    "DONE":        "#22a85a",
    "WAITING":     "#e08c00",
    "SUSPENDED":   "#9ba3b8",
    "BLOCKED":     "#e53935",
    "SKIPPED":     "#e4e8f2",
}

_LANE_STATUS_STYLE: dict[str, tuple[str, str]] = {
    "ACTIVE":    ("#e8f5e9", "#1b6e38"),
    "WAITING":   ("#fff8e1", "#a05a00"),
    "SUSPENDED": ("#f0f0f0", "#5a6278"),
    "BLOCKED":   ("#ffebee", "#c62828"),
    "DONE":      ("#e8f0fe", "#3b54d4"),
    "CANCELLED": ("#f5f5f5", "#888888"),
}

_COL_MARKET   = 0
_COL_PACKAGE  = 1
_COL_PROGRESS = 2
_COL_STATUS   = 3
_COL_JIRA     = 4
_COL_OWNER    = 5


class ProgressDelegate(QStyledItemDelegate):
    """
    Draws a segmented pill bar (one segment per step) plus a text summary
    below it.  All rendering happens in paint(); sizeHint gives 56px rows.
    """

    _SEG_GAP = 2
    _BAR_H   = 7
    _RADIUS  = 3

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        data = index.data(Qt.ItemDataRole.UserRole)
        if not data:
            super().paint(painter, option, index)
            return

        statuses: list[str] = data.get("statuses", [])
        label: str           = data.get("label", "")
        if not statuses:
            super().paint(painter, option, index)
            return

        # Draw cell background (handles alternating rows, selection, hover)
        super().paint(painter, option, index)

        painter.save()

        r = option.rect
        pad_x, pad_y = 10, 8

        bar_top = r.top() + pad_y
        bar_w   = r.width() - pad_x * 2
        n       = len(statuses)
        seg_w   = max(1, (bar_w - self._SEG_GAP * (n - 1)) / n)

        for i, status in enumerate(statuses):
            color = QColor(_STATUS_COLORS.get(status, "#d0d5e8"))
            x = int(r.left() + pad_x + i * (seg_w + self._SEG_GAP))
            w = max(1, int(seg_w))
            # Round caps on first and last segment
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(x, bar_top, w, self._BAR_H, self._RADIUS, self._RADIUS)

        # Summary text below bar
        if label:
            painter.setPen(QPen(QColor("#6b7490")))
            font = painter.font()
            font.setPointSize(9)
            painter.setFont(font)
            painter.drawText(
                r.left() + pad_x,
                bar_top + self._BAR_H + 3,
                bar_w,
                r.height() - pad_y - self._BAR_H - 3,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                label,
            )

        painter.restore()

    def sizeHint(self, option, index) -> QSize:
        return QSize(220, 52)


class StatusBadgeDelegate(QStyledItemDelegate):
    """Renders the Status column as a coloured pill."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        status = index.data(Qt.ItemDataRole.DisplayRole) or ""
        bg, fg = _LANE_STATUS_STYLE.get(status.upper(), ("#f0f0f0", "#555"))

        # Draw cell background first
        super().paint(painter, option, index)

        painter.save()

        r = option.rect
        pad_x, pad_y = 10, 10
        pill_w = min(r.width() - pad_x * 2, 90)
        pill_h = r.height() - pad_y * 2
        pill_x = r.left() + pad_x
        pill_y = r.top() + pad_y

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(bg))
        painter.drawRoundedRect(pill_x, pill_y, pill_w, pill_h, 4, 4)

        painter.setPen(QPen(QColor(fg)))
        font = painter.font()
        font.setPointSize(9)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(
            pill_x, pill_y, pill_w, pill_h,
            Qt.AlignmentFlag.AlignCenter,
            status,
        )
        painter.restore()


class MatrixView(QWidget):
    lane_selected = Signal(str)

    def __init__(self, service: ReleaseService, acting_user_id: str, parent=None) -> None:
        super().__init__(parent)
        self._service = service
        self._acting_user_id = acting_user_id
        self._filter_text = ""
        self._lane_ids: list[str] = []
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(300)
        self._filter_timer.timeout.connect(self.refresh)
        self._build_ui()
        self.refresh()

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        # ── Top header bar ──
        header = QHBoxLayout()
        header.setSpacing(10)

        title = QLabel("Release Orchestration")
        title.setStyleSheet("font-size:20px; font-weight:700; color:#1e2433;")
        header.addWidget(title)
        header.addStretch()

        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("  🔍  Filter lanes…")
        self._filter_edit.setMinimumWidth(200)
        self._filter_edit.setMaximumWidth(260)
        self._filter_edit.textChanged.connect(self._on_filter_changed)
        header.addWidget(self._filter_edit)

        new_lane_btn = _btn("+ New Lane", "primary")
        new_lane_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        new_lane_btn.clicked.connect(self._on_new_lane)
        header.addWidget(new_lane_btn)

        creds_btn = _btn("🔑  Credentials", "ghost")
        creds_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        creds_btn.clicked.connect(self._on_credentials)
        header.addWidget(creds_btn)

        root.addLayout(header)

        # ── Legend strip ──
        root.addWidget(self._build_legend())

        # ── Table ──
        self._table = QTableWidget()
        self._table.setColumnCount(6)
        self._table.setHorizontalHeaderLabels(
            ["Market", "ARCAD Package", "Progress", "Status", "Jira", "Owner"]
        )
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(_COL_PROGRESS, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(_COL_PACKAGE,  QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(_COL_MARKET,   QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(_COL_STATUS,   QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(_COL_JIRA,     QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(_COL_OWNER,    QHeaderView.ResizeMode.ResizeToContents)

        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(False)

        # Single click opens lane
        self._table.cellClicked.connect(self._on_row_clicked)
        # Right-click context menu
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_context_menu)

        self._table.setItemDelegateForColumn(_COL_PROGRESS, ProgressDelegate())
        self._table.setItemDelegateForColumn(_COL_STATUS, StatusBadgeDelegate())

        root.addWidget(self._table)

    @staticmethod
    def _build_legend() -> QWidget:
        frame = QWidget()
        frame.setStyleSheet(
            "background:#ffffff; border:1px solid #e4e8f2; border-radius:6px; padding:4px 8px;"
        )
        row = QHBoxLayout(frame)
        row.setContentsMargins(8, 4, 8, 4)
        row.setSpacing(16)
        items = [
            ("Pending",     "#d0d5e8"),
            ("In Progress", "#4f6af5"),
            ("Done",        "#22a85a"),
            ("Waiting",     "#e08c00"),
            ("Suspended",   "#9ba3b8"),
            ("Blocked",     "#e53935"),
        ]
        for label, color in items:
            dot = QLabel("●")
            dot.setStyleSheet(f"color:{color}; font-size:11px;")
            lbl = QLabel(label)
            lbl.setStyleSheet("font-size:11px; color:#6b7490;")
            row.addWidget(dot)
            row.addWidget(lbl)
        row.addStretch()
        return frame

    # ── Refresh ───────────────────────────────────────────────────────────────

    def refresh(self) -> None:
        lanes = self._service.list_lanes()
        if self._filter_text:
            q = self._filter_text.lower()
            lanes = [
                l for l in lanes
                if q in l.market.lower()
                or q in l.arcad_package.lower()
                or q in l.status.lower()
            ]

        self._table.setRowCount(len(lanes))
        self._lane_ids = []

        for row, lane in enumerate(lanes):
            self._lane_ids.append(lane.id)
            detail = self._service.get_lane_detail(lane.id)
            statuses = [s.status for s in detail.steps]
            done = sum(1 for s in statuses if s == "DONE")
            total = len(statuses)
            status_label = lane.status

            self._table.setItem(row, _COL_MARKET,  QTableWidgetItem(lane.market))
            self._table.setItem(row, _COL_PACKAGE, QTableWidgetItem(lane.arcad_package))

            progress_item = QTableWidgetItem()
            progress_item.setData(Qt.ItemDataRole.UserRole, {
                "statuses": statuses,
                "label": f"{done} / {total}  ·  {status_label.capitalize()}"
                         + (f"  ·  {lane.current_step_id}" if lane.current_step_id and lane.status not in ("DONE", "CANCELLED") else ""),
            })
            self._table.setItem(row, _COL_PROGRESS, progress_item)
            self._table.setRowHeight(row, 52)

            status_item = QTableWidgetItem(lane.status)
            self._table.setItem(row, _COL_STATUS, status_item)

            attrs = detail.attributes
            self._table.setItem(row, _COL_JIRA,  QTableWidgetItem(attrs.get("jira_id", "")))
            self._table.setItem(row, _COL_OWNER, QTableWidgetItem(attrs.get("owner", "")))

    # ── Interaction ───────────────────────────────────────────────────────────

    def _on_filter_changed(self, text: str) -> None:
        self._filter_text = text
        self._filter_timer.start()  # restarts if already running

    def _on_row_clicked(self, row: int, _col: int) -> None:
        if 0 <= row < len(self._lane_ids):
            self.lane_selected.emit(self._lane_ids[row])

    def _on_context_menu(self, pos) -> None:
        row = self._table.rowAt(pos.y())
        if row < 0 or row >= len(self._lane_ids):
            return
        lane_id = self._lane_ids[row]
        menu = QMenu(self)
        open_act    = menu.addAction("Open lane")
        menu.addSeparator()
        delete_act  = menu.addAction("🗑  Delete lane…")
        chosen = menu.exec(self._table.viewport().mapToGlobal(pos))
        if chosen == open_act:
            self.lane_selected.emit(lane_id)
        elif chosen == delete_act:
            self._delete_lane(lane_id)

    def _delete_lane(self, lane_id: str) -> None:
        try:
            lane = self._service.get_lane(lane_id)
        except Exception:
            return
        reply = QMessageBox.question(
            self,
            "Delete lane",
            f"Delete lane <b>{lane.market} / {lane.arcad_package}</b>?<br><br>"
            "All steps, audit history and recorded values will be removed permanently.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                self._service.delete_lane(lane_id, self._acting_user_id)
                self.refresh()
            except Exception as e:
                QMessageBox.critical(self, "Delete failed", str(e))

    def _on_new_lane(self) -> None:
        from PySide6.QtWidgets import QDialog
        from ui.dialogs.new_lane_dialog import NewLaneDialog
        dlg = NewLaneDialog(self._service, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            vals = dlg.get_values()
            try:
                self._service.create_lane(
                    market=vals["market"],
                    arcad_package=vals["arcad_package"],
                    owner_user_id=self._acting_user_id,
                    jira_id=vals["jira_id"],
                    confluence_page=vals["confluence_page"],
                    created_by_user_id=self._acting_user_id,
                    skip_steps=vals.get("skip_steps"),
                )
                self.refresh()
            except Exception as e:
                QMessageBox.critical(self, "Error creating lane", str(e))

    def _on_credentials(self) -> None:
        from PySide6.QtWidgets import QDialog
        from ui.dialogs.credential_dialog import CredentialManagerDialog
        dlg = CredentialManagerDialog(self._service, self._acting_user_id, parent=self)
        dlg.exec()
