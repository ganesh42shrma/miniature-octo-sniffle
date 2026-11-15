"""Helpers shared by the bank parsers: amounts, lines, descriptions, reconciliation."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from . import errors

Word = dict  # a pdfplumber word: text, x0, x1, top, bottom, ...

# Indian (1,23,456.78) or western (123,456.78) grouping, or plain 123456.78. Optional sign / Cr-Dr suffix.
_AMOUNT = re.compile(r"^(-)?(\d{1,3}(?:,\d{2,3})*|\d+)\.(\d{2})(CR|DR|Cr|Dr)?$")


def parse_amount(text: str | None) -> Decimal | None:
    """'1,23,456.78' -> Decimal('123456.78'); '14,380.73CR' -> positive; '...DR' or '-...' -> negative.
    Returns None for placeholders such as '-' or ''."""
    if text is None:
        return None
    text = text.strip()
    m = _AMOUNT.match(text)
    if not m:
        return None
    try:
        value = Decimal(f"{m.group(2).replace(',', '')}.{m.group(3)}")
    except InvalidOperation:
        return None
    if m.group(1) or (m.group(4) or "").upper() == "DR":
        value = -value
    return value


def is_amount(text: str) -> bool:
    return parse_amount(text) is not None


@dataclass
class Line:
    top: float
    words: list[Word]

    @property
    def text(self) -> str:
        return " ".join(w["text"] for w in self.words)

    def in_x(self, lo: float, hi: float) -> list[Word]:
        return [w for w in self.words if lo <= w["x0"] < hi]


def group_lines(words: list[Word], tol: float = 2.5) -> list[Line]:
    """Groups words into visual lines (same `top` within `tol`), each sorted left to right."""
    lines: list[Line] = []
    for w in sorted(words, key=lambda w: (round(w["top"]), w["x0"])):
        if lines and abs(lines[-1].top - w["top"]) <= tol:
            lines[-1].words.append(w)
        else:
            lines.append(Line(w["top"], [w]))
    for line in lines:
        line.words.sort(key=lambda w: w["x0"])
    return lines


def join_description(parts: list[str]) -> str:
    """Joins wrapped description lines. FROZEN: the backend's dedupe hash includes the description,
    so changing this breaks de-duplication of re-imported statements.

    No space when the previous part ends in '/' or '-', or the next starts with '/'
    (hard-wrapped UPI strings, '(Value Date: 13-' + '10-2026)'). Otherwise one space."""
    out = ""
    for part in (p.strip() for p in parts):
        if not part:
            continue
        if not out or out.endswith(("/", "-")) or part.startswith("/"):
            out += part
        else:
            out += " " + part
    return re.sub(r"\s+", " ", out).strip()


@dataclass
class Row:
    date: date
    description: str
    ref_no: str | None
    debit: Decimal | None
    credit: Decimal | None
    balance: Decimal


@dataclass
class Statement:
    period_from: date | None
    period_to: date | None
    opening: Decimal
    closing: Decimal | None
    rows: list[Row]
    # Optional printed totals (SBI prints them): total_debits, total_credits, debit_count, credit_count.
    totals: dict = field(default_factory=dict)


def reconcile(stmt: Statement) -> None:
    """All-or-nothing checks. Raises RECONCILIATION_FAILED describing the first problem (no statement text)."""
    if not stmt.rows:
        raise errors.unsupported_layout("no transactions found")

    prev = stmt.opening
    for i, row in enumerate(stmt.rows, start=1):
        if (row.debit is None) == (row.credit is None):
            raise errors.reconciliation_failed(f"row {i} must have exactly one of debit/credit")
        # Direction comes from the column, so amounts must be positive magnitudes. A negative debit
        # would reconcile here but be stored by the backend as a positive debit (abs()).
        if (row.debit if row.debit is not None else row.credit) <= 0:
            raise errors.reconciliation_failed(f"row {i} has a zero or negative amount")
        expected = prev - (row.debit or 0) + (row.credit or 0)
        if expected != row.balance:
            raise errors.reconciliation_failed(
                f"running balance breaks at row {i} ({row.date.isoformat()}): expected {expected}, statement shows {row.balance}"
            )
        prev = row.balance

    debits = sum((r.debit or Decimal(0) for r in stmt.rows), Decimal(0))
    credits = sum((r.credit or Decimal(0) for r in stmt.rows), Decimal(0))
    if stmt.closing is not None:
        if stmt.opening + credits - debits != stmt.closing:
            raise errors.reconciliation_failed(
                f"opening {stmt.opening} + credits {credits} - debits {debits} != closing {stmt.closing}"
            )
        if stmt.rows[-1].balance != stmt.closing:
            raise errors.reconciliation_failed("last row balance differs from closing balance")

    t = stmt.totals
    checks = [
        ("total debits", t.get("total_debits"), debits),
        ("total credits", t.get("total_credits"), credits),
        ("debit count", t.get("debit_count"), sum(1 for r in stmt.rows if r.debit is not None)),
        ("credit count", t.get("credit_count"), sum(1 for r in stmt.rows if r.credit is not None)),
    ]
    for name, printed, computed in checks:
        if printed is not None and printed != computed:
            raise errors.reconciliation_failed(f"{name}: statement shows {printed}, parsed {computed}")

    for i in range(1, len(stmt.rows)):
        if stmt.rows[i].date < stmt.rows[i - 1].date:
            raise errors.reconciliation_failed(f"row {i + 1} is dated before the row above it")

    if stmt.period_from and stmt.period_to:
        for i, row in enumerate(stmt.rows, start=1):
            if not (stmt.period_from <= row.date <= stmt.period_to):
                raise errors.reconciliation_failed(f"row {i} date {row.date.isoformat()} is outside the statement period")
