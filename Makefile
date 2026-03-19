PYTHON ?= python3
PIP ?= $(PYTHON) -m pip
WEB_DIR ?= web
UVICORN_APP ?= app.main:app
UVICORN_HOST ?= 0.0.0.0
UVICORN_PORT ?= 8000
WEB_PORT ?= 5173

.PHONY: install install-backend install-web dev-backend dev-web dev docker-up test lint

install: install-backend install-web

install-backend:
	$(PIP) install -r requirements.txt

install-web:
	npm --prefix $(WEB_DIR) install

dev-backend:
	uvicorn $(UVICORN_APP) --host $(UVICORN_HOST) --port $(UVICORN_PORT) --reload

dev-web:
	npm --prefix $(WEB_DIR) run dev -- --host 0.0.0.0 --port $(WEB_PORT)

dev:
	bash -lc 'set -euo pipefail; trap "kill 0" EXIT; $(MAKE) dev-backend & $(MAKE) dev-web & wait'

docker-up:
	docker compose up --build

test:
	pytest -q

lint:
	python -m py_compile app/*.py
