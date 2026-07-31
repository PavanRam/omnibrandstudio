.PHONY: install install-dev run worker dev frontend dev-full run-local-eval test-local-eval check-local-eval test test-unit test-integration smoke lint format migrate migrate-docker migrate-down migrate-history seed seed-admin seed-golden check-env up down down-reset fresh-start restart restart-api restart-worker logs certs setup poll-reviews check-sample-briefs urls

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
	honcho start -f Procfile.backend

frontend:
	cd frontend && npm run dev

dev-full:
	honcho start

run-local-eval:
	# TEMP_LOCAL_EVAL: Local-only startup path that bypasses docker dependencies.
	cd backend && LOCAL_DEV_MODE=1 ENABLE_LOCAL_EVAL=1 uv run uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

test-local-eval:
	# TEMP_LOCAL_EVAL: Focused test run for local eval and local-dev safety gates.
	cd backend && LOCAL_DEV_MODE=1 ENABLE_LOCAL_EVAL=1 uv run pytest tests/ -k "local_eval or local_dev or local_mode" -v

check-local-eval:
	# TEMP_LOCAL_EVAL: Quick endpoint probe for local eval route.
	curl -s -X GET http://localhost:8000/health

# ── Tests ─────────────────────────────────────────────────────────────────────
test:
	cd backend && uv run pytest tests/ -v --timeout=60

test-unit:
	cd backend && uv run pytest tests/unit/ -v

test-integration:
	cd backend && uv run pytest tests/integration/ -v --timeout=120

smoke:
	uv run python scripts/smoke_test.py

# Free-plan-friendly alternative to an Airtable webhook Automation: polls the
# Reviews table for reviewer decisions and applies them via /airtable-decide.
poll-reviews:
	uv run python scripts/airtable_poll_reviews.py

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

migrate-docker:
	docker compose exec -T api sh -lc "cd /app && PYTHONPATH=/opt/venv/lib/python3.12/site-packages python -m alembic upgrade head"

migrate-down:
	cd backend && uv run alembic downgrade -1

migrate-history:
	cd backend && uv run alembic history

seed:
	cd backend && uv run python ../scripts/seed_prompts.py

seed-admin:
	cd backend && uv run python scripts/seed_dev_admin.py

seed-golden:
	cd backend && uv run python ../scripts/seed_golden_datasets.py

# ── Infrastructure ────────────────────────────────────────────────────────────
# check-env: fail fast with a clear message instead of a raw asyncpg
# traceback when .env is missing, or when POSTGRES_PASSWORD in .env doesn't
# match what an already-initialized postgres_data volume was created with
# (Postgres only reads POSTGRES_PASSWORD on first volume init — changing .env
# later does not rotate it). Connects with the CURRENT host .env value over
# the docker network (a fresh throwaway psql container), not by exec-ing into
# the postgres container itself — that only ever has the value baked in at
# container creation and would trivially match itself.
check-env:
	@if [ ! -f .env ]; then \
		echo "ERROR: .env not found. Copy .env.example to .env and fill in values, then re-run make up."; \
		exit 1; \
	fi
	@if docker compose ps postgres --format '{{.State}}' 2>/dev/null | grep -q running; then \
		POSTGRES_PASSWORD=$$(grep -m1 '^POSTGRES_PASSWORD=' .env | cut -d= -f2-); \
		if ! docker run --rm --network omnibrandstudio_default -e PGPASSWORD="$$POSTGRES_PASSWORD" postgres:16-alpine \
			psql -h postgres -U omnibrand -d omnibrand -c "SELECT 1" >/dev/null 2>&1; then \
			echo "ERROR: postgres rejected the password currently in .env. Your omnibrandstudio_postgres_data"; \
			echo "       volume was likely initialized with a different POSTGRES_PASSWORD than .env has now."; \
			echo "       Fix: docker compose down -v postgres   (drops only the postgres volume/data)"; \
			echo "       then re-run: make up"; \
			exit 1; \
		fi; \
	fi

