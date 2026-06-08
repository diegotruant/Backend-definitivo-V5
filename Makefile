PYTHON ?= python
UVICORN_HOST ?= 127.0.0.1
UVICORN_PORT ?= 8000
UVICORN_RELOAD ?= true

.PHONY: install run test lint format typecheck precommit

install:
	$(PYTHON) -m pip install -r requirements-dev.txt

run:
	$(PYTHON) -m uvicorn api_app:app --host $(UVICORN_HOST) --port $(UVICORN_PORT) $(if $(filter true,$(UVICORN_RELOAD)),--reload,)

test:
	$(PYTHON) -m pytest -q tests/pytest_smoke.py

lint:
	$(PYTHON) -m ruff check tests scripts

format:
	$(PYTHON) -m black api_app.py tests scripts

typecheck:
	$(PYTHON) -m mypy --explicit-package-bases tests/pytest_smoke.py

precommit:
	pre-commit run --all-files
