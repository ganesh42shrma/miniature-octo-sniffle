"""The redaction script protects real statements during layout analysis; test its masking."""

import re

from scripts.redact_samples import Redactor


def checks():
    # check_redaction.py runs its scan on import, so read its regex from the source instead.
    src = open("scripts/check_redaction.py").read()
    pattern = re.search(r'"unmasked handle/email": re\.compile\(r"(.+?)"\)', src).group(1)
    return re.compile(pattern)


def test_masks_names_numbers_and_handles():
    r = Redactor(["Ravi Kumar"])
    out = r("Ravi Kumar UPI/DR/412345678901/Ramesh/HDFC/ramesh99@okhdfc 1313 Block 560091")
    assert "Ravi" not in out and "Kumar" not in out and "Ramesh" not in out
    assert "412345678901" not in out and "1313" not in out and "560091" not in out
    assert "ramesh99" not in out
    assert "UPI/DR/" in out and "HDFC" in out


def test_keeps_dates_and_amounts():
    r = Redactor([])
    out = r("02/07/2026 01 Aug 2026 1,23,456.78 14,380.73CR 99.00")
    assert out == "02/07/2026 01 Aug 2026 1,23,456.78 14,380.73CR 99.00"


def test_masks_non_ascii_names():
    out = Redactor([])("राम कुमार 张三 José")
    assert all(ord(c) < 128 for c in out)


def test_leak_check_flags_unmasked_handles_only():
    rx = checks()
    assert rx.search("pay alice@example.com")
    assert rx.search("ramesh99@okhdfc")
    assert rx.search("alice@123bank.com")
    assert not rx.search("xxxxx.xxx@okhdfc")
    assert not rx.search("[Helvetica@8.0]")
    assert not rx.search("[SourceSans3-Regular@7.7, SourceSans3-SemiBold@9.0]")
