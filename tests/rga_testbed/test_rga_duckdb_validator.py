from __future__ import annotations

import csv
import importlib.util
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _generate_dataset(root: Path, policies: int = 80) -> Path:
    generator = load_module(
        "rga_duckdb_validator_generator",
        ROOT / "scripts" / "rga_testbed" / "generate_data.py",
    )
    config = generator.load_config(ROOT / "config" / "rga_domain.yml")
    generator.build_dataset(
        config=config,
        preset_name="tiny",
        seed=42,
        reference_date=date(2026, 9, 1),
        output=root,
        policy_override=policies,
    )
    return root


def _validator():
    return load_module(
        "rga_duckdb_validator_test",
        ROOT / "scripts" / "rga_testbed" / "validate_dataset_duckdb.py",
    )


def test_duckdb_validator_passes_streaming_dataset(tmp_path: Path):
    root = _generate_dataset(tmp_path / "dataset")
    report = _validator().validate(
        root,
        config_path=ROOT / "config" / "rga_domain.yml",
        memory_limit="128MB",
    )

    assert report["status"] == "PASS"
    assert report["engine"] == "duckdb_out_of_core"
    assert report["errors"] == []
    assert report["counts"]["policies"] == 80
    assert report["counts"]["insured_lives"] == 80
    assert "all configured foreign keys" in report["scope"]


def test_duckdb_validator_detects_foreign_key_corruption(tmp_path: Path):
    root = _generate_dataset(tmp_path / "dataset", policies=40)
    policy_file = sorted((root / "csv" / "policies").glob("*.csv"))[0]

    with policy_file.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
        fieldnames = list(rows[0])
    rows[0]["treaty_id"] = "TRT_DOES_NOT_EXIST"
    with policy_file.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    # Update only the file checksum so relational validation, not checksum drift,
    # is the reason this dataset fails.
    import json
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    sha256 = _validator().sha256
    relative = policy_file.relative_to(root).as_posix()
    for item in manifest["files"]:
        if item["file"] == relative:
            item["checksum"] = sha256(policy_file)
            break
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    report = _validator().validate(
        root,
        config_path=ROOT / "config" / "rga_domain.yml",
        memory_limit="128MB",
    )

    assert report["status"] == "FAIL"
    assert any(
        "policies.treaty_id" in error and "missing references" in error
        for error in report["errors"]
    )


def test_duckdb_validator_detects_duplicate_business_key(tmp_path: Path):
    root = _generate_dataset(tmp_path / "dataset", policies=30)
    policy_file = sorted((root / "csv" / "policies").glob("*.csv"))[0]

    with policy_file.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
        fieldnames = list(rows[0])
    rows[1]["policy_id"] = rows[0]["policy_id"]
    with policy_file.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    import json
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    validator = _validator()
    relative = policy_file.relative_to(root).as_posix()
    for item in manifest["files"]:
        if item["file"] == relative:
            item["checksum"] = validator.sha256(policy_file)
            break
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    report = validator.validate(
        root,
        config_path=ROOT / "config" / "rga_domain.yml",
        memory_limit="128MB",
    )
    assert report["status"] == "FAIL"
    assert any(
        "policies has" in error and "duplicate business keys" in error
        for error in report["errors"]
    )
