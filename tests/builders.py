"""Builds fake SBI / Kotak statement PDFs that follow the layouts in docs/layouts/.

Fully synthetic (no real data), so they can be committed and run anywhere. Coordinates use
pdfplumber's convention: `top` is measured from the top of the page.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from decimal import Decimal

from reportlab.lib.pdfencrypt import StandardEncryption
from reportlab.pdfgen import canvas

W, H = 595, 842


def money(v: Decimal) -> str:
    """Indian grouping: 123456.78 -> 1,23,456.78"""
    s = f"{v:.2f}"
    whole, frac = s.split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    return f"{whole}.{frac}"


class Page:
    def __init__(self, c: canvas.Canvas):
        self.c = c

    def text(self, x: float, top: float, s: str, size: float = 8) -> None:
        self.c.setFont("Helvetica", size)
        self.c.drawString(x, H - top - size * 0.8, s)

    def rtext(self, x1: float, top: float, s: str, size: float = 8) -> None:
        self.c.setFont("Helvetica", size)
        self.c.drawRightString(x1, H - top - size * 0.8, s)

    def hrule(self, top: float, segments=((20, 100), (100, 156), (156, 306), (306, 356), (356, 436), (436, 486), (486, 566))) -> None:
        for x0, x1 in segments:
            self.c.line(x0, H - top, x1, H - top)


def _canvas(buf, password: str | None) -> canvas.Canvas:
    enc = StandardEncryption(password, ownerPassword="owner-" + password, strength=128) if password else None
    return canvas.Canvas(buf, pagesize=(W, H), encrypt=enc)


# --- SBI -------------------------------------------------------------------------------------


@dataclass
class SbiTxn:
    date: str  # DD/MM/YYYY
    lines: list[str]  # description lines; lines[0] is printed on the date line
    debit: Decimal | None = None
    credit: Decimal | None = None
    lead: str | None = "WDL TFR"
    trailer: bool = True  # "<13d> AT <5d>" + branch line


@dataclass
class SbiStatement:
    opening: Decimal
    txns: list[SbiTxn]
    per_page: int = 5
    password: str | None = None
    tamper_balance_at: int | None = None  # index of a row whose printed balance is off by 1.00
    borders: bool = True
    summary_debit_total_delta: Decimal = Decimal(0)
    split_tail: int = 0  # move the last N printed lines of each page's last row to the next page
    bad_date_at: int | None = None  # print an impossible date (32/..) on this row


def build_sbi(st: SbiStatement) -> bytes:
    buf = io.BytesIO()
    c = _canvas(buf, st.password)
    balance = st.opening
    pages = [st.txns[i : i + st.per_page] for i in range(0, len(st.txns), st.per_page)] or [[]]
    debits = credits = Decimal(0)
    n_dr = n_cr = 0
    idx = 0
    carry: list[str] = []
    for pno, txns in enumerate(pages, start=1):
        p = Page(c)
        if pno == 1:
            p.text(200, 60, "STATEMENT OF ACCOUNT", 12)
            p.text(347, 80, "State Bank of India", 10)
            p.text(347, 100, "IFSC Code : SBIN0000001", 10)
            p.text(203, 140, "Statement From :01-07-2026 to 30-09-2026", 10)
            head = 170
        else:
            head = 30.5
        p.text(514, head, "Balance", 10)
        top = head + 30
        if st.borders:
            p.hrule(top - 12)
        if carry:  # tail of the previous page's last row
            y = top - 7.1
            for line in carry:
                p.text(138, y, line)
                y += 9.3
            if st.borders:
                p.hrule(y)
            top = y + 19.1
            carry = []
        for i, t in enumerate(txns):
            if t.lead:
                p.text(138, top - 7.1, t.lead)
            shown_date = "32" + t.date[2:] if st.bad_date_at == idx else t.date
            p.text(27, top, shown_date)
            p.text(82, top, shown_date)
            p.text(138, top, t.lines[0])
            p.text(304, top, "-")
            if t.debit is not None:
                balance -= t.debit
                debits += t.debit
                n_dr += 1
                p.rtext(383, top, money(t.debit))
                p.text(446, top, "-")
            else:
                balance += t.credit
                credits += t.credit
                n_cr += 1
                p.text(366, top, "-")
                p.rtext(463, top, money(t.credit))
            shown = balance + (Decimal(1) if st.tamper_balance_at == idx else 0)
            p.rtext(548, top, money(shown))
            tail = t.lines[1:] + (["1234567890123 AT 05198", "MAIN BRANCH, CITY"] if t.trailer else [])
            if st.split_tail and i == len(txns) - 1 and pno < len(pages):
                carry, tail = tail[-st.split_tail :], tail[: -st.split_tail]
            y = top + 11.5
            for extra in tail:
                p.text(138, y, extra)
                y += 9.3
            if st.borders:
                p.hrule(y + 2)
            top = y + 2 + 19.1  # leaves room for the next row's lead line above its date
            idx += 1
        p.text(269, 755.4, f"Page no. {pno}", 10)
        if pno == len(pages):
            s = top + 30
            p.text(40, s, "Statement Summary : 01-07-2026 To 30-09-2026", 10)
            p.text(40, s + 28, "Brought Forward Dr Count Cr Count Total Debits Total Credits Closing Balance", 9)
            vals = [
                money(st.opening) + "CR",
                str(n_dr),
                str(n_cr),
                money(debits + st.summary_debit_total_delta),
                money(credits),
                money(balance) + "CR",
            ]
            for x, v in zip((40, 139, 197, 258, 359, 483), vals):
                p.text(x, s + 57, v, 9)
        c.showPage()
    c.save()
    return buf.getvalue()


# --- Kotak -----------------------------------------------------------------------------------


@dataclass
class KotakTxn:
    date: str  # "01 Aug 2026"
    lines: list[str]
    ref: str | None = None
    debit: Decimal | None = None
    credit: Decimal | None = None


@dataclass
class KotakStatement:
    opening: Decimal
    txns: list[KotakTxn]
    per_page: int = 6
    split_last_row: bool = False  # push the last row's final description line onto the next page
    skip_serial: bool = False
    summary: bool = True
    summary_closing_text: str | None = None  # override the printed closing amount (e.g. "N/A")


ROW = 6.5  # Helvetica is wider than Kotak's font; 6.5pt keeps text inside the real column widths


def build_kotak(st: KotakStatement) -> bytes:
    buf = io.BytesIO()
    c = _canvas(buf, None)
    balance = st.opening
    pages = [st.txns[i : i + st.per_page] for i in range(0, len(st.txns), st.per_page)] or [[]]
    serial = 0
    carry: str | None = None

    def header(p: Page, top: float) -> None:
        p.text(44, top, "#", 9)
        p.text(75, top, "Date", 9)
        p.text(124, top, "Description", 9)
        p.text(280, top, "Chq/Ref. No.", 9)
        p.text(355, top, "Withdrawal (Dr.)", 9)
        p.text(429, top, "Deposit (Cr.)", 9)
        p.text(498, top, "Balance", 9)

    for pno, txns in enumerate(pages, start=1):
        p = Page(c)
        if pno == 1:
            p.text(36, 102, "Account Statement", 25)
            p.text(36, 140, "01 Aug 2026 - 31 Oct 2026", 11)
            p.text(36, 300, "MICR 000000000 IFSC Code KKBK0000001", 9)
            p.text(36, 315, "Kotak Mahindra Bank", 9)
            head = 366
        else:
            p.text(36, 27.6, "Account No. 0000000000", 9)
            p.text(36, 90.3, "Savings Account Transactions", 12)
            head = 116.6
        header(p, head)
        top = head + 20
        if pno == 1:
            p.text(37, top, "-", ROW)
            p.text(75, top, "-", ROW)
            p.text(119, top, "Opening Balance", ROW)
            p.rtext(556, top, money(st.opening), ROW)
            top += 13.7
        if carry:
            p.text(119, top, carry, ROW)
            top += 13.7
            carry = None
        for i, t in enumerate(txns):
            serial += 2 if (st.skip_serial and serial == 1) else 1
            p.text(37, top, str(serial), ROW)
            for x, part in zip((73, 84, 99), t.date.split()):
                p.text(x, top, part, ROW)
            p.text(119, top, t.lines[0], ROW)
            if t.ref:
                p.text(275, top, t.ref, ROW)
            if t.debit is not None:
                balance -= t.debit
                p.rtext(418, top, money(t.debit), ROW)
            else:
                balance += t.credit
                p.rtext(487, top, money(t.credit), ROW)
            p.rtext(556, top, money(balance), ROW)
            rest = t.lines[1:]
            last_on_page = i == len(txns) - 1 and pno < len(pages)
            if st.split_last_row and last_on_page and rest:
                carry = rest.pop()
            for extra in rest:
                top += 7.7
                p.text(119, top, extra, ROW)
            top += 13.7
        p.text(36, 820.2, "Statement Generated on 04 Nov 2026, 17:52", 10)
        p.text(519, 820.2, f"Page {pno} of {len(pages) + 1}", 10)
        c.showPage()

    p = Page(c)
    if st.summary:
        p.text(36, 90, "Account Summary", 12)
        p.text(36, 120.6, "Particulars Opening Balance Closing Balance", 9)
        p.text(36, 144, "Savings Account (XX):", 9)
        p.rtext(386, 144, money(st.opening), 9)
        p.rtext(529, 144, st.summary_closing_text or money(balance), 9)
    p.text(36, 236.5, "End of Statement", 12)
    c.showPage()
    c.save()
    return buf.getvalue()


# --- sample data -----------------------------------------------------------------------------


def sbi_sample(**kw) -> SbiStatement:
    D = Decimal
    txns = [
        SbiTxn("02/07/2026", ["UPI/DR/412345678901/COFFEE", "SHOP/HDFC/cafe@okhdfc/Pay"], debit=D("99.00")),
        SbiTxn("03/07/2026", ["UPI/DR/412345678902/GROCER/", "HDFC/grocer@ybl/Pay"], debit=D("1,170.00".replace(",", ""))),
        SbiTxn("04/07/2026", ["NEFT*UTIB0000001*AXN12345", "678*ACME LTD"], credit=D("54533.00"), lead="DEP TFR"),
        SbiTxn("05/07/2026", ["ATM WDL MG ROAD"], debit=D("2000.00"), lead=None, trailer=False),
        SbiTxn("06/07/2026", ["UPI/CR/412345678903/FRIEND/SBIN/f@oksbi/Rent"], credit=D("5000.00"), lead="DEP TFR"),
        SbiTxn("07/07/2026", ["INTEREST CREDIT"], credit=D("12.34"), lead=None, trailer=False),
        SbiTxn("08/07/2026", ["UPI/DR/", "412345678904/BOOKS/ICIC/b@icici/Pay"], debit=D("450.50")),
    ]
    return SbiStatement(opening=D("14380.73"), txns=txns, **kw)


def kotak_sample(**kw) -> KotakStatement:
    D = Decimal
    txns = [
        KotakTxn("01 Aug 2026", ["UPI/COFFEE SHOP/HDFC/612345678901/NO", "REMARKS"], ref="UPI-612345678901", debit=D("75.00")),
        KotakTxn("01 Aug 2026", ["UPI/FRIEND X/SBIN/612345678902/Payment", "from Phone"], ref="UPI-612345678902", credit=D("2000.00")),
        KotakTxn("03 Aug 2026", ["UPI/GROCER/YESB/612345678903/Sent"], ref="UPI-612345678903", debit=D("956.00")),
        KotakTxn("24 Aug 2026", ["SMS:SMS ALERT CHG FOR THE", "MONTH OF JUL26"], debit=D("14.87")),
        KotakTxn("13 Sep 2026", ["UPI/BOOKS/UTIB/612345678904/Pay", "(Value Date: 13-", "10-2026)"], ref="UPI-612345678904", debit=D("120.00")),
        KotakTxn("30 Sep 2026", ["Int.Pd:0000000000:01-07-2026", "to 30-09-2026"], credit=D("6.00")),
        KotakTxn("02 Oct 2026", ["UPI/RENT/ICIC/612345678905/October", "rent payment", "for flat"], ref="UPI-612345678905", debit=D("500.00")),
        KotakTxn("30 Oct 2026", ["UPI/SALARY/HDFC/612345678906/Pay"], ref="UPI-612345678906", credit=D("1000.00")),
    ]
    return KotakStatement(opening=D("1045.36"), txns=txns, **kw)
