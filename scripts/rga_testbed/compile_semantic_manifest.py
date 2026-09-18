#!/usr/bin/env python3
"""Compile the canonical semantic contract into a stable manifest and optionally diff it."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

try:
    from scripts.rga_testbed.semantic_contract import DEFAULT_CONTRACT, load_semantic_contract, semantic_view_fqn
except ModuleNotFoundError:
    from semantic_contract import DEFAULT_CONTRACT, load_semantic_contract, semantic_view_fqn

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "rga-snowflake-data-platform" / "manifest" / "semantic_manifest.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--database", default="RGA_SYNTHETIC_TESTBED")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--diff-output", type=Path)
    return parser.parse_args()


def _sha(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _component_map(items: list[dict[str, Any]], key: str = "name") -> dict[str, dict[str, Any]]:
    return {str(item[key]): {"hash": _sha(item), "value": item} for item in items}


def build_manifest(contract_path: Path = DEFAULT_CONTRACT, database: str = "RGA_SYNTHETIC_TESTBED") -> dict[str, Any]:
    contract = load_semantic_contract(contract_path, database)
    components = {
        "grain": {"__grain__": {"hash": _sha(contract["grain"]), "value": contract["grain"]}},
        "dimensions": _component_map(contract["dimensions"]),
        "time_dimensions": _component_map(contract["time_dimensions"]),
        "facts": _component_map(contract["facts"]),
        "metrics": _component_map(contract["metrics"]),
        "verified_queries": _component_map(contract["verified_queries"], key="id"),
        "consumers": {
            name: {"hash": _sha(value), "value": value}
            for name, value in sorted(contract["consumers"].items())
        },
        "acceleration": {
            name: {"hash": _sha(value), "value": value}
            for name, value in sorted(contract.get("acceleration", {}).items())
        },
        "performance": {"__performance__": {"hash": _sha(contract["performance"]), "value": contract["performance"]}},
    }
    manifest = {
        "manifest_version": 1,
        "contract_version": contract.get("version"),
        "name": contract["name"],
        "semantic_view": semantic_view_fqn(contract),
        "source": str(contract_path),
        "source_sha256": _file_sha(contract_path),
        "components": components,
    }
    manifest["manifest_sha256"] = _sha(manifest)
    return manifest


def _diff_section(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    before_keys = set(before)
    after_keys = set(after)
    added = sorted(after_keys - before_keys)
    removed = sorted(before_keys - after_keys)
    modified = sorted(
        key for key in before_keys & after_keys
        if before[key]["hash"] != after[key]["hash"]
    )
    return {"added": added, "removed": removed, "modified": modified}


def impacted_artifacts(changed_sections: list[str]) -> list[str]:
    impacts: set[str] = set()
    semantic_sections = {"grain", "dimensions", "time_dimensions", "facts", "metrics", "verified_queries"}
    if semantic_sections & set(changed_sections):
        impacts.update({"semantic_view", "ai", "microsoft", "benchmark", "parity", "ossie"})
    if "consumers" in changed_sections:
        impacts.update({"ai", "microsoft", "parity"})
    if "acceleration" in changed_sections:
        impacts.add("acceleration")
    if "performance" in changed_sections:
        impacts.update({"benchmark", "acceleration"})
    return sorted(impacts)


def diff_manifests(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    sections = sorted(set(before["components"]) | set(after["components"]))
    details: dict[str, Any] = {}
    changed_sections: list[str] = []
    for section in sections:
        result = _diff_section(
            before["components"].get(section, {}),
            after["components"].get(section, {}),
        )
        details[section] = result
        if result["added"] or result["removed"] or result["modified"]:
            changed_sections.append(section)
    return {
        "status": "CHANGED" if changed_sections else "UNCHANGED",
        "before_sha256": before.get("manifest_sha256"),
        "after_sha256": after.get("manifest_sha256"),
        "changed_sections": changed_sections,
        "impacted_artifacts": impacted_artifacts(changed_sections),
        "details": details,
    }


def write_manifest(manifest: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    manifest = build_manifest(args.contract, args.database)
    write_manifest(manifest, args.output)
    result: dict[str, Any] = {"status": "PASS", "manifest": str(args.output), "manifest_sha256": manifest["manifest_sha256"]}
    if args.baseline:
        baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
        diff = diff_manifests(baseline, manifest)
        diff_path = args.diff_output or args.output.with_name("semantic_diff.json")
        write_manifest(diff, diff_path)
        result["diff"] = diff
        result["diff_file"] = str(diff_path)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
