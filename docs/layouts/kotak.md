# Kotak Mahindra Bank - Savings Account Statement (reviewed layout spec)

Source: `samples/redacted/kotak.txt` (redacted dump of a 10-page statement, 01 Aug 2026 - 31 Oct 2026).
Prototype: scratchpad `kotak_proto.py` (parses WORD POSITIONS rows with the rules below). Result: **229 txns, 0 balance breaks, serials 1..229 contiguous**.

## 1. Document overview
- 10 pages, A4 portrait 595x842, text-based (no OCR). Font family SourceSans3 (Regular / SemiBold).
- Page 1: 1 image (logo, no text value). Pages 9 and 10 have 5 and 13 images (promo/icons); ignore.
- Pages 1-8 hold the transaction table (page 8 is partial, ends at top~491). Page 9 = "Account Summary" + "End of Statement" + contact. Page 10 = "Important Information" + abbreviation legend (boilerplate).
- Font sizes: title "Account Statement" 25pt; period 11pt; section titles ("Savings Account Transactions", "Account Summary", "End of Statement") 12pt; table header 9pt; **transaction rows 7.7pt** (this is a reliable discriminator: body rows are the only 7.7pt text on pages 1-8; but pages 9/10 also use 7.7pt, so gate by page type, see below). Account-detail labels 9pt Regular, values 9pt SemiBold; holder name 14pt SemiBold.
- Page type detection: a page is a transaction page iff it has a line with a `#` word at x0<50 (the table header). Pages 9/10 do not.

## 2. Header / account summary
Page 1 only (top-to-bottom):
- top~102 `Account Statement` (25pt); top~127 **period line**, own line, exact format `DD Mon YYYY - DD Mon YYYY` (e.g. `01 Aug 2026 - 31 Oct 2026`, English 3-letter month). Regex on the joined line text: `^(\d{2}) (\w{3}) (\d{4}) - (\d{2}) (\w{3}) (\d{4})$`. periodFrom/periodTo from it.
- Left block (x 36-265): holder name, `CRN xxxxxx510` (partially masked), address lines, `MICR 999999999 IFSC Code KKBK...` (top~312).
- Right block (x0=348, label + SemiBold value on one line): `Account No.`, `Account Type`, `Branch`, `Account Status`, `Nominee Registered`, `Currency`.
- The same 3 lines repeat as a **running header on pages 2-10** at top 15.6 / 27.6 / 39.6 (holder name; `Account No. <n>`; `Account Statement <period>`). The period also appears here (x 111-208, top 39.6), so period can be read from any page; page 1 is canonical. Running header is above the table header row; exclude by taking only lines below the `#` header row.
- Opening balance: first table row on page 1: `-  -  Opening Balance  -  -  -  <bal>` (anchor sno is `-`, date `-`). Balance in the balance column (x1=556). No debit/credit.
- Closing balance: only in the page-9 summary (see 7), and equals last row balance.

## 3. Transaction table
Header row (9pt, repeats on **every transaction page**: top~366 on p1, top~116.6 on p2-8): words `#`(x0 44), `Date`(75), `Description`(124), `Chq/Ref. No.`(280), `Withdrawal (Dr.)`(355-416), `Deposit (Cr.)`(429-476), `Balance`(498-528). A title line `Savings Account Transactions` (12pt, top~90 on p2-8) sits above it. Rows start after header top and end before footer (top>=810).

Row column buckets (7.7pt text; x0 for left-aligned, **x1 for right-aligned amounts**). Observed:
| col | rule | observed |
|---|---|---|
| `#` | x0 in [35,60), left aligned | x0 36-39 (1-3 digits; 3-digit starts at 39-ish, 2-digit end x1<=47) |
| Date | x0 in [60,115) | 3 words `DD` x0 73, `Mon` ~82, `YYYY` ~96-111 |
| Description | x0 in [115,272) | x0 starts 119; wraps before x1~270 |
| Chq/Ref. No. | x0 in [272,350) | x0 275, x1 334 (`UPI-<12 digits>`) |
| Withdrawal (Dr.) | right-aligned, x1 <= 430 | x1 = 418 exactly (x0 varies 391-418 with width) |
| Deposit (Cr.) | right-aligned, 430 < x1 <= 500 | x1 = 487 exactly |
| Balance | right-aligned, x1 > 500 | x1 = 556 exactly |
Use right edge x1 (tolerance +-3) for amounts; do not use x0 (varies with digits count; a 7-char debit like `4,946.00` starts at 391, overlapping nothing but description region is capped by 272 so still safe). Debit x0 never drops below 391 in this sample (max amount seen 5 digits + decimals), so there is no desc/amount overlap.

