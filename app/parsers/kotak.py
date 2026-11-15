"""Kotak Mahindra Bank savings account statement. Rules: docs/layouts/kotak.md."""

from __future__ import annotations

import re
from datetime import date, datetime

import pdfplumber

from .. import errors
from ..common import Line, Row, Statement, group_lines, join_description, parse_amount
from ..pdf import words
from .base import BankParser

PERIOD = re.compile(r"^(\d{2} [A-Za-z]{3} \d{4}) - (\d{2} [A-Za-z]{3} \d{4})$")
FOOTER_TOP = 810


def _bucket(w: dict) -> str | None:
    x0, x1 = w["x0"], w["x1"]
    if x0 < 35:
        return None
    if x0 < 60:
        return "sno"
    if x0 < 115:
        return "date"
    if x0 < 272:
        return "desc"
    if x0 < 350:
        return "ref"
    if x1 <= 430:
        return "dr"
    if x1 <= 500:
        return "cr"
    return "bal"


def _cells(line: Line) -> dict[str, list[str]]:
    cells: dict[str, list[str]] = {}
    for w in line.words:
        b = _bucket(w)
        if b:
            cells.setdefault(b, []).append(w["text"])
    return cells


def _parse_date(text: str) -> date:
    try:
        return datetime.strptime(text, "%d %b %Y").date()
    except ValueError:
        raise errors.unsupported_layout("unreadable date")


def _header_top(lines: list[Line]) -> float | None:
    for line in lines:
        if any(w["text"] == "#" and w["x0"] < 50 for w in line.words) and "Balance" in line.text:
            return line.top
    return None


class KotakParser(BankParser):
    bank = "kotak"
    version = "kotak-1"

    def parse(self, pdf: pdfplumber.PDF) -> Statement:
        page_lines = [group_lines(words(page)) for page in pdf.pages]
        period_from, period_to = self._period(page_lines[0])

        opening = None
        rows: list[Row] = []
        parts: list[list[str]] = []  # description parts per row, joined at the end
        refs: list[str | None] = []
        serials: list[int] = []
        summary = None

        for pno, lines in enumerate(page_lines, start=1):
            header = _header_top(lines)
            if header is None:
                summary = summary or self._summary(lines)
                continue
            for line in lines:
                if line.top <= header or line.top >= FOOTER_TOP:
                    continue
                cells = _cells(line)
                sno = " ".join(cells.get("sno", []))
                desc = " ".join(cells.get("desc", []))

                if sno == "-" and desc.startswith("Opening Balance"):
                    opening = parse_amount(" ".join(cells.get("bal", [])))
                    if opening is None:
                        raise errors.unsupported_layout("opening balance unreadable")
                    continue

                if sno.isdigit() and len(cells.get("date", [])) == 3:
                    if opening is None:
                        raise errors.unsupported_layout("opening balance row not found")
                    rows.append(self._row(cells, pno))
                    parts.append([desc])
                    refs.append(" ".join(cells.get("ref", [])) or None)
                    serials.append(int(sno))
                    continue

                if set(cells) <= {"desc"} and desc:
                    if not rows:
                        raise errors.unsupported_layout(f"text before the first transaction on page {pno}")
                    parts[-1].append(desc)  # wrapped description, possibly carried over a page break
                    continue

                raise errors.unsupported_layout(f"unrecognised table line on page {pno}")

        if opening is None:
            raise errors.unsupported_layout("transaction table not found")
        if serials != list(range(1, len(serials) + 1)):
            raise errors.reconciliation_failed("transaction serial numbers are not contiguous")

        for row, p, ref in zip(rows, parts, refs):
            row.description = join_description(p)
            row.ref_no = ref

        closing = None
        if summary is not None:
            summary_opening, closing = summary
            if summary_opening != opening:
                raise errors.reconciliation_failed("opening balance differs between table and Account Summary")

        return Statement(period_from=period_from, period_to=period_to, opening=opening, closing=closing, rows=rows)

    def _period(self, lines: list[Line]) -> tuple[date | None, date | None]:
        for line in lines:
            m = PERIOD.match(line.text)
            if m:
                return _parse_date(m.group(1)), _parse_date(m.group(2))
        return None, None

    def _row(self, cells: dict[str, list[str]], pno: int) -> Row:
        dr, cr, bal = cells.get("dr", []), cells.get("cr", []), cells.get("bal", [])
        if len(bal) != 1 or len(dr) > 1 or len(cr) > 1 or len(dr) + len(cr) != 1:
            raise errors.unsupported_layout(f"unexpected amount columns on page {pno}")
        debit = parse_amount(dr[0]) if dr else None
        credit = parse_amount(cr[0]) if cr else None
        balance = parse_amount(bal[0])
        if balance is None or (dr and debit is None) or (cr and credit is None):
            raise errors.unsupported_layout(f"unreadable amount on page {pno}")
        return Row(
            date=_parse_date(" ".join(cells["date"])),
            description="",
            ref_no=None,
            debit=debit,
            credit=credit,
            balance=balance,
        )

    @staticmethod
    def _summary(lines: list[Line]):
        """(opening, closing) from the 'Account Summary' table. None if this page has no summary;
        raises if the summary is present but unreadable (never silently skip the closing check)."""
        idx = next((i for i, l in enumerate(lines) if l.text.strip() == "Account Summary"), None)
        if idx is None:
            return None
        for line in lines[idx + 1 :]:
            if line.text.startswith("End of Statement"):
                break
            amounts = [a for a in (parse_amount(w["text"]) for w in line.words) if a is not None]
            if len(amounts) == 2:
                return amounts[0], amounts[1]
        raise errors.unsupported_layout("Account Summary found but its balances are unreadable")
