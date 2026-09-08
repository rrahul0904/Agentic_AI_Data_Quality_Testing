from pathlib import Path

from agentic_data_platform.conformance import ConformanceCase, ConformanceRunner


def test_conformance_compares_structured_properties_not_wording(tmp_path: Path):
    case = ConformanceCase(
        case_id="X-1",
        capability="demo",
        tool="demo",
        args={},
        expected_properties=(
            {"path": "classification.type", "equals": "read"},
            {"path": "findings", "length_at_least": 1},
        ),
    )
    runner = ConformanceRunner(
        tmp_path,
        invoke=lambda tool, args: {
            "classification": {"type": "read"},
            "findings": [{"rule": "select_star", "message": "wording may differ"}],
        },
    )
    assert runner.run_case(case)["status"] == "MATCH"


def test_conformance_reports_structured_divergence(tmp_path: Path):
    case = ConformanceCase(
        case_id="X-2",
        capability="demo",
        tool="demo",
        args={},
        expected_properties=({"path": "severity", "one_of": ["warning", "error"]},),
    )
    runner = ConformanceRunner(tmp_path, invoke=lambda tool, args: {"severity": "info"})
    result = runner.run_case(case)
    assert result["status"] == "DIVERGENCE"
    assert result["differences"][0]["property"]["path"] == "severity"
