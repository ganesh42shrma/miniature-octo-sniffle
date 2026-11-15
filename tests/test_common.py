from datetime import date
from decimal import Decimal as D

import pytest

from app.common import Row, Statement, join_description, parse_amount, reconcile
from app.errors import ParserError


@pytest.mark.parametrize(
    "text,expected",
    [
        ("1,23,456.78", D("123456.78")),
        ("123,456.78", D("123456.78")),
        ("99.00", D("99.00")),
        ("14,380.73CR", D("14380.73")),
        ("14,380.73DR", D("-14380.73")),
        ("-5.00", D("-5.00")),
        ("0.00", D("0.00")),
    ],
)
def test_parse_amount(text, expected):
    assert parse_amount(text) == expected


@pytest.mark.parametrize("text", ["-", "", "abc", "12", "1.2", None, "UPI-123"])
def test_parse_amount_rejects(text):
    assert parse_amount(text) is None


@pytest.mark.parametrize(
    "parts,expected",
    [
        (["UPI/DR/123/SHOP/", "HDFC/x@ybl/Pay"], "UPI/DR/123/SHOP/HDFC/x@ybl/Pay"),
        (["UPI/DR/123/SHOP", "/HDFC/Pay"], "UPI/DR/123/SHOP/HDFC/Pay"),
        (["Pay (Value Date: 13-", "10-2026)"], "Pay (Value Date: 13-10-2026)"),
        (["WDL TFR", "UPI/DR/1", "", "  more  text "], "WDL TFR UPI/DR/1 more text"),
        ([], ""),
    ],
)
def test_join_description(parts, expected):
    assert join_description(parts) == expected


def _stmt(rows, opening="100.00", closing="150.00", **kw):
    return Statement(date(2026, 7, 1), date(2026, 7, 31), D(opening), D(closing) if closing else None, rows, **kw)


def _row(day, debit=None, credit=None, balance="0"):
    return Row(date(2026, 7, day), "x", None, D(debit) if debit else None, D(credit) if credit else None, D(balance))


def test_reconcile_ok():
    reconcile(_stmt([_row(1, debit="50.00", balance="50.00"), _row(2, credit="100.00", balance="150.00")]))


def test_reconcile_running_balance_break():
    with pytest.raises(ParserError) as e:
        reconcile(_stmt([_row(1, debit="50.00", balance="51.00")], closing=None))
    assert e.value.code == "RECONCILIATION_FAILED" and "row 1" in e.value.message


def test_reconcile_closing_mismatch():
    with pytest.raises(ParserError) as e:
        reconcile(_stmt([_row(1, debit="50.00", balance="50.00")], closing="60.00"))
    assert e.value.code == "RECONCILIATION_FAILED"


def test_reconcile_printed_totals():
    rows = [_row(1, debit="50.00", balance="50.00")]
    with pytest.raises(ParserError) as e:
        reconcile(_stmt(rows, closing="50.00", totals={"total_debits": D("49.00")}))
    assert "total debits" in e.value.message


def test_reconcile_both_debit_and_credit():
    with pytest.raises(ParserError):
        reconcile(_stmt([_row(1, debit="1.00", credit="1.00", balance="100.00")], closing=None))


def test_reconcile_date_outside_period():
    row = Row(date(2026, 8, 5), "x", None, D("1.00"), None, D("99.00"))
    with pytest.raises(ParserError) as e:
        reconcile(_stmt([row], closing=None))
    assert "outside" in e.value.message


def test_reconcile_no_rows():
    with pytest.raises(ParserError) as e:
        reconcile(_stmt([], closing=None))
    assert e.value.code == "UNSUPPORTED_LAYOUT"


def test_reconcile_negative_amount_rejected():
    # A negative debit reconciles arithmetically but the backend stores abs() as a debit.
    with pytest.raises(ParserError) as e:
        reconcile(_stmt([_row(1, debit="-50.00", balance="150.00")], closing=None))
    assert "negative" in e.value.message


def test_reconcile_negative_balance_allowed():
    reconcile(_stmt([_row(1, debit="150.00", balance="-50.00")], closing="-50.00"))


def test_reconcile_dates_must_not_go_backwards():
    rows = [_row(2, debit="10.00", balance="90.00"), _row(1, debit="10.00", balance="80.00")]
    with pytest.raises(ParserError) as e:
        reconcile(_stmt(rows, closing=None))
    assert "before the row above" in e.value.message
