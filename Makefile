.PHONY: doctor test unit-test integration-test e2e lint quality dbt-parse dbt-test airflow-check shiftforge-test benchmark demo demo-setup docker-up docker-down

PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
HOSPITALITY := hospitality-snowflake-data-platform

doctor:
	PYTHONPATH=src $(PYTHON) -m agentic_data_platform.cli doctor .

test: unit-test integration-test

unit-test:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src $(PYTHON) -m pytest -q -p no:cacheprovider tests

integration-test:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src $(PYTHON) -m pytest -q -p no:cacheprovider integration/e2e-tests

e2e: integration-test
	./scripts/demo-platform.sh

lint:
	$(PYTHON) -m ruff check src tests integration/e2e-tests

quality:
	$(MAKE) unit-test
	cd $(HOSPITALITY) && $(abspath $(PYTHON)) -m pytest -q -p no:cacheprovider
	cd local-data-harness && npm run quality

dbt-parse:
	$(PYTHON) scripts/parse_dbt.py

dbt-test:
	@if command -v dbt >/dev/null 2>&1; then dbt test --project-dir $(HOSPITALITY)/dbt --profiles-dir $(HOSPITALITY)/dbt; else echo 'SKIP - dbt executable unavailable'; fi

airflow-check:
	PYTHONPATH=src $(PYTHON) -m agentic_data_platform.cli airflow health --project $(HOSPITALITY)

shiftforge-test:
	PYTHONPATH=shiftforge/src $(PYTHON) -m pytest -q -p no:cacheprovider shiftforge/tests

benchmark:
	PYTHONPATH=src $(PYTHON) -m agentic_data_platform.cli platform graph --project $(HOSPITALITY) >/dev/null

demo-setup:
	./scripts/setup-demo.sh

demo:
	./scripts/demo-platform.sh

docker-up:
	cd $(HOSPITALITY) && docker compose up -d

docker-down:
	cd $(HOSPITALITY) && docker compose down
