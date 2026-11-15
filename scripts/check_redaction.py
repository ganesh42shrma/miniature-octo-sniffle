"""Scan redacted output for leftover identifiers. Prints counts only, never matched text."""
import re, sys, unicodedata
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from redact_samples import load_env, ROOT

env = load_env(ROOT / ".env")
terms = [t.strip() for t in env.get("REDACT_TERMS", "").split(",") if t.strip()]
pieces = sorted({p for t in terms for p in re.split(r"\W+", t) if len(p) >= 3})
print(f"REDACT_TERMS: {len(terms)} terms, {len(pieces)} word-pieces (lengths {[len(p) for p in pieces]})")
checks = {
    "digit runs >=9 (unmasked)": re.compile(r"(?<![\d,])(?!9+(?!\d))\d{9,}(?!\d)"),
    "digit runs 6-8 (unmasked)": re.compile(r"(?<![\d,.])(?!9+(?![\d]))\d{6,8}(?![\d.,])"),
    "comma + 4+ digits (unmasked)": re.compile(r",(?!9+(?!\d))\d{4,}"),
    "IFSC": re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b"),
    # Masked handles look like "xxxx.xx@domain"; any other character before "@" means unmasked.
    # Any domain counts, except the dump's font labels like "[Helvetica@8.0]" / "SourceSans3-Regular@7.7,".
    "unmasked handle/email": re.compile(r"(?<![A-Za-z0-9._%+-])(?=[A-Za-z0-9._%+-]*[^x._%+\-@])[A-Za-z0-9._%+-]+@(?!\d+(?:\.\d+)?[\],])[A-Za-z0-9]"),
}
bad = 0
for f in sorted((ROOT / "samples/redacted").glob("*.txt")):
    text = f.read_text()
    res = {k: len(p.findall(text)) for k, p in checks.items()}
    res["non-ASCII letters"] = sum(1 for c in text if ord(c) > 127 and unicodedata.category(c)[0] in "LMN")
    res["term pieces"] = sum(len(re.findall(r"(?<![A-Za-z])" + re.escape(p) + r"(?![A-Za-z])", text, re.I)) for p in pieces)
    bad += sum(res.values())  # every check is a leak indicator
    print(f.name, res)
sys.exit(1 if bad else 0)
