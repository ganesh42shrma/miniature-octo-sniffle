"""
Extract layout information from real bank statements and write a REDACTED copy.

Raw text never leaves this process: every string is masked before it is written,
and the script prints only counts. Output keeps what defines a layout (dates,
amounts, column x-positions, banking keywords, line structure) and masks what
identifies people (names, addresses, account/ref/phone numbers, UPI IDs, emails).

Usage:  uv run python scripts/redact_samples.py
Input:  samples/private/*.pdf   (bank inferred from filename: SBI / KOTAK)
        .env  -> SBI_PDF_PASSWORD, KOTAK_PDF_PASSWORD (optional), REDACT_TERMS (comma list)
Output: samples/redacted/<bank>.txt
"""

from __future__ import annotations

import re
import sys
import unicodedata
from pathlib import Path

import pdfplumber

ROOT = Path(__file__).resolve().parent.parent
PRIVATE = ROOT / "samples" / "private"
OUT = ROOT / "samples" / "redacted"

# Banking vocabulary that carries layout meaning (kept unmasked).
KEYWORDS = {
    "upi", "neft", "imps", "rtgs", "atm", "pos", "ecs", "nach", "ach", "chq", "cheque", "ifsc",
    "ifs", "micr", "cif", "inr", "rs", "dr", "cr", "bil", "onl", "sbi", "sbin", "kotak", "kkbk",
    "mb", "ib", "txn", "ref", "refno", "no", "a/c", "ac", "acct", "int", "pd", "pcd", "nwd",
    "cms", "ach", "si", "mmt", "ft", "bna", "cdm", "ckyc", "kyc", "pan", "gst", "gstin",
    "tds", "sb", "ca", "od", "fd", "rd", "ppf", "emi", "nfs", "visa", "rupay", "mastercard",
    "debit", "credit", "withdrawal", "withdrawals", "deposit", "deposits", "balance",
    "narration", "particulars", "description", "opening", "closing", "statement", "summary",
    "branch", "account", "nominee", "nomination", "registered", "customer", "period",
    "transaction", "transactions", "value", "date", "total", "page", "dt", "amt",
    "yesb", "hdfc", "icic", "utib", "pytm", "barb", "punb", "cnrb", "ubin", "idib", "ioba",
    "airp", "fdrl", "indb", "idfb", "aubl", "ybl", "okaxis", "oksbi", "okhdfcbank",
    "okicici", "paytm", "axl", "ibl", "apl", "upi", "dep", "tfr", "trf", "transfer",
    "by", "to", "from", "via", "payment", "rev", "reversal", "charges", "chgs", "sms",
    "interest", "salary", "refund", "cashback", "mandate", "autopay", "bulk", "posting",
    "mobile", "email", "address", "name", "joint", "holder", "holders", "currency",
    "drawing", "power", "mod", "balance", "cleared", "uncleared", "hold", "lien",
    "self", "cash", "clg", "inward", "outward", "return", "rtn", "ret",
}

# Fixed label / boilerplate words printed by the banks. Deliberately NOT a general dictionary:
# merchant names, UPI remarks and address words are personal and must be masked.
LABELS = {
    "statement", "of", "account", "summary", "welcome", "as", "on", "the", "and", "for", "in",
    "at", "is", "this", "with", "or", "an", "a", "be", "are", "not", "has", "have", "if", "any",
    "clear", "uncleared", "amount", "limit", "lien", "drawing", "power", "interest", "rate",
    "product", "status", "open", "opened", "active", "dormant", "type", "code", "phone", "number",
    "id", "monthly", "avg", "average", "min", "minimum", "max", "bank", "state", "india",
    "mahindra", "ltd", "limited", "savings", "saving", "regular", "current", "lotus", "edge",
    "generated", "details", "end", "computer", "signature", "required", "does", "require",
    "please", "contact", "us", "our", "your", "you", "we", "call", "visit", "www", "com", "co",
    "net", "banking", "nri", "resident", "individual", "sr", "serial", "chq", "dr.", "cr.",
    "yes", "true", "false", "na", "nil", "sweep", "linked", "deposit", "fixed", "recurring",
    "crn", "ckyc", "joint", "single", "operation", "mode", "relationship", "manager",
    "pa", "p.a", "rupee", "rupees", "indian", "only", "inr", "sl", "description", "remarks",
    "post", "posted", "txn", "tran", "ref", "reference", "no.", "cheque", "instrument",
    "date", "value", "debits", "credits", "count", "brought", "forward", "carried", "b/f", "c/f",
    "abbreviations", "used", "important", "note", "notes", "information", "disclaimer",
    "contents", "deemed", "correct", "error", "errors", "reported", "within", "days", "receipt",
    "unless", "report", "discrepancy", "immediately", "nearest", "toll", "free", "customer",
    "care", "service", "services", "grievance", "officer", "nodal", "principal",
    "by", "to", "from", "via", "per", "upto", "till", "since", "time", "times", "hrs",
}

