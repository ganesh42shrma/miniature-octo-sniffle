# squirl_parser

A stateless FastAPI service that turns SBI and Kotak statement PDFs into transactions the Squirl
backend can import. It has no database: the PDF and password live in memory for one request.

## Run

```bash
make install     # uv sync: creates .venv with all dependencies
make start       # http://127.0.0.1:8000 (the backend's default PARSER_SERVICE_URL)
make dev         # same, restarting when app/ changes
make test        # synthetic tests + local-only real-sample tests
make             # list every command
```

Override the address with `make start PORT=9000` or `make start HOST=0.0.0.0` (that one exposes the
service to your network). Needs [uv](https://docs.astral.sh/uv/).

Interactive API docs: http://127.0.0.1:8000/docs

| Env var | Default | |
|---|---|---|
| `PARSER_MAX_FILE_MB` | `10` | Upload size limit |
| `PARSER_LOG_LEVEL` | `INFO` | Logs carry counts and error codes only |

## API

`POST /parse` takes `multipart/form-data` with these fields:
- `file`: the PDF
- `bank`: `sbi`, `kotak`, or `auto` (detect the bank from the first page)
- `password`: optional

It returns `200` with this body:
```json
{ "bank": "sbi", "periodFrom": "2026-07-01", "periodTo": "2026-09-30",
  "transactions": [{ "date": "2026-07-02", "description": "...", "refNo": "412345678901",
                     "debit": 99.0, "credit": null, "balance": 14281.73 }],
  "summary": { "opening": 14380.73, "closing": 30006.11, "count": 216,
               "totalDebits": 167934.65, "totalCredits": 183560.03, "parserVersion": "sbi-1" } }
```

On failure it returns `{ "error": "<message for the user>", "code": "<CODE>" }`:

| Code | HTTP | When |
|---|---|---|
| `INVALID_FILE`, `UNSUPPORTED_BANK`, `INVALID_REQUEST` | 400 | Not a PDF / too big / bad form |
| `PASSWORD_REQUIRED`, `WRONG_PASSWORD` | 401 | Encrypted PDF |
| `BANK_MISMATCH` | 422 | PDF is from the other bank |
| `BANK_UNKNOWN` | 422 | `bank=auto` but neither bank's markers are on the first page |
| `NO_TEXT_LAYER` | 422 | Scanned PDF (no OCR) |
| `UNSUPPORTED_LAYOUT` | 422 | Expected anchors/columns not found, or row boundaries ambiguous |
| `RECONCILIATION_FAILED` | 422 | Running balance, opening/closing, printed totals, serials or dates don't add up |

`GET /health` returns `{ "status": "ok", "banks": ["kotak", "sbi"] }`.

## How it works

```
open (in memory, decrypt) → has text? → which bank? → bank parser → reconcile → JSON
```

- `app/pdf.py`: opens the PDF, maps password and corrupt-file errors, detects the bank, reads ruling lines.
- `app/parsers/sbi.py`: splits rows on the table's cell borders and cross-checks against the
  line-spacing rule. Opening and closing balances and totals come from the Statement Summary.
- `app/parsers/kotak.py`: keys rows on the serial-number column. Wrapped lines (including those
  carried over a page break) attach to the previous row.
- `app/common.py`: amounts (`Decimal`), joining description lines, and `reconcile()`, which is all-or-nothing.

The layout rules come from [docs/layouts/](docs/layouts/README.md).

**Don't change `join_description` casually.** The backend's dedupe hash includes the description.

## Privacy

- Real statements go in `samples/private/` and passwords in `.env`. Both are gitignored.
- `scripts/redact_samples.py` writes masked layout dumps to `samples/redacted/`, and
  `scripts/check_redaction.py` scans them for leaks, printing counts only.
- `tests/test_real_samples.py` runs only when the private PDFs are present, and asserts on counts and totals.
- Logs never contain statement text, descriptions or passwords. Unexpected errors log only the
  exception type.

## Adding a layout

1. Put the PDF in `samples/private/`, run the redaction script, and write a spec in `docs/layouts/`.
2. Add a parser in `app/parsers/` and register it in `app/parsers/__init__.py`.
3. Add a builder for a fake statement in `tests/builders.py`, plus tests.
