from __future__ import annotations

from dataclasses import fields

from agentic_data_platform.agents import InvestigationScenario, get_scenario, scenario_catalog


FORBIDDEN = {
    "expected_root_cause",
    "expected_first_divergence",
    "remediation_action",
    "after_fix",
}


def test_runtime_scenario_structurally_excludes_benchmark_ground_truth():
    runtime_names = {item.name for item in fields(InvestigationScenario)}
    assert FORBIDDEN.isdisjoint(runtime_names)

    fixture = get_scenario("watermark_defect")
    runtime = fixture.runtime_input()
    assert not any(hasattr(runtime, name) for name in FORBIDDEN)


def test_agent_context_does_not_leak_expected_answers_or_fix():
    context = get_scenario("watermark_defect").agent_context()
    assert FORBIDDEN.isdisjoint(context)
    rendered = repr(context)
    assert "WATERMARK_ADVANCED_BEYOND_EXTRACT" not in rendered
    assert "RESET_WATERMARK_AND_BOUNDED_BACKFILL" not in rendered


def test_public_scenario_catalog_does_not_publish_benchmark_answers():
    catalog = scenario_catalog()
    assert catalog
    assert all(FORBIDDEN.isdisjoint(item) for item in catalog)
