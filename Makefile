.PHONY: doctor test unit-test integration-test e2e lint quality dbt-parse dbt-test airflow-check shiftforge-test benchmark demo demo-setup demo-data demo-ui frontend-typecheck frontend-build docker-up docker-down

PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
PYTHON_BIN := $(shell $(PYTHON) -c 'import sys; print(sys.executable)')
HOSPITALITY := hospitality-snowflake-data-platform
WEB := apps/web

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
	cd $(HOSPITALITY) && $(PYTHON_BIN) -m pytest -q -p no:cacheprovider
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

frontend-typecheck:
	cd $(WEB) && npm run typecheck

frontend-build:
	cd $(WEB) && npm run build

demo-setup:
	./scripts/setup-demo.sh

demo-data:
	./scripts/init-demo-data.sh

demo:
	./scripts/demo-platform.sh

demo-ui:
	./scripts/demo-ui.sh

docker-up:
	cd $(HOSPITALITY) && docker compose up -d

docker-down:
	cd $(HOSPITALITY) && docker compose down


.PHONY: altimate-parity parity-summary

altimate-parity:
	$(PYTHON) scripts/check_altimate_parity.py

parity-summary:
	-$(PYTHON) scripts/check_altimate_parity.py


.PHONY: install typecheck test-unit test-integration test-airflow test-dbt test-providers test-agentic test-ui benchmark-lineage benchmark-airflow benchmark-agentic demo-agentic demo-airflow parity airflow-parity final-audit verify ci

install:
	$(PYTHON) -m pip install -e '.[dev]'

typecheck: frontend-typecheck

test-unit: unit-test

test-integration: integration-test

test-airflow:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src $(PYTHON) -m pytest -q -p no:cacheprovider tests/test_airflow_control_plane.py tests/integration/test_airflow_full_surface.py

test-dbt:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src $(PYTHON) -m pytest -q -p no:cacheprovider tests/test_dbt_runtime.py tests/test_dbt_validators.py tests/test_dbt_test_generation.py

test-providers:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src $(PYTHON) -m pytest -q -p no:cacheprovider tests/test_providers.py tests/test_provider_control.py tests/test_provider_expanded.py tests/test_provider_tool_messages.py

test-agentic:
	$(PYTHON) scripts/parse_dbt.py
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src $(PYTHON) -m pytest -q -p no:cacheprovider tests/test_agent*.py tests/test_ground_truth_isolation.py tests/test_proactive_agentic_monitoring.py tests/test_quality_agentic_primitives.py tests/test_selective_recovery.py tests/test_asset_certification.py tests/test_cross_system_impact_graph.py tests/test_mapping_transformation_agents.py tests/test_rca_evidence_grounding.py

test-ui:
	cd $(WEB) && npm run typecheck && npm run build

benchmark-lineage:
	PYTHONPATH=src $(PYTHON) benchmarks/lineage/run.py

benchmark-airflow:
	PYTHONPATH=src $(PYTHON) benchmarks/airflow/run.py

benchmark-agentic:
	PYTHONPATH=src $(PYTHON) benchmarks/agentic/run.py

demo-agentic:
	PYTHONPATH=src $(PYTHON) scripts/demo-agentic-investigation.py

demo-airflow:
	PYTHONPATH=src $(PYTHON) -m agentic_data_platform.cli airflow inventory --project $(HOSPITALITY)

parity:
	PYTHONPATH=src $(PYTHON) scripts/check_parity_gate.py --ledger altimate
	PYTHONPATH=src $(PYTHON) scripts/altimate_parity_evidence.py

airflow-parity:
	PYTHONPATH=src $(PYTHON) scripts/check_parity_gate.py --ledger airflow
	PYTHONPATH=src $(PYTHON) scripts/check_airflow_gate.py

verify: lint typecheck test-unit test-integration test-airflow test-dbt test-providers test-agentic test-hospitality shiftforge-test parity airflow-parity parity-v2 certification-local benchmark-lineage benchmark-airflow benchmark-agentic demo-smoke test-ui final-audit

ci: verify

.PHONY: test-hospitality demo-smoke

