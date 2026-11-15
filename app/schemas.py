"""Response models. Must stay compatible with `parserResponse` in squirl_backend/src/plugins/imports/import.validation.js."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel

from .common import Statement


def _num(value: Decimal | None) -> float | None:
    return None if value is None else float(value.quantize(Decimal("0.01")))


class TransactionOut(BaseModel):
    date: str
    description: str
    refNo: str | None
    debit: float | None
    credit: float | None
    balance: float | None


class SummaryOut(BaseModel):
    opening: float
    closing: float | None
    count: int
    totalDebits: float
    totalCredits: float
    parserVersion: str


class ParseResponse(BaseModel):
    bank: str
    periodFrom: str | None
    periodTo: str | None
    transactions: list[TransactionOut]
    summary: SummaryOut

    @classmethod
    def from_statement(cls, bank: str, version: str, stmt: Statement) -> "ParseResponse":
        return cls(
            bank=bank,
            periodFrom=stmt.period_from.isoformat() if stmt.period_from else None,
            periodTo=stmt.period_to.isoformat() if stmt.period_to else None,
            transactions=[
                TransactionOut(
                    date=r.date.isoformat(),
                    description=r.description,
                    refNo=r.ref_no,
                    debit=_num(r.debit),
                    credit=_num(r.credit),
                    balance=_num(r.balance),
                )
                for r in stmt.rows
            ],
            summary=SummaryOut(
                opening=_num(stmt.opening),
                closing=_num(stmt.closing),
                count=len(stmt.rows),
                totalDebits=_num(sum((r.debit or Decimal(0) for r in stmt.rows), Decimal(0))),
                totalCredits=_num(sum((r.credit or Decimal(0) for r in stmt.rows), Decimal(0))),
                parserVersion=version,
            ),
        )


class ErrorResponse(BaseModel):
    # The backend shows `error` to the user as-is; `code` lets it pick a next step.
    error: str
    code: str
