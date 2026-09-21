#!/usr/bin/env python3
"""Build one deterministic governed-semantic release bundle from the canonical contract."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

try:
    from scripts.rga_testbed import classify_semantic_change as change_mod
    from scripts.rga_testbed import compile_semantic_manifest as manifest_mod
    from scripts.rga_testbed import export_ossie as ossie_mod
    from scripts.rga_testbed import generate_acceleration_plan as acceleration_mod
    from scripts.rga_testbed import generate_ai_integration as ai_mod
    from scripts.rga_testbed import generate_benchmark_pack as benchmark_mod
    from scripts.rga_testbed import generate_microsoft_consumer_pack as microsoft_mod
    from scripts.rga_testbed import generate_multi_fact_certification as multi_fact_mod
    from scripts.rga_testbed import generate_parity_suite as parity_mod
    from scripts.rga_testbed import generate_semantic_view as semantic_mod
    from scripts.rga_testbed import report_interchange_compatibility as compatibility_mod
    from scripts.rga_testbed.semantic_contract import DEFAULT_CONTRACT, contract_slug, load_semantic_contract
except ModuleNotFoundError:
    import classify_semantic_change as change_mod
    import compile_semantic_manifest as manifest_mod
    import export_ossie as ossie_mod
    import generate_acceleration_plan as acceleration_mod
    import generate_ai_integration as ai_mod
    import generate_benchmark_pack as benchmark_mod
    import generate_microsoft_consumer_pack as microsoft_mod
    import generate_multi_fact_certification as multi_fact_mod
    import generate_parity_suite as parity_mod
    import generate_semantic_view as semantic_mod
    import report_interchange_compatibility as compatibility_mod
    from semantic_contract import DEFAULT_CONTRACT, contract_slug, load_semantic_contract

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "rga-snowflake-data-platform" / "release"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--database", default="RGA_SYNTHETIC_TESTBED")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--source-sha", default=os.environ.get("GITHUB_SHA"))
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _generated_files(root: Path) -> list[dict[str, object]]:
    rows = []
    for path in sorted(p for p in root.rglob("*") if p.is_file() and p.name != "release_manifest.json"):
        rows.append(
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": sha256(path),
                "bytes": path.stat().st_size,
            }
        )
    return rows


def build_release(
    output: Path,
    database: str,
    contract_path: Path = DEFAULT_CONTRACT,
    baseline_path: Path | None = None,
    source_sha: str | None = None,
) -> dict:
    output.mkdir(parents=True, exist_ok=True)

    contract = load_semantic_contract(contract_path, database)
    current_manifest = manifest_mod.build_manifest(contract_path, database)
    manifest_path = output / "manifest" / "semantic_manifest.json"
    manifest_mod.write_manifest(current_manifest, manifest_path)

    diff = None
    change_risk = {
        "risk": "initial_build",
        "approval_required": True,
        "reasons": ["No baseline manifest supplied; initial governed release requires review."],
        "changed_sections": [],
        "impacted_artifacts": [],
    }
    if baseline_path:
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        diff = manifest_mod.diff_manifests(baseline, current_manifest)
        manifest_mod.write_manifest(diff, output / "manifest" / "semantic_diff.json")
        change_risk = change_mod.classify(diff)
        manifest_mod.write_manifest(change_risk, output / "manifest" / "semantic_change_risk.json")

    semantic_mod.generate(output / "semantic", database, contract_path)
    ai_mod.generate(output / "ai", database, contract_path)
    microsoft_mod.generate(output / "microsoft", database, contract_path)
    benchmark_mod.generate(output / "benchmarks", database, contract_path)
    parity_mod.generate(output / "parity", database, contract_path)
    multi_fact_enabled = bool(
        contract.get("reference_extensions", {}).get("multi_fact", False)
    )
    if multi_fact_enabled:
        multi_fact_mod.generate(output / "multi_fact")
    acceleration_mod.generate(output / "acceleration", database, contract_path)

    ossie_path = output / "interchange" / f"{contract_slug(contract)}.ossie.yml"
    ossie_mod.generate(ossie_path, database, contract_path)
    compatibility = compatibility_mod.build_report(database, contract_path)
    compatibility_path = output / "interchange" / "ossie_compatibility.json"
    compatibility_path.write_text(json.dumps(compatibility, indent=2) + "\n", encoding="utf-8")

    if diff is not None:
        impacted = diff["impacted_artifacts"]
        if not multi_fact_enabled:
            impacted = [item for item in impacted if item != "multi_fact"]
    else:
        impacted = [
            "acceleration",
            "ai",
            "benchmark",
            "microsoft",
            "ossie",
            "parity",
            "semantic_view",
        ]
        if multi_fact_enabled:
            impacted.append("multi_fact")
    files = _generated_files(output)
    release = {
        "release_version": 1,
        "source_sha": source_sha,
        "database": database,
        "semantic_view": current_manifest["semantic_view"],
        "semantic_manifest_sha256": current_manifest["manifest_sha256"],
        "change_status": diff["status"] if diff else "FULL_BUILD",
        "change_risk": change_risk,
        "impacted_artifacts": impacted,
        "generated_file_count": len(files),
        "files": files,
        "external_certification_required": [
            "snowflake_object_creation",
            "dbt_build",
            "semantic_view_server_verify_and_deploy",
            "cortex_agent_and_mcp_runtime",
            "live_query_benchmark",
            "power_bi_excel_governed_parity",
        ],
    }
    release_path = output / "release_manifest.json"
    release_path.write_text(json.dumps(release, indent=2) + "\n", encoding="utf-8")
    return release


def main() -> int:
    args = parse_args()
    release = build_release(args.output, args.database, args.contract, args.baseline, args.source_sha)
    print(
        json.dumps(
            {
                "status": "PASS",
                "output": str(args.output),
                "semantic_manifest_sha256": release["semantic_manifest_sha256"],
                "generated_file_count": release["generated_file_count"],
                "change_status": release["change_status"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