**extract_tables() vs word bucketing.** Default `extract_tables()` yields one table per page (2 on pages 4 and 7) with 7 cols, correct for most rows, with `⏎` inside wrapped description cells and `∅` for empty Dr/Cr. But: (a) first row is the section title (`Savings Account Transactions | ∅...`) and second the header; (b) pages 4 and 7 split into two tables because of a vertical gap (p4 between rows 100-101 at top 418->442; p7 between rows 200-201 at 557->581), so you must concatenate; (c) a transaction split across pages yields a **continuation-only row** (`∅ | ∅ | text | ∅ ...`) at top of the next page's table (p5, p6, p8), which must be merged into the previous page's last row; (d) page 1's first body row is the opening balance with `-` cells; (e) dependency on ruling-line detection. Recommended: **word-position bucketing by row anchor** (as in the prototype) - it needs no ruling lines, handles gaps/splits uniformly. `extract_tables()` is an acceptable cross-check only.

## 4. Row structure
- **Anchor**: a visual line whose `#` bucket is an integer `^\d+$` AND whose date bucket has exactly 3 words (`DD Mon YYYY`). Opening row anchor is `-` + `Opening Balance` in Description.
- Anchor line carries: date, first description line, ref, amount, balance - all on the same `top`. Continuation lines have words only in the Description bucket (x0 starts 119) and nothing in #, Date, ref, amounts.
- Wrap: 0 to ~7 extra description lines (mostly 1; `Payment from` rows often 2). Line pitch ~7.7pt; row pitch ~13.7pt for single-line, anchor-to-next-anchor otherwise. Words are not broken mid-token except hard wraps like `13-` / `10-2026)` for `(Value Date: 13-10-2026)` and a single trailing letter on its own line (e.g. `X`).
- **Continuation can appear above the anchor visually only across a page break**: the first line(s) under the header on pages 5, 6, 8 are continuation lines of the final row of the previous page (e.g. p8 top 136.1 `/SBIN/.../Payment from` belongs to row 212 at the bottom of p7). Within a page continuation always follows its anchor. Rule: any desc-only line is appended to the most recent anchor (state carried across pages). Note the first body line on pages 3, 4, 7 happens to be an anchor.
- Date: `DD Mon YYYY` -> ISO. Dates are non-decreasing in serial order. Some descriptions end with `(Value Date: DD-MM-YYYY)` (6 rows) - this is a value date, not the txn date; keep in description (or strip into optional metadata).
- Empty Dr or Cr: simply absent (no `-`, no `0.00`) - words are missing from that bucket (tables show `∅`). Exactly one of debit/credit is present on every row (229/229).
- Amounts: Indian-style grouping with comma and always 2 decimals (`1,000.00`, `4,946.00`; no lakh amounts seen in sample but expect `1,00,000.00` style). No `Cr`/`Dr` suffix: the column decides. Balance always positive in sample; no suffix. Parse: strip `,` -> Decimal.

## 5. Description and refNo
- **REVIEWED:** join the lines with the shared rule in [README.md](README.md): no space after a trailing `/` or `-`, or before a leading `/`. This rejoins `(Value Date: 13-` + `10-2026)`. Keep the value-date tail verbatim. Also confirmed that cell borders do NOT delimit rows here (703 words cross line segments), so the anchor rule below is the primary method.
- description = continuation-joined text: the Description-bucket words of the anchor + continuation lines, in top order. Wrapped tokens often split mid-"word" (e.g. `.../Xxxx` + `xxxxx X`), so joining with a space is lossy at hard wraps; for UPI the ref is available in column and in the string, so fine. Normalise whitespace and trim. Strip nothing else.
- refNo: Chq/Ref. No. bucket text. `UPI-<12 digits>` on UPI rows (225/229; it equals the 12-digit number embedded in the description, `UPI/<name>/<BANK>/<12digits>/<remark>`). Non-UPI rows have **empty** ref bucket -> `null`.
- UPI description format: `UPI/<counterparty name>/<4-letter bank code e.g. HDFC,YESB,UTIB,SBIN,CNRB,ICIC,FDRL,INDB,BARB,AIRP>/<12-digit UPI ref>/<remark e.g. "Payment from Phone", "UPI", "NA", "Sent using Paytm">`. Name may wrap, bank code may be lowercase (`utib`).
- Transaction-type prefixes seen (count of 229): `UPI/` 225; `XXXX:SMS XXXXX XXX FOR THE XXXXX OF <MMMYY>` 3 (masked SMS-alert charge, debit, ref null; prefix after masking is unknowable - likely `SMS:` style; key on ref==null and non-`UPI/`); `Int.Pd:<acct>:<dd-mm-yyyy> to <dd-mm-yyyy>` 1 (interest credit, 6.00, ref null). The legend on page 10 lists other possible prefixes not seen in the rows: ATM/ATW (ATM withdrawal), POS/PCD, IB, MB, IMPS, NEFT, RTGS, NACH, ACH, CDM, CMS, `Sweep transfer to/from`, `Int. Pd.`. The parser must not fail on unknown prefixes: type is derived heuristically only if needed, description stays raw. A non-UPI ref format (e.g. `NEFT-...`, `IMPS-...`, cheque no.) is **not observable here** - take the ref bucket text as-is.
- Debit/credit sign is purely by column (verified by balance walk).

