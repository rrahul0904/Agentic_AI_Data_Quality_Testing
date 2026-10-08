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


def _module():
    return load_module(
        "rga_consumer_ingest_test",
        ROOT / "scripts" / "rga_testbed" / "ingest_consumer_evidence.py",
    )


def _manifest(path: Path):
    payload = {
        "cases": [
            {
                "id": "q1",
                "business_question": "What is metric A?",
                "dimensions": ["DIMENSION_A"],
                "metrics": ["METRIC_A"],
            }
        ]
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_ingest_power_bi_csv_creates_captured_evidence(tmp_path: Path):
    module = _module()
    manifest = tmp_path / "parity_manifest.json"
    _manifest(manifest)
    source = tmp_path / "powerbi.csv"
    source.write_text("DIMENSION_A,METRIC_A\nA,10.5\n", encoding="utf-8")

    report = module.ingest(
        manifest,
        tmp_path / "evidence",
        case_id="q1",
        consumer="power_bi",
        input_path=source,
        security_context="ROLE_ANALYST",
    )
    assert report["status"] == "PASS"
    assert report["row_count"] == 1

    evidence = json.loads(Path(report["output"]).read_text(encoding="utf-8"))
    assert evidence["capture_status"] == "CAPTURED"
    assert evidence["consumer"] == "power_bi"
    assert evidence["security_context"] == "ROLE_ANALYST"
    assert evidence["rows"] == [{"DIMENSION_A": "A", "METRIC_A": "10.5"}]
    assert evidence["source_sha256"]


def test_ingest_excel_json_rows_is_supported(tmp_path: Path):
    module = _module()
    manifest = tmp_path / "parity_manifest.json"
    _manifest(manifest)
    source = tmp_path / "excel.json"
    source.write_text(
        json.dumps({"rows": [{"dimension_a": "A", "metric_a": 10.5}]}),
        encoding="utf-8",
    )

    report = module.ingest(
        manifest,
        tmp_path / "evidence",
        case_id="q1",
        consumer="excel",
        input_path=source,
        security_context="ROLE_ANALYST",
    )
    evidence = json.loads(Path(report["output"]).read_text(encoding="utf-8"))
    assert evidence["rows"] == [{"DIMENSION_A": "A", "METRIC_A": 10.5}]


def test_ingest_rejects_wrong_columns(tmp_path: Path):
    module = _module()
    manifest = tmp_path / "parity_manifest.json"
    _manifest(manifest)
    source = tmp_path / "bad.csv"
    source.write_text("DIMENSION_A,WRONG\nA,10\n", encoding="utf-8")

    try:
        module.ingest(
            manifest,
            tmp_path / "evidence",
            case_id="q1",
            consumer="power_bi",
            input_path=source,
            security_context="ROLE_ANALYST",
        )
    except ValueError as exc:
        assert "column mismatch" in str(exc)
    else:
        raise AssertionError("wrong consumer columns must be rejected")


def test_ingest_restricts_external_files_to_power_bi_and_excel(tmp_path: Path):
    module = _module()
    manifest = tmp_path / "parity_manifest.json"
    _manifest(manifest)
    source = tmp_path / "rows.csv"
    source.write_text("DIMENSION_A,METRIC_A\nA,10\n", encoding="utf-8")

    try:
        module.ingest(
            manifest,
            tmp_path / "evidence",
            case_id="q1",
            consumer="snowflake_semantic_view",
            input_path=source,
            security_context="ROLE_ANALYST",
        )
    except ValueError as exc:
        assert "restricted to Power BI and Excel" in str(exc)
    else:
        raise AssertionError("Snowflake evidence must not be spoofable by external file import")


def test_ingest_protects_existing_captured_evidence(tmp_path: Path):
    module = _module()
    manifest = tmp_path / "parity_manifest.json"
    _manifest(manifest)
    source = tmp_path / "rows.csv"
    source.write_text("DIMENSION_A,METRIC_A\nA,10\n", encoding="utf-8")
    evidence_dir = tmp_path / "evidence"

    module.ingest(
        manifest,
        evidence_dir,
        case_id="q1",
        consumer="power_bi",
        input_path=source,
        security_context="ROLE_ANALYST",
    )
    try:
        module.ingest(
            manifest,
            evidence_dir,
            case_id="q1",
            consumer="power_bi",
            input_path=source,
            security_context="ROLE_ANALYST",
        )
    except ValueError as exc:
        assert "already exists" in str(exc)
    else:
        raise AssertionError("captured evidence should be protected without --overwrite")
