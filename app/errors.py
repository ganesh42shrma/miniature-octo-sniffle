"""Error codes the service returns. Messages are safe to show to the user: they never contain statement text."""

from __future__ import annotations


class ParserError(Exception):
    status_code = 422

    def __init__(self, code: str, message: str, status_code: int | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        if status_code is not None:
            self.status_code = status_code


def invalid_file(message: str = "The file is not a readable PDF") -> ParserError:
    return ParserError("INVALID_FILE", message, 400)


def unsupported_bank(bank: str) -> ParserError:
    return ParserError("UNSUPPORTED_BANK", f"Unsupported bank '{bank}'. Use 'sbi', 'kotak' or 'auto'", 400)


def password_required() -> ParserError:
    return ParserError("PASSWORD_REQUIRED", "This PDF is password protected. Enter the PDF password", 401)


def wrong_password() -> ParserError:
    return ParserError("WRONG_PASSWORD", "Incorrect PDF password", 401)


def no_text_layer() -> ParserError:
    return ParserError("NO_TEXT_LAYER", "This PDF has no readable text (it looks scanned). Download the statement from net banking instead")


def bank_mismatch(expected: str, found: str | None) -> ParserError:
    names = {"sbi": "SBI", "kotak": "Kotak"}
    if found:
        msg = f"This looks like a {names.get(found, found)} statement, not {names.get(expected, expected)}"
    else:
        msg = f"This doesn't look like a {names.get(expected, expected)} statement"
    return ParserError("BANK_MISMATCH", msg)


def bank_unknown() -> ParserError:
    return ParserError("BANK_UNKNOWN", "Couldn't tell which bank this statement is from. Pick SBI or Kotak and try again")


def unsupported_layout(detail: str) -> ParserError:
    return ParserError("UNSUPPORTED_LAYOUT", f"Unrecognised statement layout: {detail}")


def reconciliation_failed(detail: str) -> ParserError:
    return ParserError("RECONCILIATION_FAILED", f"Statement figures don't add up: {detail}")
