from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_optimization_pack_keeps_mutations_commented_and_diagnostics_executable(tmp_path: Path):
    module = load_module(
        "rga_optimization_renderer_test",
        ROOT / "scripts" / "rga_testbed" / "render_optimization_experiments.py",
    )
    analysis = {
        "recommendations": [],
        "query_history": {
            "experiments": [
                {
                    "fingerprint": "fp1",
                    "type": "clustering_diagnostic",
                    "confidence": "medium",
                    "reason": "poor pruning",
                    "table": "DB.MART.T",
                    "columns": ["PERIOD_MONTH"],
                    "diagnostic_sql": (
                        "SELECT SYSTEM$CLUSTERING_INFORMATION("
                        "'DB.MART.T', '(PERIOD_MONTH)');"
                    ),
                    "mutation_sql": (
                        "ALTER TABLE DB.MART.T CLUSTER BY (PERIOD_MONTH);"
                    ),
                    "mutation_guard": "benchmark first",
                    "automatic_mutation_allowed": False,
                },
                {
                    "fingerprint": "fp2",
                    "type": "search_optimization_cost_estimate",
                    "confidence": "medium",
                    "reason": "selective lookup",
                    "table": "DB.MART.T",
                    "columns": ["CEDANT_ID"],
                    "estimate_sql": (
                        "SELECT SYSTEM$ESTIMATE_SEARCH_OPTIMIZATION_COSTS("
                        "'DB.MART.T', 'EQUALITY(CEDANT_ID)');"
                    ),
                    "mutation_sql": (
                        "ALTER TABLE DB.MART.T ADD SEARCH OPTIMIZATION "
                        "ON EQUALITY(CEDANT_ID);"
                    ),
                    "mutation_guard": "estimate cost first",
                    "automatic_mutation_allowed": False,
                },
            ]
        },
    }
    analysis_path = tmp_path / "analysis.json"
    output = tmp_path / "experiments.sql"
    analysis_path.write_text(json.dumps(analysis), encoding="utf-8")

    report = module.generate(analysis_path, output)
    text = output.read_text(encoding="utf-8")

    assert report["status"] == "PASS"
    assert report["experiment_count"] == 2
    assert report["executable_physical_mutations"] == 0
    assert "SELECT SYSTEM$CLUSTERING_INFORMATION" in text
    assert "SELECT SYSTEM$ESTIMATE_SEARCH_OPTIMIZATION_COSTS" in text
    assert "-- ALTER TABLE DB.MART.T CLUSTER BY" in text
    assert "-- ALTER TABLE DB.MART.T ADD SEARCH OPTIMIZATION" in text
    assert "\nALTER TABLE DB.MART.T" not in text


def test_empty_optimization_pack_is_truthful(tmp_path: Path):
    module = load_module(
        "rga_optimization_renderer_empty_test",
        ROOT / "scripts" / "rga_testbed" / "render_optimization_experiments.py",
    )
    analysis_path = tmp_path / "analysis.json"
    analysis_path.write_text(
        json.dumps({"recommendations": [], "query_history": {"experiments": []}}),
        encoding="utf-8",
    )
    output = tmp_path / "experiments.sql"
    report = module.generate(analysis_path, output)

    assert report["experiment_count"] == 0
    assert "No acceleration experiments were justified" in output.read_text(
        encoding="utf-8"
    )
