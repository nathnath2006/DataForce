# Developer shortcuts. Run from the repository root.
BACKEND := backend
VENV    := $(BACKEND)/.venv/bin

# testdata: load the synthetic 'Test data' workspace (replaces it; deletes old demo-* workspaces)
.PHONY: testdata help db-up db-down migrate db-reset-test test test-integration test-all lint lock notebook ui ui-dev api-types image

# Used by `make lock`: pip-tools from the dev extras. UPGRADE=1 also bumps every pinned version.
PIP_COMPILE := $(CURDIR)/$(VENV)/pip-compile --generate-hashes --strip-extras --allow-unsafe --quiet

help:
	@echo "db-up            start Postgres + pgvector (docker compose, localhost:5433) and wait until healthy"
	@echo "db-down          stop the database (data volume is kept)"
	@echo "migrate          alembic upgrade head on the dev database"
	@echo "db-reset-test    drop and recreate the schema of dataforce_test (after changing models/migrations)"
	@echo "test             unit tests only (no database, no network)"
	@echo "test-integration tests that need the database (make db-up first)"
	@echo "test-all         everything except live tests"
	@echo "lint             ruff check"
	@echo "lock             regenerate the three hashed locks (UPGRADE=1 to bump)"
	@echo "ui               build the frontend if needed and serve the local UI on http://127.0.0.1:8800"
	@echo "api-types        refresh the OpenAPI snapshot and regenerate frontend/src/api.gen.ts"
	@echo "ui-dev           API on 8800 + Vite dev server on 127.0.0.1:5173 (hot reload)"
	@echo "image            build the hosted container image (dataforce:local); see docs/HOSTING-PLAN.md"
	@echo "notebook         open the Milestone 1 demo notebook in JupyterLab"
	@echo "testdata         load the synthetic 'Test data' workspace for the app"

# api-types: refresh the OpenAPI snapshot from the app, then regenerate frontend/src/api.gen.ts
api-types:
	cd $(BACKEND) && .venv/bin/python -c "import json; from app.api.main import create_app; print(json.dumps(create_app().openapi(), indent=1, sort_keys=True))" > ../frontend/src/openapi.snapshot.json
	cd frontend && node scripts/gen-api-types.mjs

db-up:
	docker compose up -d --wait db

db-down:
	docker compose down

migrate:
	cd $(BACKEND) && .venv/bin/alembic upgrade head

# The integration fixtures migrate dataforce_test on their own; reset it only when its schema
# drifted from models.py (the migration test then tells you to run this).
db-reset-test:
	docker compose exec -T db psql -v ON_ERROR_STOP=1 -U $${POSTGRES_USER:-dataforce} -d dataforce_test \
		-c 'DROP SCHEMA public CASCADE' -c 'CREATE SCHEMA public' -c 'CREATE EXTENSION vector'

test:
	cd $(BACKEND) && .venv/bin/pytest -m "not integration and not live"

test-integration:
	cd $(BACKEND) && .venv/bin/pytest -m integration

test-all:
	cd $(BACKEND) && .venv/bin/pytest -m "not live"

lint:
	cd $(BACKEND) && .venv/bin/ruff check app tests alembic

# Hashed, pinned locks (SR3-08). Runtime lock first, then the dev lock (runtime + dev tools).
# Install with: pip install --require-hashes -r requirements.lock && pip install --no-deps -e .
lock:
	cd $(BACKEND) && $(PIP_COMPILE) $(if $(UPGRADE),--upgrade) \
		--output-file=requirements.lock pyproject.toml
	cd $(BACKEND) && $(PIP_COMPILE) $(if $(UPGRADE),--upgrade) --constraint requirements.lock --extra dev \
		--output-file=requirements-dev.lock pyproject.toml
	cd $(BACKEND) && $(PIP_COMPILE) $(if $(UPGRADE),--upgrade) --constraint requirements.lock --extra notebook \
		--output-file=requirements-notebook.lock pyproject.toml

notebook:
	cd $(BACKEND) && .venv/bin/jupyter lab ../notebooks/M1_engine_demo.ipynb

# Local web UI. The frontend is rebuilt only when dist/index.html is missing or older than a file in src.
ui:
	$(VENV)/dataforce secrets init --if-missing
	@if [ ! -f frontend/dist/index.html ] || [ -n "$$(find frontend/src -type f -newer frontend/dist/index.html 2>/dev/null | head -1)" ]; then \
		cd frontend && npm ci && npm run build; \
	fi
	$(VENV)/dataforce ui

ui-dev:
	$(VENV)/dataforce secrets init --if-missing
	@sh scripts/ui-dev.sh

testdata:
	$(VENV)/dataforce demo testdata --replace --drop-seed-workspaces

# Container image for Cloud Run (API + built frontend). Local build only; nothing is pushed.
image:
	docker build -t dataforce:local .
