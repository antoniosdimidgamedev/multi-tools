"""Pure-python office helpers: spreadsheet formulas, CSV conversion, slide layout.

Kept GUI-free so they are unit-testable headlessly and reusable by the
packaging smoke tests.
"""
from __future__ import annotations

import csv
import io
import re
from typing import Callable

# ---------------------------------------------------------------------------
# Spreadsheet formula engine
# ---------------------------------------------------------------------------

_CELL_RE = re.compile(r"^([A-Za-z]{1,3})([1-9][0-9]*)$")
_FUNC_RE = re.compile(r"^([A-Z]+)\((.*)\)$", re.DOTALL)

MAX_ROW = 200
MAX_COL = 40


def col_letters(idx: int) -> str:
    """0-based column index -> letters (0->A, 25->Z, 26->AA)."""
    s = ""
    idx += 1
    while idx > 0:
        idx, rem = divmod(idx - 1, 26)
        s = chr(65 + rem) + s
    return s


def parse_cell_ref(ref: str) -> tuple[int, int]:
    """'B3' -> (row=2, col=1). Raises ValueError on bad refs."""
    m = _CELL_RE.match(ref.strip())
    if not m:
        raise ValueError(f"Invalid cell reference: {ref!r}")
    letters, digits = m.group(1).upper(), m.group(2)
    col = 0
    for ch in letters:
        col = col * 26 + (ord(ch) - 64)
    return int(digits) - 1, col - 1


def cell_name(row: int, col: int) -> str:
    return f"{col_letters(col)}{row + 1}"


def _to_number(v) -> float:
    if v is None or v == "":
        return 0.0
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "")
    try:
        return float(s)
    except ValueError:
        raise ValueError(f"Not a number: {v!r}")


class FormulaError(Exception):
    pass


