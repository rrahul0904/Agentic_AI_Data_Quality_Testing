from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BANKING_CONTRACT = ROOT / "config" / "examples" / "banking_semantic_contract.yml"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _exporter():
    return load_module(
        "semantic_platform_core_export_test",
        ROOT / "scripts" / "rga_testbed" / "export_semantic_platform_core.py",
    )


def test_core_export_excludes_rga_reference_workload(tmp_path: Path):
    module = _exporter()
    output = tmp_path / "semantic-platform-core"
    result = module.export_core(BANKING_CONTRACT, output)

    assert result["status"] == "PASS"
    assert result["reference_workload_included"] is False
    manifest = json.loads((output / "core_manifest.json").read_text(encoding="utf-8"))
    assert manifest["product_scope"] == "governed_semantic_platform"
    assert manifest["reference_workload_included"] is False
    assert manifest["canonical_contract"] == "config/semantic_contract.yml"
    assert manifest["core_file_count"] == len(module.CORE_FILES)

    package = output / "scripts" / "semantic_platform_core"
    for name in module.REFERENCE_WORKLOAD_EXCLUDED:
        assert not (package / name).exists(), name
    assert not (package / "generate_multi_fact_certification.py").exists()
    assert (package / "build_semantic_release.py").exists()
    assert (package / "capture_power_bi_parity_evidence.py").exists()
    assert (package / "capture_excel_parity_evidence.py").exists()
    assert (package / "smoke_snowflake_mcp.py").exists()

    python_text = "\n".join(
        path.read_text(encoding="utf-8") for path in package.glob("*.py")
    )
    assert "scripts.rga_testbed" not in python_text
    assert "rga_semantic_contract.yml" not in python_text
    assert "RGA_SYNTHETIC_TESTBED" not in python_text
    assert "RGA_SEMANTIC_BENCHMARK" not in python_text


def test_exported_core_builds_non_rga_release_without_reference_extension(tmp_path: Path):
    module = _exporter()
    output = tmp_path / "semantic-platform-core"
    module.export_core(BANKING_CONTRACT, output)

    command = [
        sys.executable,
        str(output / "scripts" / "semantic_platform_core" / "build_semantic_release.py"),
        "--contract",
        str(output / "config" / "semantic_contract.yml"),
        "--database",
        "BANKING_ANALYTICS",
        "--output",
        str(output / "release"),
        "--source-sha",
        "standalone-test",
    ]
    completed = subprocess.run(
        command,
        cwd=output,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + "\n" + completed.stderr
    summary = json.loads(completed.stdout)
    assert summary["status"] == "PASS"

    release = json.loads(
        (output / "release" / "release_manifest.json").read_text(encoding="utf-8")
    )
    assert release["source_sha"] == "standalone-test"
    assert release["database"] == "BANKING_ANALYTICS"
    assert release["semantic_view"] == (
        "BANKING_ANALYTICS.SEMANTIC.BANKING_ACCOUNT_PERFORMANCE"
    )
    assert "multi_fact" not in release["impacted_artifacts"]
    assert not (output / "release" / "multi_fact").exists()
    assert (
        output
        / "release"
        / "interchange"
        / "banking_account_performance.ossie.yml"
    ).exists()
    assert (output / "release" / "ai" / "mcp_spec.yml").exists()
    assert (output / "release" / "microsoft" / "PARITY_CHECKLIST.md").exists()


def test_exported_core_uses_neutral_defaults(tmp_path: Path):
    module = _exporter()
    output = tmp_path / "semantic-platform-core"
    module.export_core(BANKING_CONTRACT, output)

    semantic_contract = (
        output / "scripts" / "semantic_platform_core" / "semantic_contract.py"
    ).read_text(encoding="utf-8")
    release_builder = (
        output / "scripts" / "semantic_platform_core" / "build_semantic_release.py"
    ).read_text(encoding="utf-8")
    query_history = (
        output / "scripts" / "semantic_platform_core" / "collect_query_history.py"
    ).read_text(encoding="utf-8")

    assert 'ROOT / "config" / "semantic_contract.yml"' in semantic_contract
    assert 'ROOT / "release"' in release_builder
    assert "SEMANTIC_PLATFORM" in query_history
    assert "SEMANTIC_PLATFORM_BENCHMARK" in query_history
