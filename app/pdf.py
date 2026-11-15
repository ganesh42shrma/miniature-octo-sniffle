"""Opening PDFs in memory and pulling out the pieces the parsers need."""

from __future__ import annotations

import io
import re
from contextlib import contextmanager
from typing import Iterator

import pdfplumber
from pdfminer.pdfdocument import PDFPasswordIncorrect
from pdfminer.pdfparser import PDFSyntaxError
from pdfplumber.utils.exceptions import MalformedPDFException, PdfminerException

from . import errors


@contextmanager
def open_pdf(data: bytes, password: str | None) -> Iterator[pdfplumber.PDF]:
    """Opens a PDF from bytes (never touches disk). Maps failures to parser error codes."""
    if not data.startswith(b"%PDF-"):
        raise errors.invalid_file()
    try:
        pdf = pdfplumber.open(io.BytesIO(data), password=password or "")
        _ = pdf.pages  # force the document (and decryption) to load
    except (PdfminerException, MalformedPDFException, PDFPasswordIncorrect, PDFSyntaxError, ValueError, KeyError, TypeError) as exc:
        # pdfplumber wraps pdfminer errors: PdfminerException(<original>). Unwrap to classify.
        cause = exc.args[0] if isinstance(exc, PdfminerException) and exc.args else exc
        if isinstance(cause, PDFPasswordIncorrect):
            raise errors.wrong_password() if password else errors.password_required()
        # The type is enough; messages from PDF libraries can quote document content.
        raise errors.invalid_file(f"The file is not a readable PDF ({type(cause).__name__})")
    try:
        if not pdf.pages:
            raise errors.invalid_file("The PDF has no pages")
        yield pdf
    finally:
        pdf.close()


def require_text(pdf: pdfplumber.PDF) -> None:
    if not any(page.chars for page in pdf.pages[:2]):
        raise errors.no_text_layer()


def detect_bank(pdf: pdfplumber.PDF) -> str | None:
    """Best guess at the issuing bank from the first page's text."""
    text = pdf.pages[0].extract_text() or ""
    if re.search(r"State Bank of India|\bSBIN\d", text, re.I):
        return "sbi"
    if re.search(r"Kotak|\bKKBK\d", text, re.I):
        return "kotak"
    return None


def words(page) -> list[dict]:
    return page.extract_words(keep_blank_chars=False, use_text_flow=False)


def horizontal_borders(page, min_width: float = 5, merge_tol: float = 1.5) -> list[float]:
    """y positions of horizontal ruling (lines and rect edges), merged when within `merge_tol`."""
    tops = sorted(
        e["top"] for e in page.edges if e["orientation"] == "h" and e["x1"] - e["x0"] > min_width
    )
    merged: list[float] = []
    for t in tops:
        if not merged or t - merged[-1] > merge_tol:
            merged.append(t)
    return merged
