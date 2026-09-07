.PHONY: setup source-ddl generate-small generate-medium generate-large generate-smoke start airflow ingest dbt-run dbt-test dbt-docs quality demo test lint stop clean

SYSTEM_PYTHON := $(shell command -v python3.12 2>/dev/null || command -v python3.11 2>/dev/null || command -v python3)
PYTHON ?= .venv/bin/python
COMPOSE ?= docker compose

setup:
	@test -n "$(SYSTEM_PYTHON)" || (echo "Python 3.11+ is required" && exit 1)
	@test -x $(PYTHON) || $(SYSTEM_PYTHON) -m venv .venv
	@test -f .env || cp .env.example .env
	@test -f dbt/profiles.yml || cp dbt/profiles.yml.example dbt/profiles.yml
	$(PYTHON) -m pip install -e '.[dev,parquet]'
	$(PYTHON) -m data_generator.generate_source_ddl --root .

source-ddl:
	$(SYSTEM_PYTHON) -m data_generator.generate_source_ddl --root .

generate-small:
	$(PYTHON) -m data_generator.generate_oracle_data --scale small
	$(PYTHON) -m data_generator.generate_postgres_data --scale small
	$(PYTHON) -m data_generator.generate_file_data --scale small

generate-medium:
	$(PYTHON) -m data_generator.generate_oracle_data --scale medium
	$(PYTHON) -m data_generator.generate_postgres_data --scale medium
	$(PYTHON) -m data_generator.generate_file_data --scale medium

generate-large:
	$(PYTHON) -m data_generator.generate_oracle_data --scale large
	$(PYTHON) -m data_generator.generate_postgres_data --scale large
	$(PYTHON) -m data_generator.generate_file_data --scale large

generate-smoke:
	$(PYTHON) -m data_generator.generate_oracle_data --scale small --max-rows 10
	$(PYTHON) -m data_generator.generate_postgres_data --scale small --max-rows 10
	$(PYTHON) -m data_generator.generate_file_data --scale small --max-rows 100

start:
	$(COMPOSE) up airflow-init
	$(COMPOSE) up -d postgres airflow-webserver airflow-scheduler

airflow:
	$(COMPOSE) logs -f airflow-scheduler airflow-webserver

ingest:
	$(COMPOSE) exec airflow-scheduler airflow dags trigger hospitality_end_to_end_pipeline

dbt-run:
	$(COMPOSE) --profile tools run --rm dbt build --profiles-dir .

dbt-test:
	$(COMPOSE) --profile tools run --rm dbt test --profiles-dir .

dbt-docs:
	$(COMPOSE) --profile tools run --rm dbt docs generate --profiles-dir .

quality: test
	$(PYTHON) quality/checks/validate_generated_files.py sources/files/generated

demo:
	@echo "Run the SQL files in dashboards/ with the HOSPITALITY_ANALYST_ROLE."

test:
	$(PYTHON) -m pytest -q

lint:
	$(PYTHON) -m ruff check data_generator quality tests airflow/dags

stop:
	$(COMPOSE) down

clean:
	$(COMPOSE) down --volumes --remove-orphans
	find sources/files/generated -type f ! -name .gitkeep -delete
	find airflow/data/landing -type f ! -name .gitkeep -delete 2>/dev/null || true
	find airflow/data/source_exports -type f -delete 2>/dev/null || true
