# Statement layouts

Layout specs the parser service implements. One file per bank. Each one was drafted by an analysis
agent from the **redacted** samples, then reviewed: its prototype was re-run and key claims were
checked against PDF geometry (no text was revealed).

| Bank | Spec | Sample | Prototype result |
|---|---|---|---|
| SBI | [sbi.md](sbi.md) | 18 pages, encrypted, Jul–Sep 2026 | 216 txns, 0 balance breaks, totals and counts match the printed Statement Summary |
| Kotak | [kotak.md](kotak.md) | 10 pages, not encrypted, Aug–Oct 2026 | 229 txns, 0 balance breaks, serials 1..229 contiguous, closing matches the Account Summary |

## Decisions that apply to both banks

1. **Output contract** (validated by `parserResponse` in `squirl_backend/src/plugins/imports/import.validation.js`):
   `{ periodFrom, periodTo, transactions: [{ date, description, refNo, debit, credit, balance }] }`.
   Dates are `YYYY-MM-DD`. Do all arithmetic in `Decimal` and serialise amounts as 2-dp numbers.
   Exactly one of `debit`/`credit` is set per row. Keep rows in statement order.
2. **Find rows by word geometry, not `extract_tables()`.** Use `page.extract_words()` and assign
   each word to a column bucket by x position (right edge `x1` for amounts). `extract_tables()` is
   only a cross-check: it adds header/title rows, splits tables at gaps, and loses line geometry.
3. **All-or-nothing reconciliation.** Before returning, check:
   - every row: `prev_balance − debit + credit == balance`
   - `opening + Σcredit − Σdebit == closing`
   - SBI only: the printed Dr/Cr totals and counts
   If any check fails, return an error (422, with the row index and kind of failure). Never return
   partial data.
4. **The description format is frozen once shipped.** The Node backend's dedupe hash (`makeHash`)
   includes `description`. If the way descriptions are joined changes later, re-imported statements
   stop deduplicating, so any change has to come with a backend migration or a hash change.
   Joining rule for both banks: join the description lines with one space, except **no space** when
   the previous line ends in `/` or `-`, or the next line starts with `/`. This handles hard-wrapped
   UPI strings and `(Value Date: 13-` + `10-2026)`. Then collapse whitespace and trim.
5. **Check the bank before parsing.** Reject with `BANK_MISMATCH` if the PDF doesn't look like the
   requested bank:
   - SBI: `State Bank of India` text or an IFSC starting `SBIN`, plus `Statement From`
   - Kotak: an IFSC starting `KKBK` or `Kotak Mahindra`, plus the `#` / `Chq/Ref. No.` table header
6. **Error codes:**
   - `PASSWORD_REQUIRED`: encrypted PDF, no password given
   - `WRONG_PASSWORD`
   - `NO_TEXT_LAYER`: scanned PDF; there is no OCR in v1
   - `UNSUPPORTED_LAYOUT`: required anchors not found
   - `RECONCILIATION_FAILED`
   - `BANK_MISMATCH`
7. **Privacy:** never log PDF text, passwords, descriptions or account numbers. Only log counts,
   timings and error codes. Keep PDFs in memory only.

## Review findings applied to the drafts

- **SBI row segmentation → cell borders first** (geometry check on the real PDF: 216/216 bands
  between horizontal cell-border segments contain exactly one date line, and 0 words cross a
  border). The draft's 8.5 pt leading-line gap rule is now a cross-check that must agree.
- **Kotak: cell borders do NOT delimit rows** (703 words cross line segments; they are decoration
  or shading). Keep the draft's serial-number anchor approach.
- One description joining rule for both banks (decision 4), replacing the per-bank variants.
- SBI: the leading line (`XXX TFR`, `DEP TFR …`) stays **in** the description. It is real statement
  text and is the only place salary / NACH rows say what they are.
- Kotak: the `(Value Date: DD-MM-YYYY)` tail stays in the description verbatim. `date` is always
  the row's Date column.
- Kotak: only pages with a `#` table header are parsed. The geometry check found 3 extra integers
  in the serial x-band on the summary/legend pages.

## Not covered by the samples (handle defensively, add fixtures when seen)

Overdraft balances (`DR` suffix or a minus sign), cheque numbers in the ref column, NEFT/IMPS/ATM
rows on Kotak, rows split across pages on SBI, lakh-sized amounts on Kotak, other statement
variants (current accounts, older layouts, statements downloaded from the branch rather than net
banking).

## Regenerating the redacted samples

```
uv run python -I scripts/redact_samples.py    # samples/private/*.pdf → samples/redacted/*.txt
uv run python -I scripts/check_redaction.py   # leak scan, counts only; non-zero exit on a leak
```
