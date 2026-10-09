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


def _module():
    return load_module(
        "semantic_platform_distribution_test",
        ROOT / "scripts" / "rga_testbed" / "export_semantic_platform_distribution.py",
    )


def test_distribution_adds_packaging_cli_and_bundled_contract(tmp_path: Path):
    output = tmp_path / "semantic-platform-distribution"
    report = _module().build_distribution(BANKING_CONTRACT, output)

    assert report["status"] == "PASS"
    assert report["installable_python_distribution"] is True
    assert report["distribution_name"] == "governed-semantic-platform-core"
    assert report["cli"] == "semantic-platform-core"
    assert (output / "pyproject.toml").exists()

    package = output / "scripts" / "semantic_platform_core"
    assert (package / "cli.py").exists()
    assert (package / "default_semantic_contract.yml").exists()
    assert not (package / "generate_data.py").exists()
    assert not (package / "generate_change_events.py").exists()
    assert not (package / "generate_dbt_project.py").exists()

    semantic_contract = (package / "semantic_contract.py").read_text(encoding="utf-8")
    assert 'Path(__file__).resolve().parent / "default_semantic_contract.yml"' in semantic_contract
    assert 'ROOT / "config" / "semantic_contract.yml"' not in semantic_contract

    manifest = json.loads((output / "core_manifest.json").read_text(encoding="utf-8"))
    assert manifest["installable_python_distribution"] is True
    assert manifest["distribution_name"] == "governed-semantic-platform-core"
    assert manifest["cli"] == "semantic-platform-core"
    assert manifest["reference_workload_included"] is False


def test_distribution_cli_runs_directly_from_export_tree(tmp_path: Path):
    output = tmp_path / "semantic-platform-distribution"
    _module().build_distribution(BANKING_CONTRACT, output)

    about = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.semantic_platform_core.cli",
            "about",
        ],
        cwd=output,
        text=True,
        capture_output=True,
        check=False,
    )
    assert about.returncode == 0, about.stdout + "\n" + about.stderr
    about_payload = json.loads(about.stdout)
    assert about_payload["product"] == "governed_semantic_platform_core"
    assert about_payload["reference_workload_included"] is False

    validate = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.semantic_platform_core.cli",
            "validate-contract",
        ],
        cwd=output,
        text=True,
        capture_output=True,
        check=False,
    )
    assert validate.returncode == 0, validate.stdout + "\n" + validate.stderr
    validate_payload = json.loads(validate.stdout)
    assert validate_payload["status"] == "PASS"
    assert validate_payload["name"] == "BANKING_ACCOUNT_PERFORMANCE"
    assert validate_payload["semantic_view"] == (
        "BANKING_ANALYTICS.SEMANTIC.BANKING_ACCOUNT_PERFORMANCE"
    )


def test_distribution_cli_builds_release_using_bundled_default_contract(tmp_path: Path):
    output = tmp_path / "semantic-platform-distribution"
    _module().build_distribution(BANKING_CONTRACT, output)

    release = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.semantic_platform_core.cli",
            "release",
            "--database",
            "BANKING_ANALYTICS",
            "--output",
            str(output / "release"),
            "--source-sha",
            "distribution-test",
        ],
        cwd=output,
        text=True,
        capture_output=True,
        check=False,
    )
    assert release.returncode == 0, release.stdout + "\n" + release.stderr
    payload = json.loads(release.stdout)
    assert payload["status"] == "PASS"

    manifest = json.loads(
        (output / "release" / "release_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["source_sha"] == "distribution-test"
    assert manifest["semantic_view"] == (
        "BANKING_ANALYTICS.SEMANTIC.BANKING_ACCOUNT_PERFORMANCE"
    )
    assert not (output / "release" / "multi_fact").exists()
