import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "generate_parity_ledger_v2.py"


def _module():
    spec = importlib.util.spec_from_file_location("parity_v2", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_four_parity_dimensions_are_independent():
    source = {
        "entries": [{
            "reference_tool_name": "sql_classify",
            "reference_category": "sql",
            "reference_path": "reference/sql",
            "our_path": "src/sql.py",
            "tests": ["tests/test_sql.py"],
            "status": "DONE",
            "external_dependency": None,
        }]
    }
    result = _module().transform(source, {"sql_classify": ["SQL-1"]})
    item = result["entries"][0]
    assert item["implemented"] is True
    assert item["unit_verified"] is True
    assert item["behaviorally_verified"] is True
    assert item["live_verified"] is None


def test_external_requirement_does_not_become_live_verified():
    source = {
        "entries": [{
            "reference_symbol": "warehouse",
            "tests": ["tests/test_warehouse.py"],
            "status": "DONE",
            "external_dependency": "SNOWFLAKE_ACCOUNT",
        }]
    }
    item = _module().transform(source, {})["entries"][0]
    assert item["implemented"] is True
    assert item["live_verified"] is False


def test_parity_v2_exposes_explicit_status_and_evidence_fields():
    source = {
        "entries": [{
            "id": "CAP-1",
            "reference_tool_name": "discover",
            "our_path": "src/discovery.py",
            "tests": ["tests/test_discovery.py"],
            "status": "DONE",
            "external_dependency": None,
        }]
    }
    item = _module().transform(source, {"discover": ["DISCOVER-1"]})["entries"][0]
    assert item["capability_id"] == "CAP-1"
    assert item["status"] == "PASS_LOCAL"
    assert item["evidence"]["implementation"] == "src/discovery.py"
    assert item["evidence"]["behavioral_tests"] == ["DISCOVER-1"]


def test_parity_v2_external_capability_is_never_plain_pass_without_live_evidence():
    source = {
        "entries": [{
            "id": "CAP-LIVE",
            "reference_symbol": "github_review",
            "our_path": "src/review.py",
            "tests": ["tests/test_review.py"],
            "status": "DONE",
            "external_dependency": "ADE_REVIEW_GITHUB_TOKEN",
        }]
    }
    item = _module().transform(source, {"github_review": ["REVIEW-1"]})["entries"][0]
    assert item["status"] == "SKIP_EXTERNAL"
    assert item["live_verified"] is False
