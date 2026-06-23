PYTHON ?= python3
UVICORN_HOST ?= 127.0.0.1
UVICORN_PORT ?= 8000
UVICORN_RELOAD ?= true

.PHONY: install run test test-all hardening-test stress-test multitenant-stress lint format typecheck check precommit openapi openapi-frontend demo-wt

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

check: lint typecheck test-all hardening-test

openapi:
	$(PYTHON) scripts/export_openapi.py

openapi-frontend: openapi
	cd frontend && npm run codegen:api

precommit:
	pre-commit run --all-files
