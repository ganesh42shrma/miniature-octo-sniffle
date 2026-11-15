# SBI savings account statement - layout spec (reviewed)

Source: redacted sample `samples/redacted/sbi.txt` (18 pages, "SBI_ACC_STATEMENT.pdf", **encrypted: True** - the real parser must handle a password/owner-encrypted PDF).
Prototype: `scratchpad/sbi_proto.py` (works on the WORD POSITIONS section; rules below are expressed in x0/top so they transfer to `page.extract_words()` grouped by `top`).

## 1. Document overview
- 18 pages, A4 595x842 pt, text-based (no scanned content; page 18 has 4 images = logos/decoration only, no text in them).
- Single font family Helvetica. Sizes: transaction rows **8.0pt**; table header ("Balance") 10pt; page footer "Page no. N" 10pt (top=755.4, centred ~x269-324); page-1 summary block 10-11pt; titles 12-14pt; disclaimer 7.5-8pt.
- Page 1 = account summary + first 3 txns (table starts at top~500). Pages 2-17 = txns only (13 txns/page; 14 on p16 because of 2 short ATM/interest rows). Page 18 = last 4 txns + "Statement Summary" + disclaimer.
- Each txn is a fixed-pitch block: 50.0pt between consecutive 4-line txns.
- Table header: only the word `Balance` (x 514-551) is real text, at top 500.5 on p1 and top 30.5 on p2-18. The other column captions (Txn Date / Value Date / Description / Ref No / Debit / Credit) are NOT present in the extracted text (likely vector/outlined glyphs) - do not rely on them; use fixed x-ranges.

## 2. Header / account summary (page 1 only)
All "Label : value" pairs; value positions are stable. Left block (labels x~65, colon x~199-202, value x~207+) and right block (labels x~348, colon x~442-445, value x~450+).

| Label | Where | Notes |
|---|---|---|
| `Welcome:` / `As on 16-10-2026` | top 16-21 | "as on" = statement generation date (DD-MM-YYYY) |
| `Date of Statement : 16-10-2026` | left, top~206 | generation date again |
| `Clear Balance : 235.69CR` | left, top~235 | **balance as of generation date, NOT period closing** - do not use as closing balance |
| `Uncleared Amount`, `+MOD Xxx`, `Lien`, `Limit`, `Monthly Avg Balance`, `Interest Rate : 2.50 % p.a.`, `Drawing Power`, `Account open Date : DD/MM/YYYY` | left | informational |
| `Branch Code`, `Branch <name>`, `Branch Email ID`, `Branch Phone`, `CIF Number`, `Account Number`, `Product`, `IFSC Code`, `Currency`, `Account Status`, `MICR Code`, `Nominee ...` | right | `Account Number` is fully masked here but is the full account number in real data |
| **`Statement From :01-07-2026 to 30-09-2026`** | centred, top~462.3 | words: `Statement`(x203) `From`(251) `:01-07-2026`(285; note colon glued to the date, no space) `to`(344) `30-09-2026`(355) |

Period extraction: regex `Statement From\s*:?\s*(\d{2}-\d{2}-\d{4})\s+to\s+(\d{2}-\d{2}-\d{4})`, format **DD-MM-YYYY**. The same range is repeated on the last page: `Statement Summary : 01-07-2026 To 30-09-2026` (capital `To`) - fallback source.
Opening/closing balance are taken from the **Statement Summary** on the last page (section 7), not from the page-1 header. Balance suffix: `CR` glued to the number (`14,380.73CR`); `DR` presumably for overdrawn (not observed).

## 3. Transaction table
Columns (left to right) and x-ranges, measured on 8pt words (x0 for left-aligned text, x1 for right-aligned amounts):

