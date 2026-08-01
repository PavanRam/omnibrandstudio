web:    uv run uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 4
worker: uv run python -m worker.main
frontend: bash scripts/run_frontend.sh dev
