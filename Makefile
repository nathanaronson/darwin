# Darwin dev helper. Run `make` or `make help` to see targets.

SHELL := /bin/bash
.DEFAULT_GOAL := help

.PHONY: help \
        install install-backend install-frontend \
        dev backend frontend \
        seed run replay smoke eval \
        test lint format check \
        paper \
        clean clean-db reset

help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "\nTargets:\n"} \
	      /^[a-zA-Z0-9_-]+:.*##/ {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# ---- setup ----

install: install-backend install-frontend ## Install backend + frontend deps

install-backend: ## uv sync backend with dev extras
	cd backend && uv sync --extra dev

install-frontend: ## npm install frontend
	cd frontend && npm install

seed: ## Initialize DB and insert baseline-v0 (idempotent)
	cd backend && uv run python ../scripts/seed_baseline.py

# ---- running ----

dev: ## Run backend + frontend together via honcho
	honcho start

backend: ## Run backend only (uvicorn --reload on :8000)
	cd backend && uv run uvicorn darwin.api.server:app --host 0.0.0.0 --port 8000 \
	  --reload --reload-exclude 'darwin/engines/generated/*' --reload-exclude '*.db'

frontend: ## Run frontend only (vite dev on :5173)
	cd frontend && npm run dev

run: ## Run one generation end-to-end from CLI (override N=<n>)
	cd backend && uv run python -m darwin.orchestration.run --generations $(or $(N),1)

replay: ## Replay persisted generations over the WS bus (GEN=<n> to pin one)
	cd backend && uv run python ../scripts/replay.py $(if $(GEN),--gen $(GEN))

smoke: ## 10-move self-play smoke test against baseline
	cd backend && uv run python ../scripts/smoke_self_play.py

eval: ## Head-to-head match: make eval WHITE=baseline-v0 BLACK=random [N=10]
	@if [ -z "$(WHITE)" ] || [ -z "$(BLACK)" ]; then \
	  echo "usage: make eval WHITE=<engine> BLACK=<engine> [N=10]"; exit 2; \
	fi
	cd backend && uv run python ../scripts/eval_match.py \
	  --white $(WHITE) --black $(BLACK) --n $(or $(N),10)

# ---- quality ----

test: ## Run backend tests
	cd backend && uv run pytest -q

lint: ## Ruff check
	cd backend && uv run ruff check .

format: ## Ruff format in-place
	cd backend && uv run ruff format .

check: lint test ## Lint + tests (pre-PR gate)

# ---- paper ----

paper: ## Build docs/workflow.pdf via latexmk
	cd docs && latexmk -pdf -interaction=nonstopmode workflow.tex && latexmk -c workflow.tex

# ---- cleanup ----

clean-db: ## Delete the SQLite DB (re-run `make seed` after)
	rm -f backend/darwin.db backend/darwin.db-journal

clean: ## Remove Python + tooling caches
	find . -type d \( -name __pycache__ -o -name .pytest_cache -o -name .ruff_cache \) \
	  -not -path './frontend/node_modules/*' -exec rm -rf {} + 2>/dev/null || true

reset: clean-db seed ## Drop DB and re-seed baseline
