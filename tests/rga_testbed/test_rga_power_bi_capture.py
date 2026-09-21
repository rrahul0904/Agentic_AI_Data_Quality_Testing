from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pyarrow as pa
import pytest

ROOT = Path(__file__).resolve().parents[2]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _module():
    return load_module(
        "rga_power_bi_capture_test",
        ROOT / "scripts" / "rga_testbed" / "capture_power_bi_parity_evidence.py",
    )


def _parity_module():
    return load_module(
        "rga_power_bi_parity_generator_test",
        ROOT / "scripts" / "rga_testbed" / "generate_parity_suite.py",
    )


def _arrow_bytes(table: pa.Table) -> bytes:
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, table.schema) as writer:
        writer.write_table(table)
    return sink.getvalue().to_pybytes()


def test_power_bi_request_is_fail_closed_without_live_config(tmp_path: Path):
    module = _module()
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    config = module.resolve_config({}, workspace_id=None, dataset_id=None)

    errors = module.validate_request(
        manifest,
        config=config,
        security_context="ROLE_ANALYST",
        max_rows=1000,
        query_timeout=300,
        confirm=False,
        dry_run=False,
    )
    assert any("workspace id is required" in item for item in errors)
    assert any("dataset id is required" in item for item in errors)
    assert any("authentication is required" in item for item in errors)
    assert "Refusing live Power BI evidence capture without --confirm" in errors


def test_power_bi_request_dry_run_needs_no_credentials(tmp_path: Path):
    module = _module()
    parity = _parity_module()
    parity.generate(tmp_path / "parity", "RGA_SYNTHETIC_TESTBED")
    manifest = tmp_path / "parity" / "parity_manifest.json"
    config = module.resolve_config({}, workspace_id=None, dataset_id=None)

    errors = module.validate_request(
        manifest,
        config=config,
        security_context="ROLE_ANALYST",
        max_rows=1000,
        query_timeout=300,
        confirm=False,
        dry_run=True,
    )
    assert errors == []
    plan = module.plan(
        manifest,
        evidence_dir=tmp_path / "evidence",
        config=config,
        security_context="ROLE_ANALYST",
        effective_username=None,
        roles=[],
        max_rows=1000,
        query_timeout=300,
    )
    assert plan["status"] == "DRY_RUN"
    assert plan["case_count"] >= 3
    assert all(item["dax_exists"] for item in plan["cases"])
    assert "Excel remains a separate" in plan["truth_boundary"]


def test_power_bi_url_and_request_body_are_bounded():
    module = _module()
    assert module.power_bi_url("workspace", "dataset") == (
        "https://api.powerbi.com/v1.0/myorg/groups/workspace/"
        "datasets/dataset/executeDaxQueries"
    )
    body = module.build_request_body(
        "EVALUATE ROW(\"X\", 1)",
        max_rows=500,
        query_timeout=120,
        effective_username="user@example.com",
        roles=["Analyst"],
    )
    assert body["resultSetRowCountLimit"] == 500
    assert body["queryTimeout"] == 120
    assert body["effectiveUsername"] == "user@example.com"
    assert body["roles"] == ["Analyst"]
    assert body["schemaOnly"] is False


def test_power_bi_arrow_decoder_reads_data_rowset():
    module = _module()
    table = pa.table(
        {
            "REINSURANCE_PERFORMANCE[CEDANT_NAME]": ["A", "B"],
            "[TOTAL_CEDED_PREMIUM]": [100.0, 200.0],
        }
    )
    rows = module.decode_arrow_rows(_arrow_bytes(table))
    normalized = module.normalize_rows(
        rows,
        ["CEDANT_NAME", "TOTAL_CEDED_PREMIUM"],
    )
    assert normalized == [
        {"CEDANT_NAME": "A", "TOTAL_CEDED_PREMIUM": 100.0},
        {"CEDANT_NAME": "B", "TOTAL_CEDED_PREMIUM": 200.0},
    ]


def test_power_bi_arrow_decoder_rejects_error_rowset_even_on_http_200():
    module = _module()
    schema = pa.schema(
        [("ErrorCode", pa.string()), ("ErrorMessage", pa.string())],
        metadata={
            b"IsError": b"true",
            b"FaultCode": b"0xdead",
            b"FaultString": b"DAX failed",
        },
    )
    table = pa.Table.from_arrays(
        [
            pa.array(["ERR"]),
            pa.array(["bad query"]),
        ],
        schema=schema,
    )
    with pytest.raises(RuntimeError, match="DAX failed"):
        module.decode_arrow_rows(_arrow_bytes(table))


def test_power_bi_column_normalization_strips_table_qualification():
    module = _module()
    assert (
        module.normalize_power_bi_column(
            "REINSURANCE_PERFORMANCE[CEDANT_NAME]"
        )
        == "CEDANT_NAME"
    )
    assert module.normalize_power_bi_column("[CEDED_LOSS_RATIO]") == (
        "CEDED_LOSS_RATIO"
    )


def test_power_bi_capture_writes_governed_parity_evidence(
    tmp_path: Path,
    monkeypatch,
):
    module = _module()
    parity = _parity_module()
    parity_dir = tmp_path / "parity"
    parity.generate(parity_dir, "RGA_SYNTHETIC_TESTBED")
    manifest = parity_dir / "parity_manifest.json"
    suite = json.loads(manifest.read_text(encoding="utf-8"))

    monkeypatch.setattr(
        module,
        "acquire_access_token",
        lambda env: ("secret-token", "access_token"),
    )

    def fake_execute_dax(*, url, token, body):
        assert "executeDaxQueries" in url
        assert token == "secret-token"
        dax = body["query"]
        case = next(
            item
            for item in suite["cases"]
            if (parity_dir / item["power_bi"]["dax_file"]).read_text(
                encoding="utf-8"
            )
            == dax
        )
        row = {}
        for dimension in case["dimensions"]:
            row[
                f"REINSURANCE_PERFORMANCE[{dimension}]"
            ] = "A" if dimension != "PERIOD_MONTH" else "2026-01-01"
        for metric in case["metrics"]:
            row[f"[{metric}]"] = 1.25
        return _arrow_bytes(pa.Table.from_pylist([row]))

    monkeypatch.setattr(module, "execute_dax", fake_execute_dax)

    evidence_dir = tmp_path / "evidence"
    report = module.capture(
        manifest,
        evidence_dir,
        env={"POWER_BI_ACCESS_TOKEN": "secret-token"},
        workspace_id="workspace",
        dataset_id="dataset",
        security_context="ROLE_ANALYST",
        effective_username=None,
        roles=[],
        max_rows=1000,
        query_timeout=300,
        overwrite=False,
    )

    assert report["status"] == "PASS"
    assert report["failed"] == 0
    assert report["passed"] == len(suite["cases"])
    for case in suite["cases"]:
        evidence = json.loads(
            (
                evidence_dir / f"{case['id']}.power_bi.json"
            ).read_text(encoding="utf-8")
        )
        assert evidence["consumer"] == "power_bi"
        assert evidence["security_context"] == "ROLE_ANALYST"
        assert evidence["capture_status"] == "CAPTURED"
        assert evidence["capture_method"] == (
            "power_bi_execute_dax_queries_arrow"
        )
        assert "secret-token" not in json.dumps(evidence)
        expected = case["dimensions"] + case["metrics"]
        assert sorted(evidence["rows"][0]) == sorted(expected)
