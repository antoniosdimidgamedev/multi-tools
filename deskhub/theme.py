"""Windows 11-ish Fluent styling for Qt Widgets.

Mica-like layered background, rounded cards, Segoe UI Variable font,
accent colour from settings. Kept intentionally simple so it is easy to
tune and so contrast stays accessible (WCAG AA on body text).
"""
from __future__ import annotations

ACCENT = "#0078D4"

BG = "#F3F3F3"
CARD = "#FFFFFF"
CARD_HOVER = "#F9F9F9"
TEXT = "#1A1A1A"
SUBTLE = "#5F5F5F"
BORDER = "#E0E0E0"


def stylesheet(accent: str = ACCENT) -> str:
    return f"""
    QWidget {{
        font-family: "Segoe UI Variable Text", "Segoe UI", sans-serif;
        font-size: 14px;
        color: {TEXT};
        background: {BG};
    }}
    QMainWindow, QDialog {{ background: {BG}; }}
    QLabel[role="title"] {{ font-size: 28px; font-weight: 600; }}
    QLabel[role="subtitle"] {{ color: {SUBTLE}; }}
    QPushButton {{
        background: {CARD}; border: 1px solid {BORDER}; border-radius: 6px;
        padding: 7px 14px;
    }}
    QPushButton:hover {{ background: {CARD_HOVER}; border-color: #C8C8C8; }}
    QPushButton:pressed {{ background: #EDEDED; color: {SUBTLE}; }}
    QPushButton:disabled {{ background: #E8E8E8; color: #9A9A9A; }}
    QPushButton[role="accent"] {{
        background: {accent}; color: white; border: none; font-weight: 600;
    }}
    QPushButton[role="accent"]:hover {{ background: {accent}E6; }}
    QPushButton[role="accent"]:disabled {{ background: #B8D8EE; color: #F0F0F0; }}
    QToolButton {{ background: transparent; border: none; border-radius: 6px; padding: 6px; }}
    QToolButton:hover {{ background: #E4E4E4; }}
    QToolButton:checked {{ background: {accent}22; }}
    QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
        background: {CARD}; border: 1px solid {BORDER}; border-bottom: 1px solid #B0B0B0;
        border-radius: 6px; padding: 6px 10px; selection-background-color: {accent};
        selection-color: white;
    }}
    QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus {{
        border: 1px solid {accent}; border-bottom: 2px solid {accent};
    }}
    QListWidget, QTreeWidget, QTableView, QTableWidget {{
        background: {CARD}; border: 1px solid {BORDER}; border-radius: 6px;
        outline: 0;
    }}
    QListWidget::item, QTableWidget::item {{ padding: 6px; }}
    QListWidget::item:selected, QTableWidget::item:selected {{
        background: {accent}22; color: {TEXT};
    }}
    QProgressBar {{
        border: 1px solid {BORDER}; border-radius: 6px; height: 18px;
        background: {CARD}; text-align: center; color: {TEXT};
    }}
    QProgressBar::chunk {{ background: {accent}; border-radius: 4px; }}
    QScrollBar:vertical {{ background: transparent; width: 12px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: #C4C4C4; border-radius: 5px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: #A0A0A0; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QStatusBar {{ background: transparent; }}
    QMenu {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 8px; padding: 4px; }}
    QMenu::item {{ padding: 6px 24px; border-radius: 4px; }}
    QMenu::item:selected {{ background: {accent}22; }}
    QGroupBox {{
        background: {CARD}; border: 1px solid {BORDER}; border-radius: 8px;
        margin-top: 10px; padding-top: 6px;
    }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; }}
    """


TILE_QSS_BASE = """
QPushButton#tile {{
    background: %(card)s; border: 1px solid %(border)s; border-radius: 10px;
    text-align: left; padding: 18px;
}}
QPushButton#tile:hover { background: %(hover)s; border-color: %(accent)s; }
QPushButton#tile:pressed { background: #EDEDED; }
"""
