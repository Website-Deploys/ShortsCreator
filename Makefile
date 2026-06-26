# Project Olympus - developer task runner.
# Uses `uv` for fast, reproducible dependency management.

.DEFAULT_GOAL := help
.PHONY: help install lint format typecheck test run-api run-worker compose-up compose-down

help: ## Show this help.
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Create the virtualenv and install all (incl. dev) dependencies.
	uv venv
	uv pip install -e ".[dev]"

lint: ## Run the linter.
	uv run ruff check src tests

format: ## Auto-format the codebase.
	uv run ruff format src tests
	uv run ruff check --fix src tests

typecheck: ## Run the static type checker.
	uv run mypy

test: ## Run the test suite.
	uv run pytest

run-api: ## Run the API server locally (reload enabled in development).
	uv run uvicorn olympus.apps.backend_api.main:app --reload --host 0.0.0.0 --port 8000

run-worker: ## Run a Celery worker subscribed to the core queues.
	uv run celery -A olympus.apps.workers.worker:celery_app worker \
	  --queues default,ingest,transcribe,analyze,render --loglevel INFO

compose-up: ## Start local infrastructure (Postgres, Redis) via Docker Compose.
	docker compose up -d

compose-down: ## Stop local infrastructure.
	docker compose down
