"""Parser behaviour on synthetic statements built to the layout specs."""

from decimal import Decimal as D

import pytest

from app.common import reconcile
from app.errors import ParserError
from app.parsers import PARSERS
from app.pdf import open_pdf

from .builders import build_kotak, build_sbi, kotak_sample, sbi_sample


def parse(bank, data, password=None):
    with open_pdf(data, password) as pdf:
        stmt = PARSERS[bank].parse(pdf)
    reconcile(stmt)
    return stmt


# --- SBI -------------------------------------------------------------------------------------


def test_sbi_parses_and_reconciles():
    stmt = parse("sbi", build_sbi(sbi_sample()))
    assert len(stmt.rows) == 7
    assert str(stmt.period_from) == "2026-07-01" and str(stmt.period_to) == "2026-09-30"
    assert stmt.opening == D("14380.73")
    assert stmt.totals["debit_count"] == 4 and stmt.totals["credit_count"] == 3

    first = stmt.rows[0]
    assert str(first.date) == "2026-07-02"
    assert first.debit == D("99.00") and first.credit is None
    # Lead line kept, wrapped UPI string joined, "<13d> AT <5d>" + branch lines dropped.
    assert first.description == "WDL TFR UPI/DR/412345678901/COFFEE SHOP/HDFC/cafe@okhdfc/Pay"
    assert first.ref_no == "412345678901"

    assert stmt.rows[1].description == "WDL TFR UPI/DR/412345678902/GROCER/HDFC/grocer@ybl/Pay"
    neft = stmt.rows[2]
    # UTR is hard-wrapped ("AXN12345" + "678*ACME LTD"); refNo rejoins it, the description keeps the printed text.
    assert neft.credit == D("54533.00") and neft.ref_no == "AXN12345678"
    assert neft.description == "DEP TFR NEFT*UTIB0000001*AXN12345 678*ACME LTD"
    atm = stmt.rows[3]
    assert atm.description == "ATM WDL MG ROAD" and atm.ref_no is None
    assert stmt.rows[5].description == "INTEREST CREDIT"
    assert stmt.rows[6].description == "WDL TFR UPI/DR/412345678904/BOOKS/ICIC/b@icici/Pay"
    assert stmt.rows[6].ref_no == "412345678904"


@pytest.mark.parametrize("tail", [1, 2, 3])
@pytest.mark.parametrize("borders", [True, False])
def test_sbi_row_split_across_pages_matches_unsplit(tail, borders):
    """tail=1: branch line on next page; 2: AT line + branch; 3: also the UPI ref continuation line.
    The result must be identical to the unsplit statement (descriptions feed the dedupe hash)."""
    base = parse("sbi", build_sbi(sbi_sample(per_page=20)))
    split = parse("sbi", build_sbi(sbi_sample(per_page=2, split_tail=tail, borders=borders)))
    assert [(r.description, r.ref_no, r.balance) for r in split.rows] == [
        (r.description, r.ref_no, r.balance) for r in base.rows
    ]


@pytest.mark.parametrize(
    "desc,ref",
    [
        ("DEP TFR NEFT*UTIB0000001*AXN12345 678*ACME LTD", "AXN12345678"),
        ("DEP TFR NEFT*UTIB0000001*AXN12345678", "AXN12345678"),
        ("DEP TFR NEFT*UTIB0000001*AXN12345 678", None),  # wrapped, no closing '*': ambiguous
    ],
)
def test_sbi_neft_ref(desc, ref):
    from app.parsers.sbi import SbiParser

    assert SbiParser._ref_from_description(desc) == ref


def test_sbi_invalid_date_is_a_layout_error():
    with pytest.raises(ParserError) as e:
        parse("sbi", build_sbi(sbi_sample(bad_date_at=2)))
    assert e.value.code == "UNSUPPORTED_LAYOUT"


def test_sbi_without_borders_falls_back_to_gap_rule():
    stmt = parse("sbi", build_sbi(sbi_sample(borders=False)))
    assert len(stmt.rows) == 7
    assert stmt.rows[0].description.startswith("WDL TFR UPI/DR/")


def test_sbi_all_on_one_page():
    assert len(parse("sbi", build_sbi(sbi_sample(per_page=20))).rows) == 7


def test_sbi_balance_break_is_rejected():
    with pytest.raises(ParserError) as e:
        parse("sbi", build_sbi(sbi_sample(tamper_balance_at=3)))
    assert e.value.code == "RECONCILIATION_FAILED"


def test_sbi_printed_totals_mismatch_is_rejected():
    with pytest.raises(ParserError) as e:
        parse("sbi", build_sbi(sbi_sample(summary_debit_total_delta=D("1.00"))))
    assert "total debits" in e.value.message


def test_sbi_encrypted():
    stmt = parse("sbi", build_sbi(sbi_sample(password="secret")), password="secret")
    assert len(stmt.rows) == 7


# --- Kotak -----------------------------------------------------------------------------------


def test_kotak_parses_and_reconciles():
    stmt = parse("kotak", build_kotak(kotak_sample()))
    assert len(stmt.rows) == 8
    assert str(stmt.period_from) == "2026-08-01" and str(stmt.period_to) == "2026-10-31"
    assert stmt.opening == D("1045.36")
    assert stmt.closing == stmt.rows[-1].balance

    first = stmt.rows[0]
    assert first.description == "UPI/COFFEE SHOP/HDFC/612345678901/NO REMARKS"
    assert first.ref_no == "UPI-612345678901"
    assert stmt.rows[3].ref_no is None  # SMS charge
    assert stmt.rows[4].description == "UPI/BOOKS/UTIB/612345678904/Pay (Value Date: 13-10-2026)"
    assert stmt.rows[6].description == "UPI/RENT/ICIC/612345678905/October rent payment for flat"


def test_kotak_row_split_across_pages():
    stmt = parse("kotak", build_kotak(kotak_sample(per_page=7, split_last_row=True)))
    # Row 7 is last on page 1; its final line "for flat" is printed at the top of page 2.
    assert stmt.rows[6].description == "UPI/RENT/ICIC/612345678905/October rent payment for flat"
    assert len(stmt.rows) == 8


def test_kotak_serial_gap_is_rejected():
    with pytest.raises(ParserError) as e:
        parse("kotak", build_kotak(kotak_sample(skip_serial=True)))
    assert e.value.code == "RECONCILIATION_FAILED"


def test_kotak_unreadable_summary_is_rejected():
    with pytest.raises(ParserError) as e:
        parse("kotak", build_kotak(kotak_sample(summary_closing_text="N/A")))
    assert e.value.code == "UNSUPPORTED_LAYOUT"


def test_kotak_without_summary_still_checks_running_balance():
    stmt = parse("kotak", build_kotak(kotak_sample(summary=False)))
    assert stmt.closing is None and len(stmt.rows) == 8