MONTHS = {
    "jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
    "january", "february", "march", "april", "june", "july", "august", "september",
    "october", "november", "december",
}


def load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.split(" #", 1)[0].strip().strip('"').strip("'")
        env[key.strip()] = value
    return env


class Redactor:
    TOKEN = re.compile(r"[A-Za-z]+|\d+|[^A-Za-z\d]+")
    EMAIL_UPI = re.compile(r"([A-Za-z0-9._\-+]+)@([A-Za-z0-9.\-]+)")
    AMOUNT = re.compile(r"^\d{1,3}(,\d{2,3})*(\.\d{1,2})?$|^\d+\.\d{2}$")

    def __init__(self, terms: list[str]):
        # Longest first so "First Last" is masked before "First".
        # Each term is also split into its words (>=3 chars) because statements rarely print
        # a name/address exactly as typed (order, initials, line breaks differ).
        pieces = {p for t in terms for p in re.split(r"\W+", t) if len(p) >= 3}
        whole = {t.strip() for t in terms if t.strip()}
        self.terms = [
            re.compile(r"(?<![A-Za-z])" + re.escape(t) + r"(?![A-Za-z])", re.IGNORECASE)
            for t in sorted(whole | pieces, key=len, reverse=True)
        ]
        self.allowed = KEYWORDS | LABELS | MONTHS
        self.stats = {"terms": 0, "handles": 0, "words": 0, "numbers": 0}

    @staticmethod
    def _mask_non_ascii(text: str) -> str:
        """Masks every non-ASCII letter, mark or digit (Devanagari, CJK, combining accents...).
        The token rules below only understand ASCII, so these would otherwise pass through."""
        return "".join(
            "x" if ord(c) > 127 and unicodedata.category(c)[0] in "LMN" else c for c in text
        )

    @staticmethod
    def _shape(s: str) -> str:
        return "".join("X" if c.isupper() else "x" if c.islower() else "9" if c.isdigit() else c for c in s)

    def _mask_word(self, w: str) -> str:
        if w.lower() in self.allowed:
            return w
        self.stats["words"] += 1
        return self._shape(w)

    def _mask_digits(self, tok: str, before: str, after: str) -> str:
        # Keep 1-3 digit runs (day/month, serials, amount groups), 4-digit years, and the
        # integer part of amounts (123456.78 / ,075). Mask everything else: house numbers,
        # branch codes, PINs, account / ref / phone numbers.
        if len(tok) <= 3:
            return tok
        # Indian amount groups after a comma are <=3 digits (kept above), so a comma prefix
        # never justifies keeping a longer run (that is how "City,560091" PINs look).
        is_amount_part = after.startswith(".") and len(after) >= 3 and after[1:3].isdigit() and not before.endswith(",")
        if is_amount_part and len(tok) <= 8:
            return tok
        if len(tok) == 4 and tok[:2] in ("19", "20"):
            return tok
        self.stats["numbers"] += 1
        return "9" * len(tok)

    def __call__(self, text: str | None) -> str:
        if not text:
            return text or ""
        for pattern in self.terms:
            text, n = pattern.subn("[REDACTED]", text)
            self.stats["terms"] += n

        def handle(m: re.Match) -> str:
            self.stats["handles"] += 1
            return self._shape(m.group(1)).replace("X", "x").replace("9", "x")[:12] + "@" + m.group(2)

        text = self.EMAIL_UPI.sub(handle, text)
        text = self._mask_non_ascii(text)

        tokens = self.TOKEN.findall(text)
        out = []
        for i, tok in enumerate(tokens):
            if tok.isalpha():
                # Leave already-masked handles / [REDACTED] alone.
                if tok in ("REDACTED",) or (set(tok) <= {"x", "X"} and i + 1 < len(tokens) and tokens[i + 1].startswith("@")):
                    out.append(tok)
                else:
                    out.append(self._mask_word(tok))
            elif tok.isdigit():
                before = tokens[i - 1] if i else ""
                after = "".join(tokens[i + 1 : i + 3])
                out.append(self._mask_digits(tok, before, after))
            else:
                out.append(tok)
        return "".join(out)