class SheetModel:
    """Grid of raw strings with computed values and simple formula support.

    Supported: numbers, text, cell refs (B3), ranges (A1:B4), operators
    + - * / ^ ( ) and functions SUM AVERAGE MIN MAX COUNT ROUND ABS.
    """

    def __init__(self, rows: int = MAX_ROW, cols: int = MAX_COL):
        self.rows = rows
        self.cols = cols
        self.raw: dict[tuple[int, int], str] = {}

    # -- basic access ------------------------------------------------------
    def set_raw(self, row: int, col: int, text: str) -> None:
        if not (0 <= row < self.rows and 0 <= col < self.cols):
            raise ValueError("Cell outside sheet bounds")
        text = "" if text is None else str(text)
        if text == "":
            self.raw.pop((row, col), None)
        else:
            self.raw[(row, col)] = text

    def get_raw(self, row: int, col: int) -> str:
        return self.raw.get((row, col), "")

    # -- evaluation --------------------------------------------------------
    def evaluate_all(self) -> dict[tuple[int, int], object]:
        """Return {(row,col): value} for every non-empty cell.

        A formula error in one cell yields '#ERROR! …' for that cell instead
        of failing the whole sheet (Excel-like behaviour).  Genuine circular
        references are reported per-cell too.
        """
        out: dict[tuple[int, int], object] = {}
        memo: dict[tuple[int, int], object] = {}
        stack: set[tuple[int, int]] = set()
        cyclic: set[tuple[int, int]] = set()

        def _resolve(tok):
            # Range aggregation treats cells inside a detected cycle as blank;
            # direct references still raise so users see the problem.
            if tok.kind == "range":
                a, b = tok.text.split(":")
                return ("RANGE", self._range(a, b, memo, stack, skip=cyclic))
            return self._token_value(tok, memo, stack)

        keys = sorted(self.raw, key=lambda k: 0 if not self.raw[k].startswith("=") else 1)
        for key in keys:
            try:
                val = self._value(key, memo, stack, resolve=_resolve)
            except FormulaError as exc:
                msg = str(exc)
                if msg.startswith("Circular reference at "):
                    culprit = msg.rsplit(" ", 1)[-1]
                    try:
                        cc = parse_cell_ref(culprit)
                        cyclic.add(cc)
                        memo.pop(cc, None)
                    except ValueError:
                        pass
                memo[key] = f"#ERROR! {msg}"
                val = memo[key]
            out[key] = val
        return out

    def _value(self, key, memo, stack, resolve=None):
        if key in memo:
            return memo[key]
        if key in stack:
            raise FormulaError(f"Circular reference at {cell_name(*key)}")
        raw = self.get_raw(*key)
        stack.add(key)
        try:
            if raw.startswith("="):
                val = self._eval_expr(raw[1:], memo, stack, resolve)
            else:
                val = _coerce_literal(raw)
        finally:
            stack.discard(key)
        memo[key] = val
        return val

    def _lookup(self, ref: str, memo, stack):
        r, c = parse_cell_ref(ref)
        return self._value((r, c), memo, stack)

    def _range(self, a: str, b: str, memo, stack, skip=frozenset()):
        r1, c1 = parse_cell_ref(a)
        r2, c2 = parse_cell_ref(b)
        if (r1, c1) > (r2, c2):
            (r1, c1), (r2, c2) = (r2, c2), (r1, c1)
        vals = []
        for rr in range(r1, min(r2, self.rows - 1) + 1):
            for cc in range(c1, min(c2, self.cols - 1) + 1):
                key = (rr, cc)
                if key in stack or key in skip:
                    # Aggregate over a cycle: treat cyclic cells as blank
                    # instead of failing (Excel shows a warning but proceeds).
                    vals.append("")
                else:
                    vals.append(self._value(key, memo, stack))
        return vals

    def _eval_expr(self, expr: str, memo, stack, resolve=None):
        tokens = tokenize(expr)
        if resolve is None:
            resolve = lambda t: self._token_value(t, memo, stack)  # noqa: E731
        self._sub_resolver = resolve
        pos, val = parse_expression(tokens, 0, resolve)
        if pos != len(tokens):
            raise FormulaError(f"Unexpected token near {getattr(tokens[pos], 'text', '?')!r}")
        return val

    def _token_value(self, tok, memo, stack):
        if tok.kind == "num":
            return float(tok.text)
        if tok.kind == "str":
            return tok.text
        if tok.kind == "range":
            a, b = tok.text.split(":")
            return ("RANGE", self._range(a, b, memo, stack))
        if tok.kind == "func":
            name = tok.name
            inner = tok.text[len(name) + 1:-1]
            args = split_args(inner)
            evaluated = []
            sub = getattr(self, "_sub_resolver", None) or \
                (lambda t: self._token_value(t, memo, stack))  # noqa: E731
            for arg in args:
                p, v = parse_expression(tokenize(arg), 0, sub)
                if p != len(tokenize(arg)):
                    raise FormulaError(f"Bad argument in {tok.name}(...)")
                evaluated.append(v)
            return apply_function(name.upper(), evaluated)
        if tok.kind == "ref":
            return self._lookup(tok.text, memo, stack)
        raise FormulaError(f"Unexpected token {tok.text!r}")

    # -- CSV ---------------------------------------------------------------
    def to_csv_rows(self) -> list[list[str]]:
        vals = self.evaluate_all()
        if not self.raw:
            return []
        max_r = max(r for r, _ in self.raw)
        max_c = max(c for _, c in self.raw)
        rows = []
        for r in range(max_r + 1):
            row = []
            for c in range(max_c + 1):
                v = vals.get((r, c), "")
                row.append(fmt_number(v) if isinstance(v, float) else ("" if v is None else str(v)))
            rows.append(row)
        return rows

    def load_csv(self, text: str) -> None:
        self.raw.clear()
        reader = csv.reader(io.StringIO(text))
        for r, row in enumerate(reader):
            if r >= self.rows:
                break
            for c, cell in enumerate(row):
                if c >= self.cols:
                    break
                if cell != "":
                    self.raw[(r, c)] = cell


def fmt_number(v: float) -> str:
    if v == int(v) and abs(v) < 1e15:
        return str(int(v))
    return f"{v:.6g}"


def _coerce_literal(raw: str):
    s = raw.strip()
    try:
        return float(s.replace(",", "")) if s else ""
    except ValueError:
        return raw


# ---- tokenizer / recursive-descent parser --------------------------------

