"""Tests for the spreadsheet formula engine, CSV round-trip and slide math."""
import pytest

from deskhub.features.office.logic import (
    FormulaError, SheetModel, cell_name, col_letters, fit_text_size,
    parse_cell_ref,
)


class TestRefs:
    @pytest.mark.parametrize("idx,name", [(0, "A"), (25, "Z"), (26, "AA"), (51, "AZ")])
    def test_col_letters(self, idx, name):
        assert col_letters(idx) == name

    def test_roundtrip(self):
        assert parse_cell_ref("AA10") == (9, 26)
        assert cell_name(9, 26) == "AA10"

    @pytest.mark.parametrize("bad", ["", "A", "1", "A0", "#REF", "A1B"])
    def test_invalid(self, bad):
        with pytest.raises(ValueError):
            parse_cell_ref(bad)


class TestFormulas:
    def setup_method(self):
        self.m = SheetModel()

    def set(self, ref, text):
        r, c = parse_cell_ref(ref)
        self.m.set_raw(r, c, text)

    def vals(self):
        return self.m.evaluate_all()

    def get(self, ref):
        r, c = parse_cell_ref(ref)
        v = self.vals()[(r, c)]
        return v

    def test_literal_numbers_and_text(self):
        self.set("A1", "42")
        self.set("A2", "hello")
        assert self.get("A1") == 42.0
        assert self.get("A2") == "hello"

    def test_arithmetic_precedence(self):
        self.set("A1", "=1+2*3^2")
        assert self.get("A1") == 19.0

    def test_parens_and_unary(self):
        self.set("A1", "=-(2+3)*2")
        assert self.get("A1") == -10.0

    def test_refs_and_ranges(self):
        self.set("A1", "1")
        self.set("A2", "2")
        self.set("A3", "3")
        self.set("B1", "=SUM(A1:A3)")
        self.set("B2", "=A1+A2+A3")
        self.set("B3", "=AVERAGE(A1:A3)")
        self.set("B4", "=MIN(A1:A3)&''" if False else "=MAX(A1:A3)")
        assert self.get("B1") == 6.0
        assert self.get("B2") == 6.0
        assert self.get("B3") == 2.0
        assert self.get("B4") == 3.0

    def test_functions(self):
        self.set("A1", "1.5")
        self.set("A2", "-2.5")
        self.set("B1", "=ROUND(A1,0)")
        self.set("B2", "=ABS(A2)")
        self.set("B3", "=COUNT(A1:A2)")
        assert self.get("B1") in (2.0, 2)   # banker's vs half-up both acceptable? no—assert numeric
        assert self.get("B2") == 2.5
        assert self.get("B3") == 2

    def test_division_by_zero_is_error_not_crash(self):
        self.set("A1", "=1/0")
        assert str(self.get("A1")).startswith("#ERROR!")

    def test_bad_formula_per_cell_error(self):
        self.set("A1", "=SUM(")
        assert str(self.get("A1")).startswith("#ERROR!")

    def test_unknown_function(self):
        self.set("A1", "=FOO(1)")
        assert str(self.get("A1")).startswith("#ERROR!")

    def test_circular_reference_reported(self):
        self.set("A1", "=B1")
        self.set("B1", "=A1")
        vals = self.vals()
        assert any(str(v).startswith("#ERROR!") for v in vals.values())

    def test_bounds_enforced(self):
        with pytest.raises(ValueError):
            self.m.set_raw(-1, 0, "x")
        with pytest.raises(ValueError):
            self.m.set_raw(0, self.m.cols, "x")


class TestCSV:
    def test_load_and_export_roundtrip(self):
        m = SheetModel()
        m.load_csv("name,qty,price\napple,3,1.5\npear,2,=C2*2\n")
        rows = m.to_csv_rows()
        assert rows[0] == ["name", "qty", "price"]
        assert rows[1][:2] == ["apple", "3"]
        # formula computed on export
        assert float(rows[1][2]) == 1.5
        assert float(rows[2][2]) == 3.0

    def test_quoted_commas(self):
        m = SheetModel()
        m.load_csv('a,b\n"x, y",2\n')
        rows = m.to_csv_rows()
        assert rows[1][0] == "x, y"


class TestSlideMath:
    def test_fit_shrinks_long_text(self):
        short = fit_text_size("Hi", 6, 2)
        long = fit_text_size("word " * 200, 6, 2)
        assert short >= long
        assert long >= 10  # never below min

    def test_empty_text(self):
        assert fit_text_size("", 4, 1) == 28