def group_lines(words: list[dict], tol: float = 2.5) -> list[list[dict]]:
    lines: list[list[dict]] = []
    for w in sorted(words, key=lambda w: (round(w["top"]), w["x0"])):
        if lines and abs(lines[-1][0]["top"] - w["top"]) <= tol:
            lines[-1].append(w)
        else:
            lines.append([w])
    return [sorted(line, key=lambda w: w["x0"]) for line in lines]


def describe_pdf(path: Path, password: str | None, redact: Redactor) -> str:
    out: list[str] = []
    with pdfplumber.open(path, password=password or "") as pdf:
        out.append(f"# FILE: {path.name}")
        out.append(f"# pages: {len(pdf.pages)}  encrypted: {bool(password)}")
        for pno, page in enumerate(pdf.pages, start=1):
            out.append("")
            out.append("=" * 100)
            out.append(f"PAGE {pno}  size={page.width:.0f}x{page.height:.0f}  "
                       f"chars={len(page.chars)} lines={len(page.lines)} rects={len(page.rects)} images={len(page.images)}")
            out.append("=" * 100)

            out.append("\n--- LAYOUT TEXT (pdfplumber extract_text(layout=True)) ---")
            text = page.extract_text(layout=True) or ""
            out.extend(redact(line).rstrip() for line in text.splitlines())

            out.append("\n--- WORD POSITIONS (one row per visual line: top | x0:word ...) ---")
            words = page.extract_words(keep_blank_chars=False, use_text_flow=False, extra_attrs=["fontname", "size"])
            for line in group_lines(words):
                fonts = sorted({f"{w['fontname'].split('+')[-1]}@{w['size']:.1f}" for w in line})
                cells = "  ".join(f"{w['x0']:.0f}-{w['x1']:.0f}:{redact(w['text'])}" for w in line)
                out.append(f"top={line[0]['top']:6.1f} | {cells}   [{', '.join(fonts)}]")

            tables = page.extract_tables()
            out.append(f"\n--- TABLES (extract_tables, default settings): {len(tables)} found ---")
            for tno, table in enumerate(tables, start=1):
                out.append(f"[table {tno}] rows={len(table)} cols={max((len(r) for r in table), default=0)}")
                for row in table:
                    out.append(" | ".join(redact(c).replace("\n", "⏎") if c else "∅" for c in row))
    return "\n".join(out) + "\n"


def main() -> int:
    env = load_env(ROOT / ".env")
    terms = [t for t in env.get("REDACT_TERMS", "").split(",") if t.strip()]
    redact = Redactor(terms)
    OUT.mkdir(parents=True, exist_ok=True)

    pdfs = sorted(PRIVATE.glob("*.pdf"))
    if not pdfs:
        print("No PDFs found in samples/private/")
        return 1

    for path in pdfs:
        name = path.stem.lower()
        bank = "sbi" if "sbi" in name else "kotak" if "kotak" in name else name
        password = env.get(f"{bank.upper()}_PDF_PASSWORD") or None
        before = dict(redact.stats)
        try:
            content = describe_pdf(path, password, redact)
        except Exception as exc:  # never echo content; type is enough to debug
            print(f"[{bank}] FAILED: {type(exc).__name__}")
            continue
        target = OUT / f"{bank}.txt"
        target.write_text(content)
        delta = {k: redact.stats[k] - before[k] for k in redact.stats}
        print(f"[{bank}] wrote {target.relative_to(ROOT)} ({len(content.splitlines())} lines) masked={delta}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
