"""SBI savings account statement (net banking PDF). Rules: docs/layouts/sbi.md."""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass
from datetime import date, datetime

import pdfplumber

from .. import errors
from ..common import Line, Row, Statement, group_lines, join_description, parse_amount
from ..pdf import horizontal_borders, words
from .base import BankParser

DATE = re.compile(r"^\d{2}/\d{2}/\d{4}$")
PERIOD = re.compile(r"Statement From\s*:?\s*(\d{2}-\d{2}-\d{4})\s+to\s+(\d{2}-\d{2}-\d{4})", re.I)
SUMMARY_PERIOD = re.compile(r"Statement Summary\s*:?\s*(\d{2}-\d{2}-\d{4})\s+to\s+(\d{2}-\d{2}-\d{4})", re.I)
AMT = r"(\d[\d,]*\.\d{2})"
SUMMARY_VALUES = re.compile(rf"^{AMT}(CR|DR)\s+(\d+)\s+(\d+)\s+{AMT}\s+{AMT}\s+{AMT}(CR|DR)$", re.I)
AT_LINE = re.compile(r"^(?:\d{13}\s+)?(.*?)\s*\bAT\s+\d{5}$")
REF_PATTERNS = [
    re.compile(r"UPI/[A-Z]+/(\d{12})"),
    re.compile(r"IMPS/(\d{12})"),
]
NEFT = re.compile(r"NEFT\*[^*\s]+\*")

# Column bands by word x0 (pt). See spec section 3.
TXN_DATE_MAX = 75
VALUE_DATE = (75, 130)
DESC = (130, 295)
REF = (295, 340)
DEBIT = (340, 400)
CREDIT = (400, 490)
BALANCE_MIN = 500

FOOTER_TOP = 740  # "Page no. N" sits at ~755
LEAD_GAP = 8.5  # a lead line sits 7.1pt above its date line; every other line gap is >= 9.3


def _parse_date(text: str, fmt: str) -> date:
    try:
        return datetime.strptime(text, fmt).date()
    except ValueError:
        raise errors.unsupported_layout("unreadable date")


def _is_date_line(line: Line) -> bool:
    first = line.words[0]
    return first["x0"] < TXN_DATE_MAX and bool(DATE.match(first["text"]))


@dataclass
class Pending:
    """A transaction whose description may still grow (its tail can be on the next page)."""

    row: Row
    parts: list[str]
    column_ref: str | None


@dataclass
class Block:
    """The visual lines of one transaction. date_idx is None for an orphan (continuation at a page top)."""

    lines: list[Line]
    date_idx: int | None

    def signature(self) -> tuple:
        return (self.date_idx, tuple(round(line.top, 1) for line in self.lines))


