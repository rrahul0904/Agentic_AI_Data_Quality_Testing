from __future__ import annotations

import csv
import importlib.util
import json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _generator():
    return load_module(
        "rga_streaming_generator_test",
        ROOT / "scripts" / "rga_testbed" / "generate_data.py",
    )


def test_streaming_writer_rotates_without_buffering_all_rows(tmp_path: Path):
    module = _generator()
    config = module.load_config(ROOT / "config" / "rga_domain.yml")
    writer = module.Writer(
        tmp_path,
        config,
        generation_id="test_generation",
        rows_per_file=2,
    )

    for idx in range(5):
        writer.write_row(
            "cedants",
            {
                "cedant_id": f"CED{idx}",
                "cedant_name": f"Cedant {idx}",
                "country_code": "US",
                "currency_code": "USD",
                "market_segment": "LIFE",
                "active": True,
            },
        )
    writer.close()

    assert writer.counts["cedants"] == 5
    files = [item for item in writer.files if item["entity"] == "cedants"]
    assert [item["row_count"] for item in files] == [2, 2, 1]
    assert all(item["checksum"] for item in files)

    observed = []
    for item in files:
        with (tmp_path / item["file"]).open(encoding="utf-8", newline="") as handle:
            observed.extend(csv.DictReader(handle))
    assert [row["cedant_id"] for row in observed] == [
        "CED0",
        "CED1",
        "CED2",
        "CED3",
        "CED4",
    ]


def test_streaming_generator_is_deterministic_for_same_inputs(tmp_path: Path):
    module = _generator()
    config = module.load_config(ROOT / "config" / "rga_domain.yml")
    first = tmp_path / "first"
    second = tmp_path / "second"

    manifest_one = module.build_dataset(
        config=config,
        preset_name="tiny",
        seed=42,
        reference_date=date(2026, 9, 1),
        output=first,
        policy_override=25,
    )
    manifest_two = module.build_dataset(
        config=config,
        preset_name="tiny",
        seed=42,
        reference_date=date(2026, 9, 1),
        output=second,
        policy_override=25,
    )

    assert manifest_one["generation_id"] == manifest_two["generation_id"]
    assert manifest_one["counts"] == manifest_two["counts"]
    comparable_one = [
        (item["entity"], item["row_count"], item["checksum"])
        for item in manifest_one["files"]
    ]
    comparable_two = [
        (item["entity"], item["row_count"], item["checksum"])
        for item in manifest_two["files"]
    ]
    assert comparable_one == comparable_two


def test_streaming_generator_respects_rows_per_file_rotation(tmp_path: Path):
    module = _generator()
    config = module.load_config(ROOT / "config" / "rga_domain.yml")
    config = json.loads(json.dumps(config))
    config["presets"]["tiny"]["rows_per_file"] = 10

    manifest = module.build_dataset(
        config=config,
        preset_name="tiny",
        seed=7,
        reference_date=date(2026, 9, 1),
        output=tmp_path / "dataset",
        policy_override=23,
    )

    policy_files = [
        item for item in manifest["files"] if item["entity"] == "policies"
    ]
    assert [item["row_count"] for item in policy_files] == [10, 10, 3]

    exposure_files = [
        item
        for item in manifest["files"]
        if item["entity"] == "exposure_monthly"
    ]
    assert exposure_files
    assert all(item["row_count"] <= 10 for item in exposure_files)


def test_scale_benchmark_reports_real_generation_evidence(tmp_path: Path):
    module = load_module(
        "rga_scale_benchmark_test",
        ROOT / "scripts" / "rga_testbed" / "benchmark_generation.py",
    )
    report = module.benchmark(
        config_path=ROOT / "config" / "rga_domain.yml",
        preset="tiny",
        policies=50,
        seed=42,
        reference_date=date(2026, 9, 1),
        output=tmp_path / "scale",
    )

    assert report["status"] == "PASS"
    assert report["policies"] == 50
    assert report["total_rows"] > 50
    assert report["file_count"] > 0
    assert report["total_bytes"] > 0
    assert report["elapsed_seconds"] >= 0
    assert report["peak_rss_mb"] > 0
    assert report["row_emission"] == "streaming_rotating_csv"
    assert "not proof of Snowflake" in report["scope"]
