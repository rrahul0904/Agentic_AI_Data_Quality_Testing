from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_manifest_is_stable_for_same_contract():
    module = load_module(
        "rga_manifest_stable_test",
        ROOT / "scripts" / "rga_testbed" / "compile_semantic_manifest.py",
    )
    left = module.build_manifest()
    right = module.build_manifest()
    assert left["manifest_sha256"] == right["manifest_sha256"]
    assert left["components"]["metrics"]["CEDED_LOSS_RATIO"]["hash"] == right["components"]["metrics"]["CEDED_LOSS_RATIO"]["hash"]


def test_manifest_diff_identifies_metric_change_and_impacts():
    module = load_module(
        "rga_manifest_diff_test",
        ROOT / "scripts" / "rga_testbed" / "compile_semantic_manifest.py",
    )
    before = module.build_manifest()
    after = copy.deepcopy(before)
    after["components"]["metrics"]["CEDED_LOSS_RATIO"]["hash"] = "changed"
    after["manifest_sha256"] = "changed-manifest"
    diff = module.diff_manifests(before, after)
    assert diff["status"] == "CHANGED"
    assert diff["changed_sections"] == ["metrics"]
    assert "CEDED_LOSS_RATIO" in diff["details"]["metrics"]["modified"]
    assert {"semantic_view", "ai", "microsoft", "benchmark", "parity", "ossie"} <= set(diff["impacted_artifacts"])


def test_manifest_diff_can_be_unchanged():
    module = load_module(
        "rga_manifest_unchanged_test",
        ROOT / "scripts" / "rga_testbed" / "compile_semantic_manifest.py",
    )
    manifest = module.build_manifest()
    diff = module.diff_manifests(manifest, copy.deepcopy(manifest))
    assert diff["status"] == "UNCHANGED"
    assert diff["changed_sections"] == []
    assert diff["impacted_artifacts"] == []
