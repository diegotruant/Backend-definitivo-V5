PYTHON ?= python
UVICORN_HOST ?= 127.0.0.1
UVICORN_PORT ?= 8000
UVICORN_RELOAD ?= true

.PHONY: install run test test-all hardening-test stress-test multitenant-stress lint format typecheck precommit

install:
	$(PYTHON) -m pip install -r requirements-dev.txt

run:
	$(PYTHON) -m uvicorn api_app:app --host $(UVICORN_HOST) --port $(UVICORN_PORT) $(if $(filter true,$(UVICORN_RELOAD)),--reload,)

test:
	$(PYTHON) -m pytest -q tests/pytest_smoke.py

test-all:
	$(PYTHON) -m pytest -q tests/pytest_*.py

hardening-test:
	$(PYTHON) -m pytest -q -m "hardening" tests/pytest_hardening_*.py

stress-test:
	$(PYTHON) -m pytest -q -m "hardening and stress" tests/pytest_hardening_*.py

multitenant-stress:
	$(PYTHON) tools/stress/multitenant_stress.py --base-url http://$(UVICORN_HOST):$(UVICORN_PORT) --profile balanced --duration-s 60 --concurrency 32 --output-dir stress_outputs/balanced

lint:
	$(PYTHON) -m ruff check tests scripts

format:
	$(PYTHON) -m black api_app.py api tests scripts

typecheck:
	$(PYTHON) -m mypy --explicit-package-bases tests/pytest_smoke.py

precommit:
	pre-commit run --all-files
