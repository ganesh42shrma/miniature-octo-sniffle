"""Squirl statement parser service.

POST /parse  multipart: file (PDF), bank ("sbi" | "kotak" | "auto"), password (optional)
GET  /health

Stateless: the PDF and password live in memory for one request only. Logs carry counts and
error codes, never statement text or passwords.
"""

from __future__ import annotations

import json
import logging
import time

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.formparsers import MultiPartParser

from . import errors
from .common import reconcile
from .config import settings
from .parsers import PARSERS
from .pdf import detect_bank, open_pdf, require_text
from .schemas import ErrorResponse, ParseResponse

# Root stays at WARNING; only our own logger follows PARSER_LOG_LEVEL. PDF libraries can log
# document strings at DEBUG/INFO, so they are pinned to ERROR whatever the setting.
logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logging.getLogger().setLevel(logging.WARNING)  # basicConfig is a no-op if the root was configured elsewhere
log = logging.getLogger("squirl_parser")
log.setLevel(settings.log_level)
for noisy in ("pdfminer", "pdfplumber", "PIL"):
    logging.getLogger(noisy).setLevel(logging.ERROR)

# bank="auto" detects SBI or Kotak from the first page instead of trusting the caller.
AUTO = "auto"
MAX_FILE_BYTES = settings.max_file_mb * 1024 * 1024
MAX_BODY_BYTES = MAX_FILE_BYTES + 64 * 1024  # file + multipart overhead and small fields

# Starlette spools uploads over 1 MB to a temp file on disk. Keep everything up to the limit in memory.
MultiPartParser.spool_max_size = MAX_BODY_BYTES


class _BodyTooLarge(Exception):
    pass


def _json_bytes(code: str, message: str) -> bytes:
    return json.dumps(ErrorResponse(error=message, code=code).model_dump()).encode()


class GuardMiddleware:
    """Pure ASGI middleware that (1) rejects bodies over the size limit before they are buffered and
    (2) turns unexpected exceptions into a safe 500 *without re-raising*, so Uvicorn never logs
    their messages or tracebacks (which can contain statement text)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        length = dict(scope.get("headers") or []).get(b"content-length")
        if length is not None and length.isdigit() and int(length) > MAX_BODY_BYTES:
            return await self._respond(send, 400, "INVALID_FILE", f"The PDF is larger than {settings.max_file_mb} MB")

        received = 0
        started = False
        too_large = False

        async def limited_receive():
            nonlocal received, too_large
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > MAX_BODY_BYTES:
                    too_large = True
                    raise _BodyTooLarge()
            return message

        async def tracking_send(message):
            nonlocal started
            if too_large:
                # FastAPI wraps errors raised while parsing the form into its own 400; swallow that
                # response so the client gets INVALID_FILE below.
                return
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _BodyTooLarge:
            pass
        except Exception as exc:  # noqa: BLE001 - last line of defence
            log.error("unexpected error type=%s", type(exc).__name__)
            if not started and not too_large:
                await self._respond(send, 500, "INTERNAL_ERROR", "The statement parser hit an unexpected error")
        if too_large and not started:
            await self._respond(send, 400, "INVALID_FILE", f"The PDF is larger than {settings.max_file_mb} MB")

    @staticmethod
    async def _respond(send, status: int, code: str, message: str) -> None:
        body = _json_bytes(code, message)
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})


app = FastAPI(title="Squirl statement parser", version="0.1.0", docs_url="/docs", redoc_url=None)
app.add_middleware(GuardMiddleware)


def _error(status: int, code: str, message: str, headers: dict | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content=ErrorResponse(error=message, code=code).model_dump(), headers=headers)


@app.exception_handler(errors.ParserError)
async def parser_error_handler(_: Request, exc: errors.ParserError) -> JSONResponse:
    return _error(exc.status_code, exc.code, exc.message)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    fields = sorted({".".join(str(p) for p in e["loc"][1:]) or "request" for e in exc.errors()})
    return _error(400, "INVALID_REQUEST", f"Missing or invalid fields: {', '.join(fields)}")


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    # Framework errors (malformed multipart, 404, 405, ...) use the same {error, code} envelope.
    if exc.status_code == 404:
        return _error(404, "NOT_FOUND", "Not found")
    if exc.status_code == 405:
        return _error(405, "METHOD_NOT_ALLOWED", "Method not allowed", headers=exc.headers)  # keeps Allow
    return _error(exc.status_code if exc.status_code < 500 else 400, "INVALID_REQUEST", "Invalid request: the upload could not be read")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "banks": sorted(PARSERS)}


@app.post("/parse", response_model=ParseResponse, responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}, 422: {"model": ErrorResponse}})
def parse(
    file: UploadFile = File(...),
    bank: str = Form(...),
    password: str | None = Form(None),
) -> ParseResponse:
    # Sync endpoint: FastAPI runs it in a worker thread, so CPU-bound PDF work doesn't block the loop.
    started = time.perf_counter()
    bank = bank.strip().lower()
    if bank != AUTO and bank not in PARSERS:
        raise errors.unsupported_bank(bank)

    data = file.file.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise errors.invalid_file(f"The PDF is larger than {settings.max_file_mb} MB")

    try:
        with open_pdf(data, password or None) as pdf:
            require_text(pdf)
            found = detect_bank(pdf)
            if bank == AUTO:
                if found is None:
                    raise errors.bank_unknown()
                bank = found  # "auto": trust the first page's bank markers
            elif found != bank:
                raise errors.bank_mismatch(bank, found)
            parser = PARSERS[bank]
            statement = parser.parse(pdf)
            pages = len(pdf.pages)
        reconcile(statement)
    except errors.ParserError as exc:
        log.info("parse failed bank=%s code=%s ms=%d", bank, exc.code, (time.perf_counter() - started) * 1000)
        raise

    log.info("parsed bank=%s pages=%d rows=%d ms=%d", bank, pages, len(statement.rows), (time.perf_counter() - started) * 1000)
    return ParseResponse.from_statement(bank, parser.version, statement)