| # | Column | Alignment | x0 / x1 range seen | Bucketing rule (x0) |
|---|---|---|---|---|
| 1 | Txn Date `DD/MM/YYYY` | left | x0=27 (27-68) | x0 < 75 |
| 2 | Value Date `DD/MM/YYYY` | left | x0=82 (82-123) | 75 <= x0 < 130 |
| 3 | Description | left | x0=138, max x1~266 | 130 <= x0 < 295 |
| 4 | Ref No./Cheque No. | centred | `-` at 304-306 (always `-` in this sample) | 295 <= x0 < 340 |
| 5 | Debit | right (x1 ~ 378-383) | amounts x0 352-360, x1 378-383; placeholder `-` at 366-369 | 340 <= x0 < 400 |
| 6 | Credit | right (x1 ~ 463) | amounts x0 ~432-463; placeholder `-` at 446-449 | 400 <= x0 < 490 |
| 7 | Balance | right (x1 = 548) | x0 512-518, x1 548 | x0 >= 500 |

Tolerance: +-3pt on edges. Prefer right-edge (x1) for amounts because x0 varies with digit count. The debit/credit gutter between 383 and ~430 is empty, so boundaries 400 and 490 are safe (nearest data: debit x1<=383, credit x0>=~425 for 7-digit+ amounts: widest seen 432; use 400 as split).
- Header row: only "Balance" repeats on every page (p2-18 at top 30.5); no other header text. Table body therefore starts at the first line below the `Balance` word (page 1: 500.5, others: 30.5) and ends above footer (top 755.4).
- **`extract_tables()`**: yields one table per page with 7 cols; each txn is one row with multi-line cells joined by newline (leading line, description, continuation, `<13d> AT <5d>`, branch). It works for most rows, but (a) a bogus first row (`∅|...|Balance`) and last all-empty row, (b) the leading line (`XXX TFR`) is inside the description cell and on rows lacking it the cell layout differs, (c) on p18 a second table (summary) is found, (d) cells are merged text so the geometric "which line is lead vs continuation" info is lost. In this sample the tables are row-aligned (216 rows = 216 txns) so it is *usable*, but word-position bucketing is more robust (independent of ruling lines, and gives gaps for lead detection). Recommend word bucketing, using tables only as a cross-check.

## 4. Row structure
A transaction is a vertical block of visual lines (tops relative to the date line T):
```
T-7.1  [leading line]   x0=138  e.g. "XXX TFR" / "DEP TFR" / "DEP TFR XXX Salary Payment"   (optional)
T      date line        txn date, value date, description part 1, "-", debit, credit, balance
T+11.5 continuation 1   x0=138  (rest of UPI string: "/HDFC/9999999999/XXX")
T+20.8 "9999999999999 AT 99999"   13 digits + AT + 5-digit branch code
T+30.1 branch name       "XXXXXXX XXXXX, XXXXXXXXX"
```
Sparse variants: the number of continuation lines varies (0-3); trailing `AT`/branch pair is absent on 8 of 216 txns (ATM x2, INTEREST, NACH x2, UPI/REVERSAL-type CR x2, POS x1).

**Row boundary rule — REVIEWED: use cell borders first.** Each transaction is a bordered table cell
row drawn as many short horizontal segments (widths 50–150 pt). Merge horizontal edges
(`page.edges`, orientation `h`) whose `top` is within 1.5 pt into one border line, then bucket the
body words into the bands between consecutive borders. On the real sample, 216/216 bands contain
exactly one date line, 0 words cross a border, and 21 bands have no date (header/summary). The
leading line falls inside its own row's band. If a band has 0 date lines but has description words,
append it to the previous row (this covers a row split across a page). If a band has ≥2 date lines,
raise `UNSUPPORTED_LAYOUT`.

