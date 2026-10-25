"""App shell: home page with four launch tiles + in-app page stack."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from deskhub.theme import TILE_QSS_BASE, ACCENT, BORDER, CARD, CARD_HOVER


class TileButton(QPushButton):
    def __init__(self, icon: str, title: str, desc: str, accent: str = ACCENT):
        super().__init__()
        self.setObjectName("tile")
        self.setAccessibleName(title)
        self.setStyleSheet(TILE_QSS_BASE % {
            "card": CARD, "border": BORDER, "hover": CARD_HOVER, "accent": accent})
        grid = QVBoxLayout(self)
        grid.setSpacing(6)
        ic = QLabel(icon)
        ic.setStyleSheet("font-size: 34px; background: transparent; border: none;")
        t = QLabel(title)
        t.setStyleSheet("font-size: 18px; font-weight: 600; background: transparent; border: none;")
        d = QLabel(desc)
        d.setWordWrap(True)
        d.setStyleSheet("color: #5F5F5F; background: transparent; border: none;")
        for w in (ic, t, d):
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            grid.addWidget(w, alignment=Qt.AlignmentFlag.AlignLeft)
        grid.addStretch(1)
        self.setMinimumHeight(150)


class HomePage(QWidget):
    def __init__(self, launchers: dict[str, callable], accent=ACCENT):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(36, 28, 36, 28)
        lay.setSpacing(8)
        title = QLabel("DeskHub")
        title.setProperty("role", "title")
        sub = QLabel("Downloads · Games · AI Studio · Office — all on your machine.")
        sub.setProperty("role", "subtitle")
        lay.addWidget(title)
        lay.addWidget(sub)
        lay.addSpacing(12)
        row1 = QHBoxLayout()
        row1.setSpacing(16)
        row2 = QHBoxLayout()
        row2.setSpacing(16)
        specs = [
            ("downloads", "⬇", "Downloads", "Torrent downloader with magnet links, pause/resume and progress."),
            ("games", "🎮", "Games", "Minesweeper, Sudoku and Memory Match — fully offline, no accounts."),
            ("ai_studio", "🤖", "AI Studio", "Run local GGUF language models you downloaded yourself."),
            ("office", "📄", "Office", "Lightweight text, spreadsheet and presentation editors."),
        ]
        made = []
        for key, icon, name, desc in specs:
            tile = TileButton(icon, name, desc, accent)
            tile.clicked.connect(lambda _=False, k=key: launchers[k]())
            made.append(tile)
        row1.addWidget(made[0]); row1.addWidget(made[1])
        row2.addWidget(made[2]); row2.addWidget(made[3])
        lay.addLayout(row1)
        lay.addLayout(row2)
        lay.addStretch(1)
        hint = QLabel("Tip: press Alt+1…Alt+4 to jump between tools, Esc to return home.")
        hint.setStyleSheet("color:#5F5F5F;")
        lay.addWidget(hint)


class Shell(QStackedWidget):
    """Central widget managing home + feature pages."""

    def __init__(self, window_title_cb):
        super().__init__()
        self._window_title_cb = window_title_cb
        self.pages: dict[str, QWidget] = {}
        self.home = None  # set by app.py after features register

    def add_page(self, key: str, widget: QWidget, title: str):
        self.pages[key] = widget
        self.insertWidget(len(self.pages), widget)
        widget.setProperty("page_title", title)

    def go_home(self):
        if self.home is not None:
            self.setCurrentWidget(self.home)
            self._window_title_cb("DeskHub")

    def open_feature(self, key: str):
        w = self.pages.get(key)
        if w is not None:
            self.setCurrentWidget(w)
            self._window_title_cb(f"DeskHub — {w.property('page_title')}")
            if hasattr(w, "on_shown"):
                w.on_shown()

    def bind_shortcuts(self, win):
        keys = ["downloads", "games", "ai_studio", "office"]
        for i, k in enumerate(keys, start=1):
            sc = QShortcut(QKeySequence(f"Alt+{i}"), win)
            sc.activated.connect(lambda kk=k: self.open_feature(kk))
        esc = QShortcut(QKeySequence(Qt.Key.Key_Escape), win)
        esc.setContext(Qt.ShortcutContext.ApplicationShortcut)
        esc.activated.connect(self.go_home)
