SHELL := /bin/bash
export PYTHONPATH := apps/api
PY := uv run

.DEFAULT_GOAL := check

.PHONY: install check lint types arch test eval eval-retrieval eval-ocr eval-sentiment eval-lint eval-baseline eval-acl run worker up down logs migrate ingest seed demo demo-data demo-data-del fmt docs admin-install admin-dev admin-build admin-check admin-e2e prod-config prod-up smoke deploy-remote backup restore

install:
	uv sync
	cd apps/admin && npm ci

check: lint types arch test docs admin-check

lint:
	$(PY) ruff check .

fmt:
	$(PY) ruff format .
	$(PY) ruff check . --fix

types:
	$(PY) mypy

arch:                              # import cycles, layer order, and "api never calls a model"
	$(PY) lint-imports

test:
	$(PY) pytest

# Live tier: real Postgres and real providers. Costs money and needs keys, so it never runs in check.
test-live:
	$(PY) pytest -m "integration or eval"

eval:
	$(PY) python -m onboarding.evals --write $(ARGS)

eval-retrieval:
	$(PY) python -m onboarding.evals --retrieval-only --write $(ARGS)

eval-acl:                           # every (viewer, document) pair; no provider key, no generation
	$(PY) python -m onboarding.evals.acl --write $(ARGS)

eval-lint:                          # the set matches its contract and every gate has a mutant
	$(PY) pytest apps/api/tests/test_golden.py apps/api/tests/test_eval_gates_have_power.py apps/api/tests/test_eval_stats.py

eval-baseline:                      # pin this run: gate = Wilson lower bound of what it measured
	$(PY) python -m onboarding.evals --write-baseline --write $(ARGS)

eval-ocr:                          # extraction quality; needs no database and no provider key
	$(PY) python -m onboarding.evals.ocr $(ARGS)

eval-sentiment:                     # PROVIDER=keyword|prompt|jev, SPLIT=dev|test|all
	$(PY) python -m onboarding.evals.sentiment --provider $(or $(PROVIDER),prompt) --split $(or $(SPLIT),all) --repeat $(or $(REPEAT),1) $(ARGS) --write

run:
	$(PY) uvicorn onboarding.api.app:create_app --factory --reload --port 8000

cron:                              # one cron-style pass over reminders and the outbox
	PYTHONPATH=apps/api uv run python -m onboarding.app.scheduler --max-jobs 200

worker:
	$(PY) python -m onboarding.app.worker.main

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f api worker

prod-config:                       # validate the prod override without a real .env.prod
	docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env.prod config -q

prod-up:                           # production compose on the VM; needs .env.prod and TAG
	docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env.prod up -d

smoke:                             # public smoke test; BASE_URL overrides the default host
	./scripts/smoke.sh

deploy-remote:                     # on the VM: SHA=<commit> make deploy-remote
	@test -n "$(SHA)" || { echo "SHA is required" >&2; exit 2; }
	./scripts/deploy-remote.sh "$(SHA)"

backup:                            # consistent dump; BACKUP_S3_URI enables offsite upload
	./scripts/backup.sh

restore:                           # destructive: CONFIRM_RESTORE=yes FILE=<dump> make restore
	@test -n "$(FILE)" || { echo "FILE is required" >&2; exit 2; }
	CONFIRM_RESTORE=yes ./scripts/restore.sh "$(FILE)"

migrate:
	$(PY) alembic upgrade head

ingest:
	$(PY) python -m onboarding.cli ingest

seed:
	$(PY) python -m onboarding.cli seed --file infra/demo/employees.json

demo-data:
	docker compose run --rm api python -m onboarding.cli ingest
	docker compose run --rm api python -m onboarding.cli demo --reset --yes

demo: demo-data

demo-data-del:
	docker compose up -d postgres
	docker compose exec -T postgres psql -U onboarding -d onboarding -v ON_ERROR_STOP=1 < scripts/demo-data-del.sql

docs:
	$(PY) python scripts/check_docs.py

admin-install:
	cd apps/admin && npm ci

admin-dev:
	cd apps/admin && npm run dev

admin-build:
	cd apps/admin && npm run build

admin-check:
	cd apps/admin && npm run lint
	cd apps/admin && npm run typecheck
	cd apps/admin && npm run test

admin-e2e:
	cd apps/admin && npm run e2e