**Cross-check (the draft's gap rule, implemented in the prototype with 0 errors). It must produce
the same rows, otherwise raise `UNSUPPORTED_LAYOUT`:**
1. Within the table body, a line is a **date line** iff first word x0 < 40 and matches `^\d{2}/\d{2}/\d{4}$`. It carries all amounts.
2. A non-date line is a **leading line** of the *next* row iff the following line is a date line and `date_top - line_top < 8.5` (observed 7.1; every other inter-line gap is >= 9.3). Otherwise it is a **continuation** of the current row. This is required because the leading line sits *above* the date and would otherwise be mistaken for the previous row's trailer (and 3 rows have no leading line at all: ATM x2, INTEREST CREDIT - their lines are directly after the previous branch line).
3. A row ends when the next leading/date line begins. No row splits across a page (see 6).
Dates: txn date == value date for all 216 rows (still read both). Both `DD/MM/YYYY`; the parser should use Txn Date. Rows are chronological.

Empty cells: `-` in col 4 (always), and in the debit cell for credits and the credit cell for debits. Exactly one of debit/credit is a number per row (asserted for all 216). `-` is never an amount.
Amount format: Indian grouping (`1,67,934.65`, `4,763.86`, `54,533.00`), always 2 decimals, no sign, no CR/DR suffix on row amounts. Row balance has **no CR/DR suffix** (`14,281.73`); only Brought Forward/Closing and Clear Balance carry `CR`. Regex: `^\d{1,3}(?:,\d{2})*(?:,\d{3})?\.\d{2}$|^\d+\.\d{2}$` -> strip commas -> Decimal. Balance `0.00` occurs (after an ATM withdrawal).

## 5. Description & refNo
Description assembly: lines = leading + date-line description part + continuations; drop the `^\d{13} AT \d{5}$` line and the branch line after it (if the AT line also contains text, e.g. `XXXXXXXXX XXXX X AT 99999`, keep the text before ` AT ddddd`). Join using the shared rule in [README.md](README.md) (no space after a trailing `/` or `-`, or before a leading `/`). Hard wraps without `/` (e.g. a split payee name) can't be detected, so accept a space. **REVIEWED: keep the leading line** (`XXX TFR` is probably `WDL TFR`; the real letters are masked) as the first part of the description. It's real statement text and the only label on salary/NACH rows.
Branch-code/`AT` line (13-digit number) is a bank-internal transaction id, NOT the UPI RRN.

refNo (column 4 is always `-`, so refNo is derived from description):
| Type (first token of description line) | count | Dir | refNo |
|---|---|---|---|
| `UPI/DR/<12d>/<payee>/<bank4>/<vpa>/<note>` (lead `XXX TFR`) | 196 | DR | the 12 digits after `UPI/DR/` |
| `UPI/CR/<12d>/...` | 5 | CR | 12 digits |
| `UPI/REVERSAL/<12d>/...` (lead `XXXXXX DEP`) | 1 | CR | 12 digits |
| `UPI/<other>/<12d>/<6d>` (masked verb, lead `XXXXXX DEP`) | 1 | CR | 12 digits |
| `NEFT*<IFSC>*<utr>` (lead `DEP TFR`) | 2 | CR | token after 2nd `*` (UTR) |
| `IMPS/<12d>/<name>-<..>` | 1 | CR | 12 digits |
| `<13d> OF <...>` (salary/credit, lead `DEP TFR XXX Salary Payment` / `DEP TFR XXX Xxxxx`) | 4 | CR | null |
| `NACH<14d> <...>` (lead `DEBIT XXXXx`) | 2 | DR | null (or the NACH id) |
| `ATM <...>` (no lead, no trailer) | 2 | DR | null |
| `POS ATM ...` / `<12d>XXXXXXXXX* ...` (lead `POS ATM XXXXX XXXXX`) | 1 | DR | null (12d prefix is a card RRN) |
| `INTEREST CREDIT` (no lead, no trailer) | 1 | CR | null |
Total 216. Masked examples: `UPI/DR/999999999999/Xxxxxxxx/X XXX/xxxxxxxxxx/Xxx`, `NEFT*UTIB9999999*XXXX999999 999999*XX0XX XXXXXX XX`.

## 6. Page breaks
- Top of pages 2-18: `Balance` (top 30.5); first txn line at top 61.3 (leading line) / 68.4 (date). Bottom: `Page no. N` at top 755.4 (ignore everything with top > 740). Last txn line on a full page is at ~698.5; the next block would not fit.
- Rows are never split across pages in this sample (prototype counts 0 continuation lines at page top; every page's first body line is a leading/date line, every page ends with a complete 4-line block). Defensive rule: if the first body line of a page is neither lead nor date, append to previous row.
- Page 1 gets 3 txns (begin top 531); pages 2-17 have 13; p16 has 14; p18 has 4.

## 7. End of statement (page 18)
After the last txn (top ~248):
- `Statement Summary : 01-07-2026 To 30-09-2026` (top 341)
- Header line (top 369): `Brought Forward( ) Dr Count Cr Count Total Debits( ) Total Credits( ) Closing Balance( )` - the "( )" is likely a rupee glyph lost in extraction.
- Value line (top 398): `14,380.73CR  201  15  1,67,934.65  1,83,560.03  30,006.11CR` at x0 40 / 139 / 197 / 258 / 359 / 483 (Brought Forward = opening, Dr Count, Cr Count, Total Debits, Total Credits, Closing). Extract by regex over the line: `(\d[\d,]*\.\d{2})CR\s+(\d+)\s+(\d+)\s+(amt)\s+(amt)\s+(amt)CR`.
- Disclaimer (4 lines, 7.5-8pt, "Please do not share ... This is a computer generated statement ...") and page footer. Exclude everything from the line starting `Statement Summary` onward; extract_tables returns this as a 2nd table - ignore for txns.

## 8. Validation rules
- Opening balance = Brought Forward (Statement Summary). Running check per row: `prev_balance - debit + credit == balance` (Decimal), with prev for row 1 = opening. Balance sign is always positive/CR in sample (if a `DR` suffix appears on Brought Forward/Closing, negate).
- Totals: sum(debits) == Total Debits; sum(credits) == Total Credits; count(debit rows) == Dr Count; count(credit rows) == Cr Count; opening + credits - debits == closing; last row balance == closing.
- periodFrom/periodTo from `Statement From`.

## 9. Prototype results (redacted sample)
- Transactions found: **216** (201 debit, 15 credit); first date 02/07/2026, last 30/09/2026 (chronological; txn date == value date everywhere).
- **Running-balance breaks: 0** of 216 (starting from Brought Forward 14,380.73).
- Total debits 167,934.65 and credits 183,560.03 both match the Statement Summary exactly; counts 201/15 match; closing 30,006.11 matches last row; opening + credits - debits == closing.
- Period parsed: 2026-07-01 .. 2026-09-30.

## 10. Edge cases & open questions
- PDF is encrypted (pdfplumber needs password or an empty-user-password decrypt; check `pdf.is_encrypted` handling).
- Column captions are not extractable text (only `Balance`); verify on a real PDF that this is the same (could be that redaction/extraction dropped them). Parser should not require them; anchor on `Balance` at x>500 or on page geometry.
- Real transaction-type leading words (`WDL TFR`, `DEP TFR`, etc.) are masked as `XXX TFR`; real vocabulary unknown. Leading-line detection is geometric (gap < 8.5), so it is robust to this.
- Unseen: `DR` suffix on balances (overdraft), cheque numbers in col 4 (would appear instead of `-`; keep refNo = col 4 if not `-`), charges/fees rows (SMS, ATM charges), multi-page splits, statements with a zero-txn page, statements where leading line text is wide enough to reach x>295.
- Rows lacking leading AND trailer (ATM, INTEREST CREDIT): the 8.5pt gap rule distinguishes them; a naive "4-lines per row" or "date line preceded by branch line" rule would fail.
- Wrapped payee names: lines joined with space unless the earlier line ends with `/`; some real names may be split mid-word.
- Gap threshold sanity: lead gap 7.1; smallest other gap (date -> continuation) 11.5, continuation steps 9.3; threshold 8.5 sits between.
