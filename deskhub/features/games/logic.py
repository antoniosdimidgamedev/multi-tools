"""Pure-python game logic for DeskHub games (no Qt) — fully unit-testable."""
from __future__ import annotations

import random
import re
from dataclasses import dataclass, field


# ---------------------------------------------------------------- Minesweeper
class Minesweeper:
    """Classic 9x9/16x16 minesweeper. Cells: -1 = mine, else neighbour count."""

    def __init__(self, width=9, height=9, mines=10, rng: random.Random | None = None):
        if not (4 <= width <= 50 and 4 <= height <= 50):
            raise ValueError("Board too small/large")
        if mines >= width * height - 9:
            raise ValueError("Too many mines for this board")
        self.w, self.h, self.m = width, height, mines
        self._rng = rng or random.Random()
        self.reset()

    def reset(self):
        self.grid = [0] * (self.w * self.h)
        self.revealed = [False] * (self.w * self.h)
        self.flagged = [False] * (self.w * self.h)
        self.dead = False
        self.won = False
        self._mines_placed = False

    def _place_mines(self, exclude: int):
        # exclude the clicked cell and its 8 neighbours for a fair opening
        ex = {exclude}
        x, y = divmod(exclude, self.w)
        for i in range(max(0, x-1), min(self.w, x+2)):
            for j in range(max(0, y-1), min(self.h, y+2)):
                ex.add(j * self.w + i)
        ex &= set(range(self.w * self.h))
        if len(ex) > self.w * self.h - self.m:
            ex = {exclude}
        pool = sorted(set(range(self.w * self.h)) - ex)
        for idx in self._rng.sample(pool, self.m):
            self.grid[idx] = -1
        for idx in range(self.w * self.h):
            if self.grid[idx] != -1:
                self.grid[idx] = self._neighbours(idx)
        self._mines_placed = True

    def _neighbours(self, idx: int) -> int:
        x, y = divmod(idx, self.w)
        n = 0
        for i in range(max(0, x-1), min(self.w, x+2)):
            for j in range(max(0, y-1), min(self.h, y+2)):
                k = j * self.w + i
                if k != idx and self.grid[k] == -1:
                    n += 1
        return n

    def neighbors(self, idx: int) -> list[int]:
        x, y = divmod(idx, self.w)
        out = []
        for i in range(max(0, x-1), min(self.w, x+2)):
            for j in range(max(0, y-1), min(self.h, y+2)):
                k = j * self.w + i
                if k != idx:
                    out.append(k)
        return out

    def reveal(self, idx: int) -> None:
        if self.dead or self.won or not (0 <= idx < self.w * self.h):
            return
        if self.flagged[idx] or self.revealed[idx]:
            return
        if not self._mines_placed:
            self._place_mines(idx)
        if self.grid[idx] == -1:
            self.dead = True
            self.revealed[idx] = True
            return
        # flood fill zeros
        stack = [idx]
        while stack:
            k = stack.pop()
            if self.revealed[k] or self.flagged[k] or self.grid[k] == -1:
                continue
            self.revealed[k] = True
            if self.grid[k] == 0:
                stack.extend(self.neighbors(k))
        self._check_win()

    def toggle_flag(self, idx: int) -> None:
        if self.dead or self.won or not (0 <= idx < self.w * self.h):
            return
        if self.revealed[idx]:
            return
        self.flagged[idx] = not self.flagged[idx]

    def chord(self, idx: int) -> None:
        """Middle-click: reveal neighbours if flag count matches number."""
        if self.dead or self.won or not self.revealed[idx]:
            return
        if self.grid[idx] <= 0:
            return
        nb = self.neighbors(idx)
        if sum(self.flagged[k] for k in nb) == self.grid[idx]:
            for k in nb:
                if not self.flagged[k]:
                    self.reveal(k)

    def flags_used(self) -> int:
        return sum(self.flagged)

    def _check_win(self):
        if all(self.revealed[i] or self.grid[i] == -1
               for i in range(self.w * self.h)):
            if self._mines_placed:
                self.won = True


# --------------------------------------------------------------------- Sudoku
def solve_board(grid: list[list[int]]) -> bool:
    """Backtracking solver; mutates grid in place. 0 = empty."""
    for r in range(9):
        for c in range(9):
            if grid[r][c] == 0:
                for v in (1, 2, 3, 4, 5, 6, 7, 8, 9):
                    if _can_place(grid, r, c, v):
                        grid[r][c] = v
                        if solve_board(grid):
                            return True
                        grid[r][c] = 0
                return False
    return True