up: check-env
	# Bring up long-running services and wait for health/readiness.
	docker compose up -d --wait postgres redis minio litellm langfuse prometheus grafana jaeger redis-exporter postgres-exporter mailhog api worker
	# One-shot init job exits 0 by design; run it separately so --wait does not fail.
	docker compose up -d createbuckets
	# Re-check now that postgres is confirmed up (first run above may have
	# skipped the password check if postgres wasn't running yet).
	# NOTE: intentionally the bare "make" word here, not a make-variable
	# reference to the invoking binary. On Windows the GnuWin32 install path
	# contains "Program Files (x86)"; substituting that path into the recipe
	# (quoted or not) breaks both bash's parser and make's own recipe
	# handling. Plain "make" avoids embedding that path at all.
	make check-env
	# Keep DB schema current in the same runtime context the API uses.
	make migrate-docker
	# Ensure org/brand/prompt rows exist before admin-seed depends on them.
	make seed
	# Ensure default dev admin exists after startup/migration.
	docker compose exec -T api python scripts/seed_dev_admin.py

down:
	docker compose down

down-reset:
	docker compose down -v

fresh-start: install certs up

# ── Restart Services ──────────────────────────────────────────────────────────
# RESTART GUIDE:
#   make restart      → Full restart (all services). Use after major config changes.
#   make restart-api  → Restart API only. Use after editing routes, endpoints, auth, schemas.
#   make restart-worker → Restart worker only. Use after editing agents, campaign logic, RAG.

restart: down up

restart-api:
	docker compose restart api

restart-worker:
	docker compose restart worker

logs:
	docker compose logs -f api worker

# ── Observability access ──────────────────────────────────────────────────────
# Print the URLs + login credentials for every local observability tool. Reads
# secrets from .env so the printed values match what the containers actually use.
urls:
	@echo ""
	@echo "OmniBrand Studio — local service access"
	@echo "======================================================================"
	@if [ -f .env ]; then . ./.env; fi; \
	printf "%-14s %-30s %-22s %s\n" "TOOL" "URL" "USER" "PASSWORD"; \
	printf "%-14s %-30s %-22s %s\n" "----" "---" "----" "--------"; \
	printf "%-14s %-30s %-22s %s\n" "App API"     "http://localhost:8000/docs" "$${DEV_ADMIN_EMAIL:-admin@omnibrand.local}" "$${DEV_ADMIN_PASSWORD:-OmniBrand!123}"; \
	printf "%-14s %-30s %-22s %s\n" "Grafana"     "http://localhost:3000"      "admin" "$${GRAFANA_ADMIN_PASSWORD:-admin}"; \
	printf "%-14s %-30s %-22s %s\n" "Prometheus"  "http://localhost:9090"      "-" "(no auth)"; \
	printf "%-14s %-30s %-22s %s\n" "Jaeger"      "http://localhost:16686"     "-" "(no auth)"; \
	printf "%-14s %-30s %-22s %s\n" "Langfuse"    "http://localhost:3001"      "$${LANGFUSE_INIT_USER_EMAIL:-admin@omnibrand.local}" "$${LANGFUSE_INIT_USER_PASSWORD:-OmniBrand!123}"; \
	printf "%-14s %-30s %-22s %s\n" "MinIO"       "http://localhost:9001"      "omnibrand" "$${MINIO_PASSWORD}"; \
	printf "%-14s %-30s %-22s %s\n" "Mailhog"     "http://localhost:8025"      "-" "(no auth)"; \
	echo ""; \
	echo "See docs/observability/ for dashboards, metric catalog, and query recipes."
	@echo ""

# ── TLS / JWT keys ────────────────────────────────────────────────────────────
certs:
	mkdir -p certs
	openssl genrsa -out certs/private_key.pem 2048
	openssl rsa -in certs/private_key.pem -pubout -out certs/public_key.pem
	chmod 600 certs/private_key.pem
	@echo "JWT keys generated in certs/"

# ── Full local setup (run once after cloning) ────────────────────────────────
setup: install certs up
	@echo ""
	@echo "Foundation ready. Run 'make smoke' to verify."
	@echo "Backend only: make dev | Frontend only: make frontend | Both: make dev-full"
