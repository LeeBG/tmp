"""GUI 스타일 (Qt 스타일시트)."""

from __future__ import annotations

PINK = "#e8547f"
PINK_DARK = "#c93f68"
PINK_SOFT = "#fde7ee"
INK = "#2b2130"
MUTED = "#8a7f90"

STYLESHEET = f"""
QWidget {{
    background: #fff8fa;
    color: {INK};
    font-family: "Malgun Gothic", "맑은 고딕", "Noto Sans CJK KR", sans-serif;
    font-size: 13px;
}}
QLabel#title {{
    font-size: 26px;
    font-weight: 700;
    color: {PINK_DARK};
}}
QLabel#subtitle {{
    color: {MUTED};
    font-size: 12px;
}}
QLabel#sectionTitle {{
    font-weight: 700;
    color: {PINK_DARK};
    padding-top: 4px;
}}
QFrame#card {{
    background: #ffffff;
    border: 1px solid #f3d7e1;
    border-radius: 12px;
}}
QFrame#statusCard {{
    background: {PINK_SOFT};
    border: 1px solid #f6c3d5;
    border-radius: 12px;
}}
QLabel#statusTitle {{
    color: {PINK_DARK};
    font-weight: 700;
}}
QLabel#statusDetail {{
    color: {MUTED};
    font-size: 11px;
}}
QTabWidget::pane {{
    border: 1px solid #f3d7e1;
    border-radius: 10px;
    background: #ffffff;
    top: -1px;
}}
QTabBar::tab {{
    background: #fdeff4;
    color: {MUTED};
    padding: 7px 18px;
    margin-right: 4px;
    border-top-left-radius: 10px;
    border-top-right-radius: 10px;
}}
QTabBar::tab:selected {{
    background: {PINK};
    color: #ffffff;
    font-weight: 700;
}}
QPushButton {{
    background: #ffffff;
    border: 1px solid #edc9d8;
    border-radius: 8px;
    padding: 7px 14px;
}}
QPushButton:hover {{ background: {PINK_SOFT}; }}
QPushButton:disabled {{ color: #c4bcc9; background: #f7f2f5; }}
QPushButton#primary {{
    background: {PINK};
    color: #ffffff;
    border: none;
    font-weight: 700;
    padding: 11px 18px;
    font-size: 14px;
}}
QPushButton#primary:hover {{ background: {PINK_DARK}; }}
QPushButton#primary:disabled {{ background: #f0c3d3; color: #ffffff; }}
QPushButton#secondary {{
    background: #f4eef1;
    color: {INK};
    border: 1px solid #e6d4dc;
    font-weight: 700;
    padding: 11px 18px;
    font-size: 14px;
}}
QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {{
    background: #ffffff;
    border: 1px solid #e7cfd9;
    border-radius: 7px;
    padding: 4px 8px;
    min-height: 22px;
}}
QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QLineEdit:focus {{
    border: 1px solid {PINK};
}}
QComboBox QAbstractItemView {{
    background: #ffffff;
    selection-background-color: {PINK_SOFT};
    selection-color: {INK};
}}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border: 1px solid #dfc4d0;
    border-radius: 4px;
    background: #ffffff;
}}
QCheckBox::indicator:checked {{
    background: {PINK};
    border: 1px solid {PINK_DARK};
}}
QPlainTextEdit#log {{
    background: #2a1f2a;
    color: #ffd9e6;
    border: 1px solid #d9b7c5;
    border-radius: 10px;
    font-family: Consolas, "D2Coding", monospace;
    font-size: 12px;
}}
QGroupBox {{
    border: 1px solid #f0d5e0;
    border-radius: 10px;
    margin-top: 14px;
    padding-top: 10px;
    font-weight: 700;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: {PINK_DARK};
}}
QScrollBar:vertical {{
    background: transparent; width: 10px; margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: #edc9d8; border-radius: 5px; min-height: 30px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
"""

LEVEL_COLORS = {
    "debug": "#9c8fa6",
    "info": "#ffd9e6",
    "ok": "#8ce0a8",
    "warn": "#ffd479",
    "error": "#ff8f9e",
}