class Tok:
    __slots__ = ("kind", "text", "name")

    def __init__(self, kind: str, text: str, name: str = ""):
        self.kind, self.text, self.name = kind, text, name

    def __repr__(self):  # pragma: no cover
        return f"Tok({self.kind},{self.text})"


_RANGE_RE = re.compile(r"[A-Za-z]{1,3}[1-9][0-9]*:[A-Za-z]{1,3}[1-9][0-9]*")
_REF_RE = re.compile(r"[A-Za-z]{1,3}[1-9][0-9]*")
_NUM_RE = re.compile(r"[0-9]+(?:\.[0-9]+)?")
_FUNC_HEAD_RE = re.compile(r"[A-Za-z]+\(")


def tokenize(expr: str) -> list[Tok]:
    toks: list[Tok] = []
    i, n = 0, len(expr)
    while i < n:
        ch = expr[i]
        if ch.isspace():
            i += 1
            continue
        if ch in "+-*/^(),":
            toks.append(Tok("op", ch))
            i += 1
            continue
        if ch == '"':
            j = expr.find('"', i + 1)
            if j == -1:
                raise FormulaError("Unterminated string literal")
            toks.append(Tok("str", expr[i + 1:j]))
            i = j + 1
            continue
        m = _NUM_RE.match(expr, i)
        if m:
            toks.append(Tok("num", m.group()))
            i = m.end()
            continue
        m = _RANGE_RE.match(expr, i)
        if m:
            toks.append(Tok("range", m.group()))
            i = m.end()
            continue
        m = _FUNC_HEAD_RE.match(expr, i)
        if m:
            name = m.group()[:-1].upper()
            depth, j = 1, m.end()
            instr = False
            while j < n and depth:
                ch2 = expr[j]
                if ch2 == '"':
                    instr = not instr
                elif not instr:
                    if ch2 == "(":
                        depth += 1
                    elif ch2 == ")":
                        depth -= 1
                j += 1
            if depth:
                raise FormulaError("Unbalanced parentheses")
            toks.append(Tok("func", expr[i:j], name))
            i = j
            continue
        m = _REF_RE.match(expr, i)
        if m:
            toks.append(Tok("ref", m.group().upper()))
            i = m.end()
            continue
        raise FormulaError(f"Unexpected character {ch!r}")
    return toks


def split_args(inner: str) -> list[str]:
    parts, depth, cur = [], 0, ""
    instr = False
    for ch in inner:
        if ch == '"':
            instr = not instr
        if not instr:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            elif ch == "," and depth == 0:
                parts.append(cur)
                cur = ""
                continue
        cur += ch
    parts.append(cur)
    return [p for p in parts] if inner.strip() else []


def parse_expression(tokens: list[Tok], pos: int, resolve: Callable[[Tok], object]):
    return parse_additive(tokens, pos, resolve)


def parse_additive(tokens, pos, resolve):
    pos, left = parse_multiplicative(tokens, pos, resolve)
    while pos < len(tokens) and tokens[pos].kind == "op" and tokens[pos].text in "+-":
        op = tokens[pos].text
        pos, right = parse_multiplicative(tokens, pos + 1, resolve)
        left = _num(left) + _num(right) if op == "+" else _num(left) - _num(right)
    return pos, left


def parse_multiplicative(tokens, pos, resolve):
    pos, left = parse_power(tokens, pos, resolve)
    while pos < len(tokens) and tokens[pos].kind == "op" and tokens[pos].text in "*/":
        op = tokens[pos].text
        pos, right = parse_power(tokens, pos + 1, resolve)
        if op == "/" and _num(right) == 0:
            raise FormulaError("Division by zero")
        left = _num(left) * _num(right) if op == "*" else _num(left) / _num(right)
    return pos, left


def parse_power(tokens, pos, resolve):
    pos, base = parse_unary(tokens, pos, resolve)
    if pos < len(tokens) and tokens[pos].kind == "op" and tokens[pos].text == "^":
        pos, exp = parse_power(tokens, pos + 1, resolve)
        return pos, _num(base) ** _num(exp)
    return pos, base