test-hospitality:
	cd $(HOSPITALITY) && $(PYTHON_BIN) -m pytest -q -p no:cacheprovider

demo-smoke:
	bash scripts/demo-full-platform.sh


final-audit:
	PYTHONPATH=src $(PYTHON) scripts/final_acceptance_audit.py
	PYTHONPATH=src $(PYTHON) -m pytest -q -p no:cacheprovider tests/test_final_acceptance_audit.py



.PHONY: snowflake-live-e2e snowflake-pipeline-live-e2e airflow-live-e2e agent-live-e2e dbt-live-e2e live-e2e

snowflake-live-e2e:
	PYTHONPATH=src $(PYTHON) scripts/live_snowflake_e2e.py

snowflake-pipeline-live-e2e:
	PYTHONPATH=src $(PYTHON) scripts/live_snowflake_pipeline_testing.py

airflow-live-e2e:
	PYTHONPATH=src $(PYTHON) scripts/live_airflow_e2e.py

agent-live-e2e:
	PYTHONPATH=src $(PYTHON) scripts/live_agent_e2e.py

dbt-live-e2e:
	PYTHONPATH=src $(PYTHON) scripts/live_dbt_e2e.py

live-e2e: snowflake-live-e2e airflow-live-e2e agent-live-e2e dbt-live-e2e


.PHONY: conformance certification-local certification-live parity-v2

conformance:
	$(PYTHON) scripts/parse_dbt.py
	PYTHONPATH=src $(PYTHON) scripts/run_conformance.py

certification-local:
	PYTHONPATH=src $(PYTHON) scripts/run_certification.py

certification-live:
	PYTHONPATH=src $(PYTHON) scripts/run_certification.py --live

parity-v2: conformance
	PYTHONPATH=src $(PYTHON) scripts/generate_parity_ledger_v2.py


.PHONY: snowflake-pipeline-test
snowflake-pipeline-test:
	PYTHONPATH=src $(PYTHON) -m pytest -q tests/test_snowflake_pipeline_testing.py tests/test_snowflake_pipeline_surface.py tests/test_snowflake_failure_lab.py


.PHONY: capability-superiority-check coco-certification-reports coco-parity-check snowflake-extension-check snowflake-governed-mutation-test
capability-superiority-check:
	PYTHONPATH=src $(PYTHON) scripts/check_capability_superiority.py --json
	PYTHONPATH=src $(PYTHON) -m pytest -q tests/test_capability_superiority_ledger.py

coco-certification-reports:
	PYTHONPATH=src $(PYTHON) scripts/generate_coco_certification.py

coco-parity-check: capability-superiority-check coco-certification-reports
	PYTHONPATH=src $(PYTHON) scripts/check_capability_superiority.py --scope coco --require-coco-parity --json

snowflake-extension-check: capability-superiority-check coco-certification-reports
	PYTHONPATH=src $(PYTHON) scripts/check_capability_superiority.py --scope extensions --json

snowflake-governed-mutation-test:
	PYTHONPATH=src $(PYTHON) -m pytest -q tests/test_snowflake_governed_mutation.py


.PHONY: capability-superiority-p1-check
capability-superiority-p1-check:
	PYTHONPATH=src $(PYTHON) -m pytest -q \
		tests/test_unified_semantic_search.py \
		tests/test_parallel_subagents.py \
		tests/test_enforceable_plugin_hooks.py \
		tests/test_automation_scheduler.py \
		tests/test_plugin_bundles.py \
		tests/test_snowflake_managed_dbt.py \
		tests/test_semantic_layer.py \
		tests/test_semantic_adapters.py \
		tests/test_cortex_agents.py \
		tests/test_hosted_runner.py \
		tests/test_hosted_runner_deployment.py \
		tests/test_notebook_agent.py \
		tests/test_agentic_browser.py \
		tests/test_snowflake_app_builder.py \
		tests/test_snowpark_model_registry.py \
		tests/test_snowpark_ml_workflow.py \
		tests/test_ai_workflows.py \
		tests/test_ide_bridge.py \
		tests/test_advanced_live_capabilities.py \
		tests/test_advanced_capability_extensions.py \
		tests/test_shell_sandbox.py \
		tests/test_memory_personalization.py \
		tests/test_todo_management.py \
		tests/test_coco_modes.py \
		tests/test_workspace_files.py \
		tests/test_git_parity.py \
		tests/test_coding_workspace.py \
		tests/test_session_checkpoints.py \
		tests/test_context_controls.py \
		tests/test_rules_instructions.py

