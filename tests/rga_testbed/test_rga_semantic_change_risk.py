from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_metric_formula_change_is_high_risk():
    module = load_module(
        "rga_change_risk_metric_test",
        ROOT / "scripts" / "rga_testbed" / "classify_semantic_change.py",
    )
    diff = {
        "status": "CHANGED",
        "changed_sections": ["metrics"],
        "impacted_artifacts": ["semantic_view", "ai"],
        "details": {
            "grain": {"added": [], "removed": [], "modified": []},
            "metrics": {"added": [], "removed": [], "modified": ["CEDED_LOSS_RATIO"]},
            "facts": {"added": [], "removed": [], "modified": []},
            "dimensions": {"added": [], "removed": [], "modified": []},
            "time_dimensions": {"added": [], "removed": [], "modified": []},
            "verified_queries": {"added": [], "removed": [], "modified": []},
            "consumers": {"added": [], "removed": [], "modified": []},
            "acceleration": {"added": [], "removed": [], "modified": []},
            "performance": {"added": [], "removed": [], "modified": []},
        },
    }
    result = module.classify(diff)
    assert result["risk"] == "high"
    assert result["approval_required"] is True
    assert "CEDED_LOSS_RATIO" in " ".join(result["reasons"])


def test_metric_removal_is_breaking():
    module = load_module(
        "rga_change_risk_remove_test",
        ROOT / "scripts" / "rga_testbed" / "classify_semantic_change.py",
    )
    diff = {
        "status": "CHANGED",
        "changed_sections": ["metrics"],
        "impacted_artifacts": ["semantic_view"],
        "details": {
            "grain": {"added": [], "removed": [], "modified": []},
            "metrics": {"added": [], "removed": ["TOTAL_CEDED_PREMIUM"], "modified": []},
            "facts": {"added": [], "removed": [], "modified": []},
            "dimensions": {"added": [], "removed": [], "modified": []},
            "time_dimensions": {"added": [], "removed": [], "modified": []},
            "verified_queries": {"added": [], "removed": [], "modified": []},
            "consumers": {"added": [], "removed": [], "modified": []},
            "acceleration": {"added": [], "removed": [], "modified": []},
            "performance": {"added": [], "removed": [], "modified": []},
        },
    }
    result = module.classify(diff)
    assert result["risk"] == "breaking"
    assert result["approval_required"] is True


def test_unchanged_release_needs_no_approval():
    module = load_module(
        "rga_change_risk_unchanged_test",
        ROOT / "scripts" / "rga_testbed" / "classify_semantic_change.py",
    )
    result = module.classify({"status": "UNCHANGED", "details": {}, "changed_sections": []})
    assert result["risk"] == "none"
    assert result["approval_required"] is False
