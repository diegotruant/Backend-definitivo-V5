PYTHON ?= python3
UVICORN_HOST ?= 127.0.0.1
UVICORN_PORT ?= 8000
UVICORN_RELOAD ?= true

.PHONY: install run test test-all hardening-test stress-test lockdown-test integrity-test coverage-test api-matrix-test perfection-test multitenant-stress lint format typecheck check precommit openapi openapi-frontend

install:
	$(PYTHON) -m pip install -r requirements-dev.txt

run:
	$(PYTHON) -m uvicorn api_app:app --host $(UVICORN_HOST) --port $(UVICORN_PORT) $(if $(filter true,$(UVICORN_RELOAD)),--reload,)

test:
	$(PYTHON) -m pytest -q tests/pytest_smoke.py

test-all:
	$(PYTHON) -m pytest -q tests/pytest_*.py pytest_script_suite.py

hardening-test:
	$(PYTHON) -m pytest -q -m "hardening" tests/pytest_hardening_*.py tests/pytest_security_hardening.py

stress-test:
	$(PYTHON) -m pytest -q -m "hardening and stress" tests/pytest_hardening_*.py

lockdown-test:
	$(PYTHON) -m pytest -q tests/pytest_engine_lockdown_v1.py tests/pytest_suite_integrity.py --tb=short

integrity-test:
	$(PYTHON) -m pytest -q tests/pytest_suite_integrity.py --tb=short

api-matrix-test:
	$(PYTHON) -m pytest -q tests/pytest_openapi_http_matrix.py --tb=short

perfection-status:
	$(PYTHON) scripts/perfection_status.py

perfection-test:
	$(PYTHON) -m pytest -q tests/pytest_engine_unit_hardening.py tests/pytest_perfection_http_strict.py --tb=short

coverage-test:
	$(PYTHON) -m pytest -q tests/pytest_*.py \
		--cov=engines --cov=api --cov-branch \
		--cov-report=term-missing:skip-covered \
		--cov-report=json
	$(PYTHON) scripts/check_coverage_baseline.py

multitenant-stress:
	$(PYTHON) tools/stress/multitenant_stress.py --base-url http://$(UVICORN_HOST):$(UVICORN_PORT) --profile balanced --duration-s 60 --concurrency 32 --output-dir stress_outputs/balanced

lint:
	$(PYTHON) -m ruff check api api_app.py tests scripts

format:
	$(PYTHON) -m black api api_app.py tests scripts

typecheck:
	$(PYTHON) -m mypy --explicit-package-bases api api_app.py

typecheck-metabolic:
	$(PYTHON) -m mypy --explicit-package-bases engines/metabolic

check: lint typecheck test-all hardening-test lockdown-test integrity-test api-matrix-test perfection-test coverage-test

openapi:
	$(PYTHON) scripts/export_openapi.py

openapi-frontend: openapi
	cd frontend && npm run codegen:api

precommit:
	pre-commit run --all-files
