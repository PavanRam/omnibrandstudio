.PHONY: install install-dev run worker dev test test-unit test-integration smoke lint format migrate migrate-down migrate-history seed up down logs certs setup

# ── Dependencies ─────────────────────────────────────────────────────────────
install:
	uv sync

install-dev:
	uv sync --dev

# ── Local development ─────────────────────────────────────────────────────────
run:
	cd backend && uv run uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

worker:
	cd backend && uv run python -m worker.main

dev:
	honcho start

# ── Tests ─────────────────────────────────────────────────────────────────────
test:
	cd backend && uv run pytest tests/ -v --timeout=60

test-unit:
	cd backend && uv run pytest tests/unit/ -v

test-integration:
	cd backend && uv run pytest tests/integration/ -v --timeout=120

smoke:
	uv run python scripts/smoke_test.py

# ── Code quality ──────────────────────────────────────────────────────────────
lint:
	cd backend && uv run ruff check .
	cd backend && uv run mypy . --ignore-missing-imports

format:
	cd backend && uv run ruff format .
	cd backend && uv run ruff check . --fix

# ── Database ──────────────────────────────────────────────────────────────────
migrate:
	cd backend && uv run alembic upgrade head

migrate-down:
	cd backend && uv run alembic downgrade -1

migrate-history:
	cd backend && uv run alembic history

seed:
	cd backend && uv run python ../scripts/seed_prompts.py

# ── Infrastructure ────────────────────────────────────────────────────────────
up:
	docker compose up -d --wait

down:
	docker compose down -v

logs:
	docker compose logs -f api worker

# ── TLS / JWT keys ────────────────────────────────────────────────────────────
certs:
	mkdir -p certs
	openssl genrsa -out certs/private_key.pem 2048
	openssl rsa -in certs/private_key.pem -pubout -out certs/public_key.pem
	chmod 600 certs/private_key.pem
	@echo "JWT keys generated in certs/"

# ── Full local setup (run once after cloning) ────────────────────────────────
setup: install certs up migrate seed
	@echo ""
	@echo "Foundation ready. Run 'make smoke' to verify."
	@echo "Run 'make run' (API) + 'make worker' (worker) or 'make dev' (both)."
