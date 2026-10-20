.PHONY: install lint format typecheck test check download-history research backtest paper db-upgrade ingest-db

UV ?= uv

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

download-history:
	$(UV) run strata download-history $(ARGS)

research:
	$(UV) run strata research $(STEP) $(ARGS)

backtest:
	$(UV) run strata backtest $(ARGS)

paper:
	$(UV) run strata paper-cycle $(ARGS)

db-upgrade:
	$(UV) run strata db-upgrade

ingest-db:
	$(UV) run strata ingest-db
