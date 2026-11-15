import io

import pytest
from fastapi.testclient import TestClient
from reportlab.pdfgen import canvas

from app.main import app

from .builders import build_kotak, build_sbi, kotak_sample, sbi_sample

client = TestClient(app)


def post(data: bytes, bank: str, password: str | None = None, name="s.pdf"):
    form = {"bank": bank}
    if password is not None:
        form["password"] = password
    return client.post("/parse", files={"file": (name, data, "application/pdf")}, data=form)


@pytest.fixture(scope="module")
def sbi_encrypted():
    return build_sbi(sbi_sample(password="pw123"))


@pytest.fixture(scope="module")
def kotak_pdf():
    return build_kotak(kotak_sample())


def test_health():
    assert client.get("/health").json() == {"status": "ok", "banks": ["kotak", "sbi"]}


def test_parse_sbi_success_matches_backend_contract(sbi_encrypted):
    res = post(sbi_encrypted, "sbi", "pw123")
    assert res.status_code == 200
    body = res.json()
    assert body["bank"] == "sbi" and body["periodFrom"] == "2026-07-01" and body["periodTo"] == "2026-09-30"
    assert len(body["transactions"]) == 7
    tx = body["transactions"][0]
    assert set(tx) == {"date", "description", "refNo", "debit", "credit", "balance"}
    assert tx["date"] == "2026-07-02" and tx["debit"] == 99.0 and tx["credit"] is None
    assert body["summary"]["count"] == 7 and body["summary"]["parserVersion"] == "sbi-1"


def test_parse_kotak_success(kotak_pdf):
    res = post(kotak_pdf, "KOTAK")  # bank is case-insensitive
    assert res.status_code == 200
    assert len(res.json()["transactions"]) == 8


def test_password_required(sbi_encrypted):
    res = post(sbi_encrypted, "sbi")
    assert res.status_code == 401 and res.json()["code"] == "PASSWORD_REQUIRED"


def test_wrong_password(sbi_encrypted):
    res = post(sbi_encrypted, "sbi", "nope")
    assert res.status_code == 401 and res.json()["code"] == "WRONG_PASSWORD"
    # Backend contract: `error` is a plain string it can show to the user.
    assert isinstance(res.json()["error"], str)


def test_bank_mismatch(kotak_pdf):
    res = post(kotak_pdf, "sbi")
    assert res.status_code == 422 and res.json()["code"] == "BANK_MISMATCH"
    assert "Kotak" in res.json()["error"]


def test_not_a_pdf():
    res = post(b"hello world", "sbi")
    assert res.status_code == 400 and res.json()["code"] == "INVALID_FILE"


def test_unsupported_bank(kotak_pdf):
    res = post(kotak_pdf, "hdfc")
    assert res.status_code == 400 and res.json()["code"] == "UNSUPPORTED_BANK"


def test_missing_fields():
    res = client.post("/parse", data={"bank": "sbi"})
    assert res.status_code == 400 and res.json()["code"] == "INVALID_REQUEST"


def test_scanned_pdf_has_no_text():
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.rect(50, 50, 200, 200, fill=1)
    c.showPage()
    c.save()
    res = post(buf.getvalue(), "sbi")
    assert res.status_code == 422 and res.json()["code"] == "NO_TEXT_LAYER"


def test_reconciliation_failure_returns_422():
    res = post(build_sbi(sbi_sample(tamper_balance_at=1)), "sbi")
    assert res.status_code == 422 and res.json()["code"] == "RECONCILIATION_FAILED"


def test_file_too_large_by_content_length(monkeypatch, kotak_pdf):
    from app import main

    monkeypatch.setattr(main, "MAX_BODY_BYTES", 1000)
    res = post(kotak_pdf, "kotak")
    assert res.status_code == 400 and res.json()["code"] == "INVALID_FILE"


def test_file_too_large_after_reading(monkeypatch, kotak_pdf):
    from app import main

    monkeypatch.setattr(main, "MAX_FILE_BYTES", 1000)
    res = post(kotak_pdf, "kotak")
    assert res.status_code == 400 and res.json()["code"] == "INVALID_FILE"


def test_chunked_oversized_upload_reports_invalid_file(monkeypatch, kotak_pdf):
    from app import main

    monkeypatch.setattr(main, "MAX_BODY_BYTES", 4096)
    boundary = "xyz"
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"bank\"\r\n\r\nkotak\r\n"
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"s.pdf\"\r\n"
        f"Content-Type: application/pdf\r\n\r\n"
    ).encode() + kotak_pdf + f"\r\n--{boundary}--\r\n".encode()

    def chunks():  # a generator body is sent chunked, without Content-Length
        for i in range(0, len(body), 1024):
            yield body[i : i + 1024]

    res = client.post("/parse", content=chunks(), headers={"content-type": f"multipart/form-data; boundary={boundary}"})
    assert res.status_code == 400 and res.json()["code"] == "INVALID_FILE"


def test_method_not_allowed_keeps_allow_header():
    res = client.post("/health")
    assert res.status_code == 405 and res.json()["code"] == "METHOD_NOT_ALLOWED"
    assert "GET" in res.headers.get("allow", "")


def test_uploads_are_not_spooled_to_disk():
    from starlette.formparsers import MultiPartParser

    from app import main

    assert MultiPartParser.spool_max_size >= main.MAX_BODY_BYTES


def test_malformed_multipart_uses_error_envelope():
    res = client.post("/parse", content=b"garbage", headers={"content-type": "multipart/form-data"})
    assert res.status_code == 400
    assert set(res.json()) == {"error", "code"} and res.json()["code"] == "INVALID_REQUEST"


def test_unexpected_error_is_contained(monkeypatch, kotak_pdf, caplog):
    from app.parsers import PARSERS

    def boom(_pdf):
        raise RuntimeError("SECRET STATEMENT TEXT")

    monkeypatch.setattr(PARSERS["kotak"], "parse", boom)
    with TestClient(app, raise_server_exceptions=True) as strict:
        res = strict.post("/parse", files={"file": ("s.pdf", kotak_pdf, "application/pdf")}, data={"bank": "kotak"})
    assert res.status_code == 500 and res.json()["code"] == "INTERNAL_ERROR"
    assert "SECRET" not in res.text
    assert "SECRET" not in caplog.text


def test_auto_detects_bank(kotak_pdf, sbi_encrypted):
    res = post(kotak_pdf, "auto")
    assert res.status_code == 200 and res.json()["bank"] == "kotak"
    res = post(sbi_encrypted, "AUTO", "pw123")
    assert res.status_code == 200 and res.json()["bank"] == "sbi" and len(res.json()["transactions"]) == 7


def test_auto_with_unknown_bank():
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(72, 720, "Some Other Bank account statement")
    c.save()
    res = post(buf.getvalue(), "auto")
    assert res.status_code == 422 and res.json()["code"] == "BANK_UNKNOWN"
