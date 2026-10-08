from __future__ import annotations

import importlib.util
import json
import sys
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
        "rga_excel_capture_test",
        ROOT / "scripts" / "rga_testbed" / "capture_excel_parity_evidence.py",
    )


def _parity_module():
    return load_module(
        "rga_excel_parity_generator_test",
        ROOT / "scripts" / "rga_testbed" / "generate_parity_suite.py",
    )


def test_excel_request_is_fail_closed_without_live_config(tmp_path: Path):
    module = _module()
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    config = {
        "runner_command": None,
        "cube_name": None,
        "connection_string_env": "EXCEL_XMLA_CONNECTION_STRING",
        "connection_configured": False,
    }

    errors = module.validate_request(
        manifest,
        config=config,
        security_context="ROLE_ANALYST",
        max_rows=1000,
        query_timeout=300,
        confirm=False,
        dry_run=False,
    )
    assert any("runner is required" in item for item in errors)
    assert any("cube/model name is required" in item for item in errors)
    assert any("connection is required" in item for item in errors)
    assert "Refusing live Excel evidence capture without --confirm" in errors


def test_excel_request_dry_run_needs_no_credentials(tmp_path: Path):
    module = _module()
    parity = _parity_module()
    parity.generate(tmp_path / "parity", "RGA_SYNTHETIC_TESTBED")
    manifest = tmp_path / "parity" / "parity_manifest.json"
    config = {
        "runner_command": None,
        "cube_name": None,
        "connection_string_env": "EXCEL_XMLA_CONNECTION_STRING",
        "connection_configured": False,
    }

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
        max_rows=1000,
        query_timeout=300,
    )
    assert plan["status"] == "DRY_RUN"
    assert plan["case_count"] >= 3
    assert all(item["mdx_exists"] for item in plan["cases"])
    assert plan["protocol"] == "XMLA/ADOMD MDX"
    assert "interactive Excel workbook UI" in plan["truth_boundary"]


def test_render_cube_name_escapes_mdx_identifier():
    module = _module()
    rendered = module.render_cube_name(
        "SELECT {} ON COLUMNS FROM [__CUBE_NAME__]",
        "Model]Prod",
    )
    assert "FROM [Model]]Prod]" in rendered
    assert "__CUBE_NAME__" not in rendered


def test_excel_xmla_column_normalization_handles_mdx_properties():
    module = _module()
    assert module.normalize_xmla_column(
        "[REINSURANCE_PERFORMANCE].[CEDANT_NAME].[CEDANT_NAME].[MEMBER_CAPTION]"
    ) == "CEDANT_NAME"
    assert module.normalize_xmla_column(
        "[Measures].[TOTAL_CEDED_PREMIUM]"
    ) == "TOTAL_CEDED_PREMIUM"


def test_excel_runner_rows_can_be_mapped_by_contract_order():
    module = _module()
    rows = module.normalize_rows(
        {
            "columns": ["caption", "measure"],
            "rows": [["Cedant A", 125.5]],
        },
        ["CEDANT_NAME", "TOTAL_CEDED_PREMIUM"],
        max_rows=10,
    )
    assert rows == [
        {"CEDANT_NAME": "Cedant A", "TOTAL_CEDED_PREMIUM": 125.5}
    ]


def test_excel_capture_writes_governed_evidence_without_connection_secret(
    tmp_path: Path,
):
    module = _module()
    parity = _parity_module()
    parity_dir = tmp_path / "parity"
    parity.generate(parity_dir, "RGA_SYNTHETIC_TESTBED")
    manifest = parity_dir / "parity_manifest.json"
    suite = json.loads(manifest.read_text(encoding="utf-8"))

    runner = tmp_path / "fake_xmla_runner.py"
    runner.write_text(
        """
import json
import re
import sys
request = json.load(sys.stdin)
query = request["query"]
dimension_count = len(re.findall(r"\\.MEMBERS", query))
measure_count = len(re.findall(r"\\[Measures\\]\\.\\[", query))
row = []
for index in range(dimension_count):
    row.append("2026-01-01" if "PERIOD_MONTH" in query and index == dimension_count - 1 else f"D{index + 1}")
for index in range(measure_count):
    row.append(1.25 + index)
json.dump({
    "status": "PASS",
    "columns": [f"C{index}" for index in range(len(row))],
    "rows": [row],
    "metadata": {
        "runner": "fake",
        "server_version": "test",
        "connection_echo": request["connection_string"],
    },
}, sys.stdout)
""".strip()
        + "\n",
        encoding="utf-8",
    )

    secret = "Provider=MSOLAP;Password=super-secret;"
    evidence_dir = tmp_path / "evidence"
    report = module.capture(
        manifest,
        evidence_dir,
        env={"EXCEL_XMLA_CONNECTION_STRING": secret},
        runner_command=f"{sys.executable} {runner}",
        cube_name="Model",
        connection_string_env="EXCEL_XMLA_CONNECTION_STRING",
        security_context="ROLE_ANALYST",
        max_rows=1000,
        query_timeout=300,
        overwrite=False,
    )

    assert report["status"] == "PASS"
    assert report["failed"] == 0
    assert report["passed"] == len(suite["cases"])
    for case in suite["cases"]:
        evidence = json.loads(
            (evidence_dir / f"{case['id']}.excel.json").read_text(
                encoding="utf-8"
            )
        )
        assert evidence["consumer"] == "excel"
        assert evidence["security_context"] == "ROLE_ANALYST"
        assert evidence["capture_status"] == "CAPTURED"
        assert evidence["capture_method"] == "xmla_adomd_mdx_runner"
        assert evidence["cube_name"] == "Model"
        assert evidence["runner_metadata"] == {
            "runner": "fake",
            "server_version": "test",
        }
        assert secret not in json.dumps(evidence)
        expected = case["dimensions"] + case["metrics"]
        assert list(evidence["rows"][0]) == expected


def test_safe_metadata_removes_sensitive_keys_recursively():
    module = _module()
    assert module.safe_metadata(
        {
            "server": "xmla",
            "access_token": "secret",
            "nested": {
                "connection_string": "secret",
                "database": "model",
            },
        }
    ) == {
        "server": "xmla",
        "nested": {"database": "model"},
    }