def parse_unary(tokens, pos, resolve):
    if pos < len(tokens) and tokens[pos].kind == "op" and tokens[pos].text == "-":
        pos, v = parse_unary(tokens, pos + 1, resolve)
        return pos, -_num(v)
    if pos < len(tokens) and tokens[pos].kind == "op" and tokens[pos].text == "+":
        return parse_unary(tokens, pos + 1, resolve)
    return parse_atom(tokens, pos, resolve)


def parse_atom(tokens, pos, resolve):
    if pos >= len(tokens):
        raise FormulaError("Unexpected end of formula")
    tok = tokens[pos]
    if tok.kind == "op" and tok.text == "(":
        pos, val = parse_additive(tokens, pos + 1, resolve)
        if pos >= len(tokens) or tokens[pos].text != ")":
            raise FormulaError("Missing closing parenthesis")
        return pos + 1, val
    if tok.kind in ("num", "str", "ref", "range", "func"):
        return pos + 1, resolve(tok)
    raise FormulaError(f"Unexpected token {tok.text!r}")


def _num(v):
    if isinstance(v, tuple) and v and v[0] == "RANGE":
        raise FormulaError("Range used where a single number is required")
    try:
        return _to_number(v)
    except ValueError as exc:
        raise FormulaError(str(exc)) from exc


def _flatten(args):
    out = []
    for a in args:
        if isinstance(a, tuple) and a and a[0] == "RANGE":
            out.extend(a[1])
        else:
            out.append(a)
    return out


def apply_function(name: str, args: list):
    flat = _flatten(args)
    # Aggregate functions ignore text/blank cells (Excel-like); arithmetic ops
    # still raise via _num.  '#ERROR!' propagates so mistakes stay visible.
    def _coerce(x):
        if isinstance(x, str) and x.startswith("#ERROR!"):
            raise FormulaError(x)
        try:
            return _num(x)
        except FormulaError:
            return None

    if name in ("SUM", "AVERAGE", "MIN", "MAX", "COUNT"):
        nums = [n for n in (_coerce(x) for x in flat) if n is not None]
        if name == "SUM":
            return sum(nums)
        if name == "COUNT":
            return float(len(nums))
        if not nums:
            raise FormulaError(f"{name} of empty/non-numeric range")
        if name == "AVERAGE":
            return sum(nums) / len(nums)
        return min(nums) if name == "MIN" else max(nums)
    if name == "ROUND":
        if len(flat) != 2:
            raise FormulaError("ROUND(number, digits) takes 2 arguments")
        digits = int(_num(flat[1]))
        return round(_num(flat[0]), digits)
    if name == "ABS":
        if len(flat) != 1:
            raise FormulaError("ABS(number) takes 1 argument")
        return abs(_num(flat[0]))
    raise FormulaError(f"Unsupported function: {name}")


def evaluate_formula(expr: str, lookup: Callable[[str], object]) -> object:
    """Standalone helper used by tests: '='-prefixed formula + ref resolver."""
    toks = tokenize(expr)
    pos, val = parse_expression(toks, 0, lambda t: lookup(t.text) if t.kind == "ref"
                                else (float(t.text) if t.kind == "num" else t.text))
    return val


# ---------------------------------------------------------------------------
# Presentation layout math (pure; used by PPTX writer and the editor view)
# ---------------------------------------------------------------------------

SLIDE_W_IN = 13.333
SLIDE_H_IN = 7.5


def fit_text_size(text: str, box_w_in: float, box_h_in: float,
                  base_pt: float = 28, min_pt: float = 10) -> float:
    """Shrink font size until the wrapped text roughly fits its box."""
    pt = base_pt
    chars_per_line = max(1, int(box_w_in * 96 / (pt * 0.62)))
    lines = 0
    for para in text.splitlines() or [""]:
        lines += max(1, -(-len(para) // chars_per_line))
    line_h_in = pt * 1.35 / 72
    while lines * line_h_in > box_h_in and pt > min_pt:
        pt -= 2
        chars_per_line = max(1, int(box_w_in * 96 / (pt * 0.62)))
        lines = 0
        for para in text.splitlines() or [""]:
            lines += max(1, -(-len(para) // chars_per_line))
        line_h_in = pt * 1.35 / 72
    return pt