def _can_place(grid, r, c, v) -> bool:
    if any(grid[r][i] == v for i in range(9)):
        return False
    if any(grid[i][c] == v for i in range(9)):
        return False
    br, bc = 3 * (r // 3), 3 * (c // 3)
    return all(grid[br + i][bc + j] != v for i in range(3) for j in range(3))


def count_solutions(grid: list[list[int]], limit: int = 2) -> int:
    """Count solutions up to *limit* (used to verify uniqueness)."""
    g = [row[:] for row in grid]

    def rec() -> int:
        for r in range(9):
            for c in range(9):
                if g[r][c] == 0:
                    total = 0
                    for v in range(1, 10):
                        if _can_place(g, r, c, v):
                            g[r][c] = v
                            total += rec()
                            g[r][c] = 0
                            if total >= limit:
                                return total
                    return total
        return 1

    return rec()


def generate_sudoku(rng: random.Random | None = None,
                    clues_keep: int = 32) -> tuple[list[list[int]], list[list[int]]]:
    """Return (puzzle, solution). Puzzle has a unique solution by construction."""
    rng = rng or random.Random()
    # shuffled solved grid
    base = [[0] * 9 for _ in range(9)]
    nums = list(range(1, 10))
    rng.shuffle(nums)
    fill_random(base, nums, rng)
    solution = [row[:] for row in base]
    puzzle = [row[:] for row in base]
    cells = [(r, c) for r in range(9) for c in range(9)]
    rng.shuffle(cells)
    removed = 0
    target = 81 - clues_keep
    for r, c in cells:
        if removed >= target:
            break
        backup = puzzle[r][c]
        puzzle[r][c] = 0
        if count_solutions(puzzle, 2) == 1:
            removed += 1
        else:
            puzzle[r][c] = backup
    return puzzle, solution


def fill_random(grid, nums, rng: random.Random) -> bool:
    for r in range(9):
        for c in range(9):
            if grid[r][c] == 0:
                vals = nums[:]
                rng.shuffle(vals)
                for v in vals:
                    if _can_place(grid, r, c, v):
                        grid[r][c] = v
                        if fill_random(grid, nums, rng):
                            return True
                        grid[r][c] = 0
                return False
    return True


def is_valid_solution(grid: list[list[int]]) -> bool:
    if any(grid[r][c] not in range(1, 10) for r in range(9) for c in range(9)):
        return False
    rows = [set(range(9)) for _ in range(0)]  # placeholder no-op
    for i in range(9):
        if len({grid[i][c] for c in range(9)}) != 9:
            return False
        if len({grid[r][i] for r in range(9)}) != 9:
            return False
    for br in range(0, 9, 3):
        for bc in range(0, 9, 3):
            block = {grid[br+i][bc+j] for i in range(3) for j in range(3)}
            if len(block) != 9:
                return False
    return True


# ------------------------------------------------------------- Memory Match
EMOJI_POOL = ["🍎", "🚀", "🌵", "🐙", "🎲", "🧩", "🔦", "🍦",
              "⚓", "🪁", "🎯", "🧭"]


class MemoryMatch:
    def __init__(self, pairs: int = 8, rng: random.Random | None = None):
        if not 2 <= pairs <= len(EMOJI_POOL):
            raise ValueError(f"pairs must be 2..{len(EMOJI_POOL)}")
        rng = rng or random.Random()
        chosen = rng.sample(EMOJI_POOL, pairs)
        deck = chosen * 2
        rng.shuffle(deck)
        self.cards = deck
        self.n = len(deck)
        self.face_up = [False] * self.n
        self.matched = [False] * self.n
        self.moves = 0
        self.open: list[int] = []
        self.busy = False

    def flip(self, idx: int):
        """Flip a card.

        Returns one of:
          ('first', None)             first card of a pair is showing
          ('invalid', None)           rejected click
          ('match', (a, b))           second card completed a pair
          ('miss', (a, b))            second card did not match; UI should
                                      call settle() after a short delay.
        """
        if not (0 <= idx < self.n) or self.matched[idx] or self.face_up[idx]:
            return ("invalid", None)
        if self.busy:  # a previous miss was never settled: clean up and treat
            self.settle_pending()  # this click as the start of a new pair
        # Drop any stale open-list entries whose cards are no longer face-up.
        self.open = [i for i in self.open if self.face_up[i] and not self.matched[i]]
        self.face_up[idx] = True
        if not self.open:
            self.open = [idx]
            return ("first", None)
        self.moves += 1
        self.busy = True
        a, b = self.open[0], idx
        self.open = []
        if self.cards[a] == self.cards[b]:
            self.matched[a] = self.matched[b] = True
            self.busy = False
            return ("match", (a, b))
        return ("miss", (a, b))

    def settle_pending(self) -> None:
        """Hide every un-matched face-up card and reset the open pair state."""
        for i in range(self.n):
            if not self.matched[i]:
                self.face_up[i] = False
        self.open = []
        self.busy = False

    def settle(self, a: int = -1, b: int = -1) -> None:
        """Hide an unmatched pair after the UI's peek delay.

        Only settles if *a* and *b* are still the two face-up cards; stale
        timers from an already-resolved pair become no-ops.  Called with no
        arguments it hides every un-matched face-up card.
        """
        if a >= 0 and b >= 0:
            if not (self.face_up[a] and self.face_up[b]
                    and not self.matched[a] and not self.matched[b]):
                return
        self.settle_pending()

    @property
    def won(self) -> bool:
        return all(self.matched)

    def remaining_pairs(self) -> int:
        return sum(not m for m in self.matched) // 2
