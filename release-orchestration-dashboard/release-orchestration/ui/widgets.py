from __future__ import annotations

from PySide6.QtWidgets import QPushButton

# Inline styles — guaranteed to override Windows platform style bleed-through.
# QSS property selectors are unreliable inside QFrame/QWidget containers on Windows.

_STYLES: dict[str, str] = {
    "primary": (
        "QPushButton {"
        "  background-color: #4f6af5; color: #ffffff;"
        "  border: none; border-radius: 6px;"
        "  padding: 6px 16px; font-weight: 600; font-size: 12px; min-width: 64px;"
        "}"
        "QPushButton:hover   { background-color: #3d57e0; }"
        "QPushButton:pressed { background-color: #2d43c8; }"
        "QPushButton:disabled { background-color: #c5cad6; color: #8e96a8; }"
    ),
    "ghost": (
        "QPushButton {"
        "  background-color: transparent; color: #4f6af5;"
        "  border: 1px solid #cbd2e8; border-radius: 6px;"
        "  padding: 6px 16px; font-weight: 600; font-size: 12px; min-width: 64px;"
        "}"
        "QPushButton:hover { background-color: #eef1fd; border-color: #4f6af5; }"
        "QPushButton:pressed { background-color: #dde4fb; }"
        "QPushButton:disabled { color: #9ba3b8; border-color: #dde1ee; }"
    ),
    "danger": (
        "QPushButton {"
        "  background-color: #e53935; color: #ffffff;"
        "  border: none; border-radius: 6px;"
        "  padding: 6px 16px; font-weight: 600; font-size: 12px; min-width: 64px;"
        "}"
        "QPushButton:hover   { background-color: #c62828; }"
        "QPushButton:pressed { background-color: #b71c1c; }"
    ),
    "flat": (
        "QPushButton {"
        "  background-color: transparent; color: #4f6af5;"
        "  border: none; border-radius: 4px;"
        "  padding: 4px 8px; font-weight: 600; font-size: 12px; min-width: 0;"
        "}"
        "QPushButton:hover { background-color: #eef1fd; }"
    ),
}


def btn(text: str, style: str = "primary", tooltip: str = "") -> QPushButton:
    """Create a QPushButton with an inline stylesheet that cannot be overridden."""
    b = QPushButton(text)
    b.setStyleSheet(_STYLES[style])
    if tooltip:
        b.setToolTip(tooltip)
    return b
