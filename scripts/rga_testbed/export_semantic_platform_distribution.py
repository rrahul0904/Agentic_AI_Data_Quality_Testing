#!/usr/bin/env python3
"""Build an installable standalone governed-semantic platform distribution."""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

try:
    from scripts.rga_testbed.export_semantic_platform_core import export_core
except ModuleNotFoundError:
    from export_semantic_platform_core import export_core

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTRACT = ROOT / "config" / "examples" / "banking_semantic_contract.yml"
DEFAULT_OUTPUT = ROOT / "artifacts" / "semantic_platform_distribution"

PYPROJECT = '''[build-system]
requires = ["setuptools>=69"]
build-backend = "setuptools.build_meta"

[project]
name = "governed-semantic-platform-core"
version = "0.1.0"
description = "Reusable governed Snowflake semantic platform compiler and certification tooling."
readme = "README.md"
requires-python = ">=3.11"
dependencies = ["PyYAML>=6"]

[project.optional-dependencies]
snowflake = ["snowflake-connector-python>=3"]
dev = ["pytest>=8"]

[project.scripts]
semantic-platform-core = "scripts.semantic_platform_core.cli:main"

[tool.setuptools.packages.find]
where = ["."]
include = ["scripts*"]

[tool.setuptools.package-data]
"scripts.semantic_platform_core" = ["default_semantic_contract.yml", "*.ps1"]
'''

CLI = '''#!/usr/bin/env python3
"""Standalone governed semantic platform operator CLI."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.semantic_platform_core.build_semantic_release import build_release
from scripts.semantic_platform_core.semantic_contract import (
    DEFAULT_CONTRACT,
    load_semantic_contract,
    semantic_view_fqn,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="semantic-platform-core",
        description="Governed Snowflake semantic platform core.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("about", help="Describe the standalone product boundary.")

    validate = sub.add_parser("validate-contract", help="Validate a canonical semantic contract.")
    validate.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    validate.add_argument("--database")

    release = sub.add_parser("release", help="Compile a governed semantic release bundle.")
    release.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    release.add_argument("--database", required=True)
    release.add_argument("--output", type=Path, default=Path("release"))
    release.add_argument("--baseline", type=Path)
    release.add_argument("--source-sha")

    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.command == "about":
        print(json.dumps({
            "product": "governed_semantic_platform_core",
            "basis": "one canonical semantic contract -> Snowflake Semantic View -> governed BI/Excel/AI consumers -> parity certification -> evidence-backed physical optimization",
            "reference_workload_included": False,
            "default_contract": str(DEFAULT_CONTRACT),
        }, indent=2))
        return 0

    if args.command == "validate-contract":
        contract = load_semantic_contract(args.contract, args.database)
        print(json.dumps({
            "status": "PASS",
            "name": contract["name"],
            "database": contract["database"],
            "semantic_view": semantic_view_fqn(contract),
            "metric_count": len(contract["metrics"]),
            "verified_query_count": len(contract["verified_queries"]),
        }, indent=2))
        return 0

    if args.command == "release":
        result = build_release(
            args.output,
            args.database,
            contract_path=args.contract,
            baseline_path=args.baseline,
            source_sha=args.source_sha,
        )
        print(json.dumps({"status": "PASS", **result}, indent=2))
        return 0

    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
'''


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def _neutralize_installed_defaults(package_dir: Path) -> None:
    default_contract = package_dir / "default_semantic_contract.yml"
    semantic_contract = package_dir / "semantic_contract.py"
    text = semantic_contract.read_text(encoding="utf-8")
    old = 'ROOT / "config" / "semantic_contract.yml"'
    new = 'Path(__file__).resolve().parent / "default_semantic_contract.yml"'
    if old not in text:
        raise RuntimeError("standalone semantic-contract default path was not found")
    semantic_contract.write_text(text.replace(old, new), encoding="utf-8")
    if not default_contract.exists():
        raise RuntimeError("bundled default semantic contract is missing")


def build_distribution(contract: Path, output: Path) -> dict[str, Any]:
    core = export_core(contract, output)
    package_dir = output / "scripts" / "semantic_platform_core"
    bundled_contract = package_dir / "default_semantic_contract.yml"
    shutil.copyfile(output / "config" / "semantic_contract.yml", bundled_contract)
    _neutralize_installed_defaults(package_dir)

    (package_dir / "cli.py").write_text(CLI, encoding="utf-8")
    (output / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")

    manifest_path = output / "core_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update(
        {
            "distribution_version": 1,
            "installable_python_distribution": True,
            "distribution_name": "governed-semantic-platform-core",
            "cli": "semantic-platform-core",
            "bundled_default_contract": "scripts/semantic_platform_core/default_semantic_contract.yml",
            "runtime_dependencies": ["PyYAML>=6"],
            "optional_dependencies": {
                "snowflake": ["snowflake-connector-python>=3"],
                "dev": ["pytest>=8"],
            },
        }
    )
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    return {
        **core,
        "installable_python_distribution": True,
        "distribution_name": "governed-semantic-platform-core",
        "cli": "semantic-platform-core",
        "pyproject": str(output / "pyproject.toml"),
    }


def main() -> int:
    args = parse_args()
    try:
        result = build_distribution(args.contract, args.output)
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, indent=2))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
