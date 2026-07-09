.PHONY: install install-dev run-local dev-local test test-unit lint format

# ── Dependencies ─────────────────────────────────────────────────────────────
install:
	uv sync

install-dev:
	uv sync --dev

# ── Quick eval, no Docker (in-memory checkpointer, in-process graph) ─────────
run-local:
	cd backend && uv run uvicorn api.main_local:app --host 0.0.0.0 --port 8000 --reload

dev-local:
	honcho start -f Procfile.local

# ── Tests ─────────────────────────────────────────────────────────────────────
test:
	cd backend && uv run pytest tests/ -v --timeout=60

test-unit:
	cd backend && uv run pytest tests/unit/ -v

# ── Code quality ──────────────────────────────────────────────────────────────
lint:
	cd backend && uv run ruff check .
	cd backend && uv run mypy . --ignore-missing-imports

format:
	cd backend && uv run ruff format .
	cd backend && uv run ruff check . --fix
