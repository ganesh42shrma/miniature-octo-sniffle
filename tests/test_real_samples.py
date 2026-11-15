"""Local-only: the real statements in samples/private/. Skipped when they aren't present.
Assertions use counts and totals only, so failures never print statement text."""

from decimal import Decimal as D

import pytest

from app.common import reconcile
from app.parsers import PARSERS
from app.pdf import detect_bank, open_pdf
from scripts.redact_samples import PRIVATE, ROOT, load_env

ENV = load_env(ROOT / ".env")

CASES = [
    # bank, file, rows, opening, closing
    ("sbi", "SBI_ACC_STATEMENT.pdf", 216, D("14380.73"), D("30006.11")),
    ("kotak", "KOTAK_ACC_STATE.pdf", 229, D("45.36"), D("61.38")),
]


@pytest.mark.parametrize("bank,fname,rows,opening,closing", CASES)
def test_real_statement(bank, fname, rows, opening, closing):
    path = PRIVATE / fname
    if not path.exists():
        pytest.skip(f"{fname} not present")
    with open_pdf(path.read_bytes(), ENV.get(f"{bank.upper()}_PDF_PASSWORD")) as pdf:
        assert detect_bank(pdf) == bank
        stmt = PARSERS[bank].parse(pdf)
    reconcile(stmt)
    assert len(stmt.rows) == rows
    assert stmt.opening == opening and stmt.closing == closing
    assert all(r.description for r in stmt.rows)
