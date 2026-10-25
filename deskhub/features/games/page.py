"""Games hub: Minesweeper, Sudoku and Memory Match — all offline."""
from __future__ import annotations

import random
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox, QGridLayout, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QTabWidget, QVBoxLayout, QWidget,
)

from deskhub.features.games.logic import (
    MemoryMatch, Minesweeper, generate_sudoku, is_valid_solution, solve_board,
)
from deskhub.features.games.store import ScoreStore


class _GameFrame(QWidget):
    """Common chrome: title row, restart + how-to-play buttons, body area."""

    def __init__(self, title: str, help_text: str, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        t = QLabel(title)
        t.setFont(QFont("", 14, QFont.Weight.DemiBold))
        top.addWidget(t)
        top.addStretch(1)
        self.info = QLabel("")
        self.info.setStyleSheet("color:#5F5F5F;")
        top.addWidget(self.info)
        btn_help = QPushButton("How to play")
        btn_help.clicked.connect(lambda: QMessageBox.information(self, title, help_text))
        btn_restart = QPushButton("Restart")
        top.addWidget(btn_restart)
        top.addWidget(btn_help)
        lay.addLayout(top)
        self.body_host = QVBoxLayout()
        lay.addLayout(self.body_host)
        self._btn_restart = btn_restart


# ------------------------------------------------------------------ Minesweeper
_NUM_COLORS = {1: "#0078D4", 2: "#107C10", 3: "#C42B1C", 4: "#5B2A86",
               5: "#9D5D00", 6: "#008575", 7: "#444444", 8: "#111111"}


class MinesweeperView(_GameFrame):
    EASY = (9, 9, 10)
    EXPERT = (16, 16, 40)

    def __init__(self, store: ScoreStore):
        super().__init__("Minesweeper",
                         "Left-click reveals a cell. Right-click places a flag on "
                         "suspected mines. Reveal every cell except the mines. "
                         "The first click is always safe.")
        self._store = store
        self.diff = QComboBox()
        self.diff.addItems(["Beginner 9×9 · 10 mines", "Expert 16×16 · 40 mines"])
        self.diff.currentIndexChanged.connect(self.new_game)
        self.top_row = QHBoxLayout()
        self.top_row.addWidget(self.diff)
        self.top_row.addStretch(1)
        self.body_host.addLayout(self.top_row)
        self.grid_w = QGridLayout()
        self.grid_w.setSpacing(2)
        self.body_host.addLayout(self.grid_w)
        self._btn_restart.clicked.connect(self.new_game)
        self.new_game()

    def new_game(self):
        w, h, m = self.EXPERT if self.diff.currentIndex() == 1 else self.EASY
        self.game = Minesweeper(w, h, m)
        self.variant = "expert" if self.diff.currentIndex() == 1 else "beginner"
        self._t0 = None
        self.buttons = []
        while self.grid_w.count():
            it = self.grid_w.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        for idx in range(w * h):
            b = QPushButton("")
            b.setFixedSize(30, 30)
            b.setFocusPolicy(Qt.TabFocus)
            b.clicked.connect(lambda _=False, i=idx: self._click(i))
            b.setContextMenuPolicy(Qt.CustomContextMenu)
            b.customContextMenuRequested.connect(
                lambda pos, i=idx, bb=b: self._flag(bb.mapToGlobal(pos), i))
            self.grid_w.addWidget(b, idx // w, idx % w)
            self.buttons.append(b)
        self._redraw()

    def _click(self, idx):
        if self.game.dead or self.game.won:
            return
        if self._t0 is None:
            self._t0 = time.monotonic()
        self.game.reveal(idx)
        self._redraw()
        if self.game.dead:
            self.info.setText("Boom! Click Restart to try again.")
        elif self.game.won:
            secs = int(time.monotonic() - self._t0)
            rec = self._store.record("minesweeper", self.variant,
                                     **{"best_seconds": secs})
            self.info.setText(f"You won in {secs}s "
                              f"(best: {rec.get('best_seconds', secs)}s)")

    def _flag(self, global_pos, idx):
        if self.game.dead or self.game.won:
            return
        self.game.toggle_flag(idx)
        self._redraw()

    def _redraw(self):
        g = self.game
        for idx, b in enumerate(self.buttons):
            b.setText("")
            b.setStyleSheet("")
            b.setEnabled(True)
            if g.revealed[idx]:
                v = g.grid[idx]
                b.setEnabled(False)
                if v == -1:
                    b.setText("💥")
                    b.setStyleSheet("background:#FDE7E9;")
                elif v > 0:
                    b.setText(str(v))
                    b.setStyleSheet(f"color:{_NUM_COLORS[v]}; font-weight:bold;"
                                   " background:#EDEDED;")
                else:
                    b.setStyleSheet("background:#EDEDED;")
            elif g.flagged[idx]:
                b.setText("🚩")
            if g.dead and g.grid[idx] == -1 and not g.revealed[idx]:
                b.setText("💣")
                b.setEnabled(False)
        left = g.m - g.flags_used()
        self.info.setText(f"Mines left: {left}" + ("  ·  ⏱ running" if self._t0 and not g.dead and not g.won else ""))


# ---------------------------------------------------------------------- Sudoku
class SudokuView(_GameFrame):
    def __init__(self, store: ScoreStore):
        super().__init__("Sudoku",
                         "Fill the grid so every row, column and 3×3 box contains "
                         "1–9 once. Type a digit with the selected empty cell, or "
                         "click a cell then a digit button. Given clues cannot be "
                         "changed. Errors are highlighted in red.")
        self._store = store
        self.diff = QComboBox()
        self.diff.addItems(["Easy (40 clues)", "Medium (32 clues)", "Hard (26 clues)"])
        self.diff.currentIndexChanged.connect(self.new_game)
        row = QHBoxLayout()
        row.addWidget(self.diff)
        row.addStretch(1)
        self.body_host.addLayout(row)

        self.grid_w = QGridLayout()
        self.grid_w.setSpacing(1)
        self.cells = []
        for r in range(9):
            for c in range(9):
                b = QPushButton("")
                b.setFixedSize(38, 38)
                b.setCheckable(True)
                bold = (r % 3 == 0)
                right = (c % 3 == 2)
                style = "QPushButton { background:white; border:1px solid #C8C8C8;"
                if bold:
                    style += " border-top:2px solid #555;"
                if r == 8 and (r % 3 == 2):
                    style += " border-bottom:2px solid #555;"
                if right:
                    style += " border-right:2px solid #555;"
                if c == 8 and c % 3 == 2:
                    style += " border-left none;"
                style += " }"
                b.setStyleSheet(style)
                b.clicked.connect(lambda _=False, i=r*9+c: self._select(i))
                self.grid_w.addWidget(b, r, c)
                self.cells.append(b)
        self.body_host.addLayout(self.grid_w)

        digits = QHBoxLayout()
        self.digit_btns = []
        for d in range(1, 10):
            b = QPushButton(str(d))
            b.setMinimumWidth(34)
            b.clicked.connect(lambda _=False, v=d: self._enter(v))
            digits.addWidget(b)
            self.digit_btns.append(b)
        eraser = QPushButton("⌫")
        eraser.clicked.connect(lambda: self._enter(0))
        digits.addWidget(eraser)
        hint = QPushButton("Hint")
        hint.setToolTip("Fill the selected cell with the correct value (adds 60 s penalty).")
        hint.clicked.connect(self._hint)
        digits.addWidget(hint)
        digits.addStretch(1)
        self.body_host.addLayout(digits)
        self._btn_restart.clicked.connect(self.new_game)
        self.sel = None
        self.new_game()

    def new_game(self):
        keep = [40, 32, 26][self.diff.currentIndex()]
        rng = random.Random()
        self.puzzle, self.solution = generate_sudoku(rng, clues_keep=keep)
        self.givens = [[v != 0 for v in row] for row in self.puzzle]
        self.board = [row[:] for row in self.puzzle]
        self.variant = ["easy", "medium", "hard"][self.diff.currentIndex()]
        self._t0 = time.monotonic()
        self.penalty = 0
        self.sel = None
        self._redraw()
        self.info.setText("New puzzle generated locally.")

    def _select(self, i):
        r, c = divmod(i, 9)
        if self.givens[r][c]:
            return
        if self.sel is not None:
            self.cells[self.sel].setChecked(False)
        self.sel = i
        self.cells[i].setChecked(True)

    def _set(self, i, v):
        r, c = divmod(i, 9)
        if self.givens[r][c]:
            return
        self.board[r][c] = v
        self._redraw_cell(i)
        self._check_done()

    def _enter(self, v):
        if self.sel is None:
            self.info.setText("Select an empty cell first.")
            return
        self._set(self.sel, v)

    def _hint(self):
        if self.sel is None:
            self.info.setText("Select an empty cell first.")
            return
        r, c = divmod(self.sel, 9)
        self.penalty += 60
        self._set(self.sel, self.solution[r][c])

    def _conflict(self, i) -> bool:
        r, c = divmod(i, 9)
        v = self.board[r][c]
        if v == 0:
            return False
        for k in range(9):
            if k != c and self.board[r][k] == v:
                return True
            if k != r and self.board[k][c] == v:
                return True
        br, bc = 3*(r//3), 3*(c//3)
        for rr in range(br, br+3):
            for cc in range(bc, bc+3):
                if (rr, cc) != (r, c) and self.board[rr][cc] == v:
                    return True
        return False

    def _redraw_cell(self, i):
        r, c = divmod(i, 9)
        b = self.cells[i]
        v = self.board[r][c]
        b.setText(str(v) if v else "")
        if self.givens[r][c]:
            b.setStyleSheet(b.styleSheet().replace("background:white", "background:#EFEFEF"))
            b.setEnabled(False)
        elif v and self._conflict(i):
            b.setStyleSheet("QPushButton { background:#FDE7E9; color:#C42B1C;"
                            " border:1px solid #C42B1C; }")
        else:
            b.setStyleSheet("QPushButton { background:white; border:1px solid #C8C8C8; }")

    def _redraw(self):
        for i in range(81):
            self._redraw_cell(i)

    def _check_done(self):
        flat = [v for row in self.board for v in row]
        if 0 in flat:
            return
        if is_valid_solution(self.board):
            secs = int(time.monotonic() - self._t0) + self.penalty
            rec = self._store.record("sudoku", self.variant,
                                     **{"best_seconds": secs})
            self.info.setText(f"Solved in {secs}s (best: {rec.get('best_seconds')}s) 🎉")
            QMessageBox.information(self, "Sudoku", f"Solved in {secs} seconds!")
        else:
            self.info.setText("Grid is full but not valid — check red cells.")


# ----------------------------------------------------------------- MemoryMatch
class MemoryView(_GameFrame):
    def __init__(self, store: ScoreStore):
        super().__init__("Memory Match",
                         "Flip two cards at a time and find all matching pairs. "
                         "Fewer moves is better. Best score per size is saved on "
                         "this computer only.")
        self._store = store
        row = QHBoxLayout()
        self.size = QComboBox()
        self.size.addItems(["4×3 (6 pairs)", "4×4 (8 pairs)", "6×4 (12 pairs)"])
        self.size.currentIndexChanged.connect(self.new_game)
        row.addWidget(self.size)
        row.addStretch(1)
        self.body_host.addLayout(row)
        self.grid_w = QGridLayout()
        self.grid_w.setSpacing(6)
        self.body_host.addLayout(self.grid_w)
        self._btn_restart.clicked.connect(self.new_game)
        self.new_game()

    def new_game(self):
        pairs = [6, 8, 12][self.size.currentIndex()]
        self.variant = f"{pairs}p"
        self.game = MemoryMatch(pairs)
        cols = 4 if pairs <= 8 else 6
        while self.grid_w.count():
            it = self.grid_w.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self.buttons = []
        for idx in range(self.game.n):
            b = QPushButton("?")
            b.setFixedSize(64, 64)
            b.setFont(QFont("", 22))
            b.clicked.connect(lambda _=False, i=idx: self._flip(i))
            self.grid_w.addWidget(b, idx // cols, idx % cols)
            self.buttons.append(b)
        self._redraw()
        best = self._store.best("memory", self.variant, "best_moves")
        self.info.setText(f"Moves: 0 · Pairs left: {pairs}" +
                          (f" · Best: {best}" if best else ""))

    def _flip(self, idx):
        kind, pair = self.game.flip(idx)
        if kind in ("invalid", "first"):
            return
        self._redraw()
        if kind == "miss":
            a, b = pair
            QTimer.singleShot(650, lambda: (self.game.settle(a, b), self._redraw()))
        elif kind == "match":
            self._check_won()
        self._update_info()

    def _update_info(self):
        best = self._store.best("memory", self.variant, "best_moves")
        self.info.setText(f"Moves: {self.game.moves} · Pairs left: "
                          f"{self.game.remaining_pairs()}" +
                          (f" · Best: {best}" if best else ""))

    def _check_won(self):
        if self.game.won:
            rec = self._store.record("memory", self.variant,
                                     **{"best_moves": self.game.moves})
            self.info.setText(f"All matched in {self.game.moves} moves! "
                              f"Best: {rec.get('best_moves')}")
            QMessageBox.information(self, "Memory Match",
                                    f"You cleared the board in {self.game.moves} moves!")

    def _redraw(self):
        for idx, b in enumerate(self.buttons):
            if self.game.face_up[idx] or self.game.matched[idx]:
                b.setText(self.game.cards[idx])
                b.setEnabled(not self.game.matched[idx])
                b.setStyleSheet("background:#FFFFFF;"
                                + ("border:2px solid #107C10;" if self.game.matched[idx] else ""))
            else:
                b.setText("?")
                b.setEnabled(True)
                b.setStyleSheet("background:#0078D4; color:white;")


# -------------------------------------------------------------------- Hub page
class GamesPage(QWidget):
    """Tab container for the three offline games."""

    def __init__(self, settings):
        super().__init__()
        self._store = ScoreStore()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 12, 24, 16)
        tabs = QTabWidget()
        tabs.addTab(MinesweeperView(self._store), "Minesweeper")
        tabs.addTab(SudokuView(self._store), "Sudoku")
        tabs.addTab(MemoryView(self._store), "Memory Match")
        lay.addWidget(tabs, 1)
