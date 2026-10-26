"""Tests for pure game logic (Minesweeper, Sudoku, Memory Match)."""
import random

import pytest

from deskhub.features.games.logic import (
    MemoryMatch, Minesweeper, generate_sudoku, is_valid_solution, solve_board,
)


class TestMinesweeper:
    def _board(self, **kw):
        return Minesweeper(rng=random.Random(42), **kw)

    def test_first_click_never_mine(self):
        for seed in range(25):
            g = Minesweeper(rng=random.Random(seed))
            g.reveal(40)  # centre
            assert not g.dead

    def test_flood_fill_opens_region(self):
        g = self._board()
        g.reveal(0)
        assert any(g.revealed)

    def test_flags_and_bounds(self):
        g = self._board()
        g.toggle_flag(5)
        assert g.flagged[5] and g.flags_used() == 1
        g.toggle_flag(5)
        assert g.flags_used() == 0
        g.toggle_flag(-1)      # ignored
        g.toggle_flag(10**6)   # ignored
        assert g.flags_used() == 0

    def test_reveal_on_flag_blocked(self):
        g = self._board()
        g.toggle_flag(0)
        g.reveal(0)
        assert not g.revealed[0]

    def test_losing_reveals_dead_only_for_mine(self):
        g = self._board(width=4, height=4, mines=1)
        g.reveal(0)  # places mines away from 0 and neighbours
        # find a mine and click it
        mine = g.grid.index(-1)
        g.reveal(mine)
        assert g.dead and not g.won
        g.reveal(1)  # input ignored after death
        assert g.grid[mine] == -1

    def test_win_condition(self):
        g = self._board(width=4, height=4, mines=1)
        g.reveal(0)
        for i in range(16):
            if g.grid[i] != -1:
                g.reveal(i)
        assert g.won

    def test_chord(self):
        g = self._board(width=4, height=4, mines=1)
        g.reveal(0)
        idx = next(i for i in range(16) if g.grid[i] > 0 and g.revealed[i] is False)
        g.reveal(idx)
        n = g.grid[idx]
        nb = g.neighbors(idx)
        mines_here = [k for k in nb if g.grid[k] == -1]
        for k in mines_here[:n]:
            g.toggle_flag(k)
        before = sum(g.revealed)
        g.chord(idx)
        if len(mines_here) == n:
            assert sum(g.revealed) >= before  # chord executed without error


class TestSudoku:
    def test_generated_puzzle_unique_and_solvable(self):
        puzzle, solution = generate_sudoku(random.Random(7), clues_keep=40)
        assert is_valid_solution(solution)
        # puzzle derives from solution
        for r in range(9):
            for c in range(9):
                assert puzzle[r][c] == 0 or puzzle[r][c] == solution[r][c]
        g = [row[:] for row in puzzle]
        assert solve_board(g)
        assert g == solution

    def test_clue_count_respected(self):
        puzzle, _ = generate_sudoku(random.Random(3), clues_keep=35)
        clues = sum(1 for r in range(9) for c in range(9) if puzzle[r][c])
        assert 30 <= clues <= 45  # generation may stop early but stays reasonable

    def test_is_valid_solution_rejects_bad(self):
        _, sol = generate_sudoku(random.Random(1), clues_keep=45)
        bad = [row[:] for row in sol]
        bad[0][0] = bad[0][1]  # duplicate in row
        assert not is_valid_solution(bad)
        zero = [[0] * 9 for _ in range(9)]
        assert not is_valid_solution(zero)


class TestMemoryMatch:
    def test_deck_construction(self):
        m = MemoryMatch(pairs=6, rng=random.Random(1))
        assert len(m.cards) == 12
        assert all(m.cards.count(x) == 2 for x in set(m.cards))

    def test_flip_sequence(self):
        m = MemoryMatch(pairs=3, rng=random.Random(2))
        kind, _ = m.flip(0)
        assert kind == "first"
        # find its partner
        partner = next(i for i in range(m.n) if i != 0 and m.cards[i] == m.cards[0])
        other = next(i for i in range(m.n) if m.cards[i] != m.cards[0])
        kind, pair = m.flip(other)
        assert kind == "miss" and pair == (0, other)
        m.settle(*pair)
        assert not m.face_up[other]
        # After a settle the board is clear, so the next flip starts a new
        # pair ('first'); clicking the same card again is rejected ('invalid')
        # while it stays face-up and un-matched; clicking its twin completes
        # the pair ('match') and locks both cards.
        kind, _ = m.flip(partner)
        assert kind == "first"
        assert m.face_up[partner]
        kind, _ = m.flip(partner)
        assert kind == "invalid"  # already face up — click ignored
        assert not m.matched[partner]
        kind, pair = m.flip(0)  # index 0 holds the same emoji as partner
        assert kind == "match" and pair == (partner, 0)
        assert m.matched[0] and m.matched[partner]

    def test_invalid_flips(self):
        m = MemoryMatch(pairs=2, rng=random.Random(3))
        assert m.flip(-1)[0] == "invalid"
        assert m.flip(99)[0] == "invalid"
        m.flip(0)
        assert m.flip(0)[0] == "invalid"  # already up

    def test_full_win(self):
        m = MemoryMatch(pairs=2, rng=random.Random(4))
        pairs = {}
        for i, c in enumerate(m.cards):
            pairs.setdefault(c, []).append(i)
        for a, b in pairs.values():
            m.flip(a)
            kind, _ = m.flip(b)
            assert kind == "match"
        assert m.won and m.remaining_pairs() == 0

    def test_pairs_bounds(self):
        with pytest.raises(ValueError):
            MemoryMatch(pairs=1)
        with pytest.raises(ValueError):
            MemoryMatch(pairs=99)