class SbiParser(BankParser):
    bank = "sbi"
    version = "sbi-1"

    def parse(self, pdf: pdfplumber.PDF) -> Statement:
        page_lines = [group_lines(words(page)) for page in pdf.pages]
        period_from, period_to = self._period(page_lines)

        pending: list[Pending] = []
        summary = None
        for pno, (page, lines) in enumerate(zip(pdf.pages, page_lines), start=1):
            body, summary_lines = self._body(lines)
            if summary_lines and summary is None:
                summary = self._summary(summary_lines)
            if not body:
                continue

            gap_blocks = self._blocks_by_gap(body)
            borders = horizontal_borders(page)
            if borders:
                border_blocks = self._blocks_by_border(body, borders, pno)
                if [b.signature() for b in border_blocks] != [b.signature() for b in gap_blocks]:
                    raise errors.unsupported_layout(f"row boundaries are ambiguous on page {pno}")
                blocks = border_blocks
            else:
                blocks = gap_blocks

            for block in blocks:
                if block.date_idx is None:
                    if not pending:
                        raise errors.unsupported_layout(f"text before the first transaction on page {pno}")
                    pending[-1].parts += [l.text for l in block.lines]  # tail carried over a page break
                else:
                    pending.append(self._row(block, pno))

        # Descriptions and refs are finalised only now, after every page, so a row split across
        # pages is stripped and referenced exactly like an unsplit one (stable dedupe hash).
        rows: list[Row] = []
        for p in pending:
            parts = self._strip_branch_trailer(p.parts)
            p.row.description = join_description(parts)
            p.row.ref_no = p.column_ref or self._ref_from_description(p.row.description)
            rows.append(p.row)

        if summary is None:
            raise errors.unsupported_layout("Statement Summary not found")
        if period_from is None and summary.get("period"):
            period_from, period_to = summary["period"]

        return Statement(
            period_from=period_from,
            period_to=period_to,
            opening=summary["opening"],
            closing=summary["closing"],
            rows=rows,
            totals={k: summary[k] for k in ("total_debits", "total_credits", "debit_count", "credit_count")},
        )

    # --- header / footer -------------------------------------------------------------------

    def _period(self, page_lines: list[list[Line]]) -> tuple[date | None, date | None]:
        for line in page_lines[0]:
            m = PERIOD.search(line.text)
            if m:
                return _parse_date(m.group(1), "%d-%m-%Y"), _parse_date(m.group(2), "%d-%m-%Y")
        return None, None

    def _body(self, lines: list[Line]) -> tuple[list[Line], list[Line]]:
        """Transaction lines (below the 'Balance' column header, above the footer / summary),
        plus the lines from 'Statement Summary' onwards if present on this page."""
        start = next(
            (i for i, l in enumerate(lines) if len(l.words) == 1 and l.words[0]["text"] == "Balance" and l.words[0]["x0"] > BALANCE_MIN),
            None,
        )
        if start is None:
            return [], self._summary_lines(lines)
        body: list[Line] = []
        for line in lines[start + 1 :]:
            if line.top > FOOTER_TOP or line.text.startswith("Statement Summary"):
                break
            body.append(line)
        return body, self._summary_lines(lines)

    @staticmethod
    def _summary_lines(lines: list[Line]) -> list[Line]:
        idx = next((i for i, l in enumerate(lines) if l.text.startswith("Statement Summary")), None)
        return [] if idx is None else lines[idx:]

    def _summary(self, lines: list[Line]) -> dict:
        out: dict = {}
        m = SUMMARY_PERIOD.search(lines[0].text)
        if m:
            out["period"] = (_parse_date(m.group(1), "%d-%m-%Y"), _parse_date(m.group(2), "%d-%m-%Y"))
        for line in lines[1:]:
            m = SUMMARY_VALUES.match(line.text)
            if m:
                out.update(
                    opening=parse_amount(m.group(1) + m.group(2).upper()),
                    debit_count=int(m.group(3)),
                    credit_count=int(m.group(4)),
                    total_debits=parse_amount(m.group(5)),
                    total_credits=parse_amount(m.group(6)),
                    closing=parse_amount(m.group(7) + m.group(8).upper()),
                )
                return out
        raise errors.unsupported_layout("Statement Summary figures not found")

    # --- row segmentation --------------------------------------------------------------------

    def _blocks_by_border(self, body: list[Line], borders: list[float], pno: int) -> list[Block]:
        bands: dict[int, list[Line]] = {}
        for line in body:
            bands.setdefault(bisect.bisect_left(borders, line.top), []).append(line)
        blocks: list[Block] = []
        for _, lines in sorted(bands.items()):
            date_idx = [i for i, l in enumerate(lines) if _is_date_line(l)]
            if len(date_idx) > 1:
                raise errors.unsupported_layout(f"two transactions share a table row on page {pno}")
            if not date_idx and blocks:
                raise errors.unsupported_layout(f"table row without a date on page {pno}")
            blocks.append(Block(lines, date_idx[0] if date_idx else None))
        return blocks

    def _blocks_by_gap(self, body: list[Line]) -> list[Block]:
        blocks: list[Block] = []
        pending: list[Line] = []
        for i, line in enumerate(body):
            if _is_date_line(line):
                blocks.append(Block(pending + [line], len(pending)))
                pending = []
                continue
            nxt = body[i + 1] if i + 1 < len(body) else None
            if nxt is not None and _is_date_line(nxt) and nxt.top - line.top < LEAD_GAP:
                pending.append(line)
            elif blocks:
                blocks[-1].lines.append(line)
            else:
                blocks.append(Block([line], None))  # continuation of the previous page's last row
        return blocks

    # --- row assembly ------------------------------------------------------------------------

    def _row(self, block: Block, pno: int) -> Pending:
        date_line = block.lines[block.date_idx]

        def cell(lo: float, hi: float) -> list[str]:
            return [w["text"] for w in date_line.in_x(lo, hi)]

        value_date = cell(*VALUE_DATE)
        ref = cell(*REF)
        debit, credit = cell(*DEBIT), cell(*CREDIT)
        balance = [w["text"] for w in date_line.words if w["x0"] >= BALANCE_MIN]
        if len(debit) != 1 or len(credit) != 1 or len(balance) != 1 or len(value_date) != 1:
            raise errors.unsupported_layout(f"unexpected columns in a transaction on page {pno}")

        d, c, bal = parse_amount(debit[0]), parse_amount(credit[0]), parse_amount(balance[0])
        if bal is None or (d is None and debit[0] != "-") or (c is None and credit[0] != "-"):
            raise errors.unsupported_layout(f"unreadable amount on page {pno}")

        parts = [l.text for l in block.lines[: block.date_idx]]
        parts.append(" ".join(cell(*DESC)))
        parts += [l.text for l in block.lines[block.date_idx + 1 :]]

        row = Row(
            date=_parse_date(date_line.words[0]["text"], "%d/%m/%Y"),
            description="",
            ref_no=None,
            debit=d,
            credit=c,
            balance=bal,
        )
        return Pending(row, parts, " ".join(ref) if ref and ref != ["-"] else None)

    @staticmethod
    def _strip_branch_trailer(parts: list[str]) -> list[str]:
        """Drops the '<13 digits> AT <5-digit branch>' line and the branch-name line after it."""
        for k in (len(parts) - 2, len(parts) - 1):
            if k >= 1:
                m = AT_LINE.match(parts[k])
                if m:
                    return parts[:k] + ([m.group(1)] if m.group(1) else [])
        return parts

    @staticmethod
    def _ref_from_description(description: str) -> str | None:
        for pattern in REF_PATTERNS:
            m = pattern.search(description)
            if m:
                return m.group(1)
        m = NEFT.search(description)
        if m:
            # NEFT*<IFSC>*<UTR>*<sender>: the UTR is often hard-wrapped onto the next line, which
            # inserts a space. Rejoin it up to the next '*'. Without a closing '*' a wrap can't be
            # told apart from following text, so only a single unambiguous token is accepted.
            rest = description[m.end():]
            if "*" in rest:
                utr = re.sub(r"\s+", "", rest.split("*", 1)[0])
            else:
                tokens = rest.split()
                utr = tokens[0] if len(tokens) == 1 else ""
            return utr or None
        return None
