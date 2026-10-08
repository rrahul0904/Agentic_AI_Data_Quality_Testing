from __future__ import annotations

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


def test_parquet_materialization_preserves_entity_counts(tmp_path: Path):
    generator = load_module(
        "rga_parquet_generator_test",
        ROOT / "scripts" / "rga_testbed" / "generate_data.py",
    )
    parquet = load_module(
        "rga_parquet_materialize_test",
        ROOT / "scripts" / "rga_testbed" / "materialize_parquet.py",
    )
    config = generator.load_config(ROOT / "config" / "rga_domain.yml")
    source = tmp_path / "source"
    source_manifest = generator.build_dataset(
        config=config,
        preset_name="tiny",
        seed=42,
        reference_date=date(2026, 9, 1),
        output=source,
        policy_override=60,
    )

    output = tmp_path / "parquet"
    report = parquet.materialize(
        source,
        output,
        memory_limit="128MB",
        row_group_size=1000,
    )

    assert report["status"] == "PASS"
    assert report["format"] == "parquet"
    assert report["compression"] == "zstd"
    assert report["source_generation_id"] == source_manifest["generation_id"]
    assert report["counts"] == source_manifest["counts"]
    assert report["file_count"] == len(source_manifest["files"])
    assert report["total_bytes"] > 0
    assert all(item["checksum"] for item in report["files"])
    assert all((output / item["file"]).exists() for item in report["files"])
    assert (output / "manifest.json").exists()


def test_parquet_materialization_rejects_too_small_row_groups(tmp_path: Path):
    parquet = load_module(
        "rga_parquet_row_group_test",
        ROOT / "scripts" / "rga_testbed" / "materialize_parquet.py",
    )
    try:
        parquet.materialize(
            tmp_path / "missing",
            tmp_path / "output",
            row_group_size=10,
        )
    except ValueError as exc:
        assert "row_group_size must be at least 1000" in str(exc)
    else:
        raise AssertionError("tiny Parquet row groups must be rejected")
