# Squirl statement parser. Run `make` to list the commands.

# Localhost only: statements and passwords never leave this machine.
HOST ?= 127.0.0.1
# The backend expects PARSER_SERVICE_URL=http://127.0.0.1:8000
PORT ?= 8000

.DEFAULT_GOAL := help
.PHONY: help check-uv install install-prod start dev test redact check-redaction

help: ## List the commands
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  make %-16s %s\n", $$1, $$2}'

check-uv:
	@command -v uv >/dev/null || { echo "uv is not installed: https://docs.astral.sh/uv/ (brew install uv)"; exit 1; }

install: check-uv ## Install all dependencies, including test tools, into .venv
	uv sync

install-prod: check-uv ## Install runtime dependencies only
	uv sync --no-dev

start: check-uv ## Start the service on HOST:PORT
	uv run uvicorn app.main:app --host $(HOST) --port $(PORT)

dev: check-uv ## Start with auto-reload when files in app/ change
	uv run uvicorn app.main:app --host $(HOST) --port $(PORT) --reload --reload-dir app

test: check-uv ## Run the test suite
	uv run pytest -q

redact: check-uv ## Write masked layout dumps of samples/private/ to samples/redacted/
	uv run python scripts/redact_samples.py

check-redaction: check-uv ## Scan samples/redacted/ for leftover identifiers (prints counts only)
	uv run python scripts/check_redaction.py