.PHONY: advanced-live-e2e
advanced-live-e2e:
	PYTHONPATH=src $(PYTHON) scripts/live_advanced_capabilities.py

.PHONY: hospitality-generate hospitality-validate-files hospitality-bootstrap-snowflake hospitality-stage-internal hospitality-copy-load hospitality-upload-s3 hospitality-snowpipe-monitor hospitality-stream-check hospitality-dbt hospitality-reconcile hospitality-dq hospitality-certify hospitality-failure-fixtures hospitality-failure-certify hospitality-e2e-local hospitality-e2e-live hospitality-reset hospitality-teardown hospitality-test
hospitality-generate:
	$(PYTHON) scripts/hospitality_testbed/generate_data.py --preset $${ADE_TESTBED_SCALE:-tiny} --seed $${ADE_TESTBED_SEED:-42}

hospitality-validate-files:
	$(PYTHON) scripts/hospitality_testbed/validate_files.py

hospitality-bootstrap-snowflake:
	$(PYTHON) scripts/hospitality_testbed/bootstrap_snowflake.py --mode $${ADE_TESTBED_MODE:-local}

hospitality-stage-internal:
	$(PYTHON) scripts/hospitality_testbed/stage_internal_files.py

hospitality-copy-load:
	$(PYTHON) scripts/hospitality_testbed/run_copy_loads.py --mode local

hospitality-upload-s3:
	$(PYTHON) scripts/hospitality_testbed/upload_to_s3.py

hospitality-snowpipe-monitor:
	$(PYTHON) scripts/hospitality_testbed/monitor_snowpipe.py

hospitality-stream-check:
	$(PYTHON) scripts/hospitality_testbed/monitor_streams.py

hospitality-dbt:
	$(PYTHON) scripts/hospitality_testbed/run_dbt.py

hospitality-reconcile:
	$(PYTHON) scripts/hospitality_testbed/reconcile_pipeline.py

hospitality-dq:
	$(PYTHON) scripts/hospitality_testbed/validate_pipeline.py
	$(PYTHON) scripts/hospitality_testbed/run_snowflake_dq.py

hospitality-certify:
	PYTHONPATH=src $(PYTHON) scripts/hospitality_testbed/certify_with_ade.py --mode $${ADE_TESTBED_MODE:-live}

hospitality-failure-fixtures:
	$(PYTHON) scripts/hospitality_testbed/stage_failure_fixture.py --all

hospitality-failure-certify:
	$(PYTHON) scripts/hospitality_testbed/run_failure_certification.py --scenario $${ADE_TESTBED_FAILURE_SCENARIO:-invalid_timestamp} --mode $${ADE_TESTBED_MODE:-live}

hospitality-e2e-local:
	$(PYTHON) scripts/hospitality_testbed/run_e2e.py --mode local --preset $${ADE_TESTBED_SCALE:-tiny} --seed $${ADE_TESTBED_SEED:-42}

hospitality-e2e-live:
	$(PYTHON) scripts/hospitality_testbed/run_e2e.py --mode live --preset $${ADE_TESTBED_SCALE:-tiny} --seed $${ADE_TESTBED_SEED:-42}

hospitality-reset:
	$(PYTHON) scripts/hospitality_testbed/reset_testbed.py --confirm-database $${ADE_SNOWFLAKE_DATABASE:-HOSPITALITY_TESTBED}

hospitality-teardown:
	$(PYTHON) scripts/hospitality_testbed/teardown_snowflake.py --confirm-database $${ADE_SNOWFLAKE_DATABASE:-HOSPITALITY_TESTBED}

hospitality-test:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src $(PYTHON) -m pytest -q -p no:cacheprovider tests/hospitality_testbed
