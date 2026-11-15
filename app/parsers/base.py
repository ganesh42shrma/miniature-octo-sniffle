from __future__ import annotations

from abc import ABC, abstractmethod

import pdfplumber

from ..common import Statement


class BankParser(ABC):
    """One implementation per statement layout. See docs/layouts/<bank>.md for the rules."""

    bank: str
    version: str

    @abstractmethod
    def parse(self, pdf: pdfplumber.PDF) -> Statement:
        """Extracts the statement. Raises ParserError for anything it cannot vouch for."""