## 6. Page breaks
- Top of pages 2-10: 3-line running header (top 15.6-39.6). Pages 2-8 then have `Savings Account Transactions` (top~90.3) and the column header (top~116.6), body from ~136.
- Bottom of every page: footer `Statement Generated on 04 Nov 2026, 17:52` (x 36-211, 10pt) at top 820.2 and `Page N of 10` at x 519-568, same line. Exclude any line with top >= 810 (or matching `^Statement Generated on` / `Page \d+ of \d+`). Page numbering "Page n of 10" is on all pages incl. 9, 10.
- **Transactions do split across pages**: confirmed 3 times (p4->5, p5->6, p7->8): the anchor sits at the bottom of the page, its trailing description line(s) at top of the next page (examples: row 212 on p7 / `/SBIN/.../Payment from` on p8; p5 begins with `XXXXXXXX/XXX...`; p6 begins with `xxxxx X`). The `extract_tables()` form shows them as description-only rows. The row anchor (balance, amounts) is always on one page - amounts never split.
- Body max top ~797 on full pages; last full-page row at 790-797.

## 7. End of statement
- Page 8 body ends at row 229 (top~491); rest of page empty; footer only.
- Page 9: `Account Summary` (12pt, top 90) with a mini table: header words `Particulars` / `Opening Balance` / `Closing Balance` (top 120.6) and one row `Savings Account (XX): <opening> <closing>` (top~144; opening x 369-386, closing x 512-529). Sample: opening 45.36, closing 61.38. **No** total-withdrawals/deposits or counts are printed.
- Then `End of Statement` (12pt, top 236.5), disclaimer text, `Contact Us` block (branch address/phone), `Kotak Mahindra Bank Ltd. | CIN ...` registered-office footer. Page 10: `Important Information` text and `Abbreviations Used` legend table (`IB - ...`, `UPI - ...`). Exclude everything from page 9 `Account Summary` onward (stop once a page has no `#` header).
- Stop criterion: iterate pages having the `#` header; ignore the rest. Optionally read closing balance from the page-9 summary row for cross-check.

## 8. Validation rules
1. opening = page-1 `Opening Balance` row balance (also page-9 summary opening).
2. for each row: `prev_balance - debit + credit == balance` (Decimal), with prev starting at opening. Exactly one of debit/credit non-null.
3. serial `#` contiguous 1..N, N = 229 here.
4. last row balance == page-9 closing balance; opening + sum(credit) - sum(debit) == closing.
5. dates within [periodFrom, periodTo] and non-decreasing.
6. Row count per page is a sanity (p1 20, p2 31, p3 33, p4 33, p5 32, p6 31, p7 32, p8 17).

### Prototype results (redacted file)
- transactions: **229**; balance breaks: **0**; serials contiguous: yes; shape errors (both/neither Dr/Cr): 0.
- first date 2026-08-01, last 2026-10-30; period 2026-08-01 .. 2026-10-31.
- opening 45.36; total debits 51,607.98; total credits 51,624.00; computed closing 61.38 == page-9 closing 61.38. No printed totals exist to compare debits/credits against; reconciliation is via opening/closing.
- Counts: UPI 225 (all with `UPI-<12>` ref), 3 SMS-charge debits (14.87, 12.57, 3.19; ref null), 1 interest credit (6.00, ref null).

## 9. Edge cases and open questions
- Statement dates are posting dates; `(Value Date: ...)` tail on 6 rows may differ by +1-2 days. Decide whether to put in description (current) or ignore.
- Hard-wrapped tokens: joining lines with space may insert a space inside an original unbroken token (e.g. `13-` / `10-2026)`; `Xxxx` / `xxxxx X`). Use x1 of the previous line: if previous line's x1 is near the column wrap limit (>~262) the break may be mid-word; the sample cannot say. Low impact.
- Masking hides non-UPI prefixes (SMS charge row) - confirm real text in private sample (likely `SMS Alert Chrg` style); ref empty for those. Also confirm that NEFT/IMPS/ATM/POS rows (present only in the legend here) put their ref (UTR/cheque no.) in the Chq/Ref column and what it looks like.
- Vertical gaps inside the table (p4, p7 ~24pt) are layout artefacts; do not treat as row separators; row boundary is decided by anchors only.
- A 3-digit serial begins at x0 39 but 1-digit also x0 39; `#` bucket x0 in [35,60) is safe. Serial could reach 4 digits on longer statements (x1 ~ 58): keep bucket upper bound at 60 (date x0 is 73).
- Opening row has `-` placeholders in Date/Chq/Dr/Cr columns; closing balance has no row in table.
- Balance negative / OD representation (e.g. `Dr` suffix or minus) is unknown - not in sample; parse optional leading `-` and trailing `Cr/Dr` defensively.
- Multi-statement / currency: single savings account, INR (`Currency INDIAN RUPEE` on page 1).
- Text near the right edge: description lines never exceed x~270, ref starts 275 - narrow 5pt margin, so bucket threshold 272 is tight; compute by ref anchor x0 (275) if layout shifts (e.g. read the header word `Chq/Ref.` x0=280 minus ~5).
