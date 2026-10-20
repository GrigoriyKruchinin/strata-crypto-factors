.PHONY: install lint format typecheck test check backtest download-history compose-config

UV ?= uv
COMPOSE_LOCAL = docker compose -f docker-compose.local.yml

install:
	$(UV) sync

lint:
	$(UV) run ruff check src tests
	$(UV) run ruff format --check src tests

format:
	$(UV) run ruff format src tests
	$(UV) run ruff check --fix src tests

typecheck:
	$(UV) run mypy src tests

test:
	$(UV) run pytest -m "not integration"

check: lint typecheck test

compose-config:
	$(COMPOSE_LOCAL) config --quiet

download-history:
	$(UV) run strata download-history $(ARGS)

backtest:
	$(UV) run strata backtest $(ARGS)
