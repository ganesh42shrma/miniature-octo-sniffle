from .base import BankParser
from .kotak import KotakParser
from .sbi import SbiParser

PARSERS: dict[str, BankParser] = {p.bank: p for p in (SbiParser(), KotakParser())}

__all__ = ["BankParser", "PARSERS"]
