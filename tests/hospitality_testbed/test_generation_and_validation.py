from __future__ import annotations

import json

from generate_data import build_dataset
from validate_files import validate
from validate_pipeline import load_entities


def test_generator_is_deterministic_and_has_twenty_entities(generated_dataset, tmp_path):
    root, first, settings = generated_dataset
    second = build_dataset(settings, tmp_path / "second", record_runtime=False)
    first_projection = [(item["entity"], item["file"], item["row_count"], item["checksum"]) for item in first["files"]]
    second_projection = [(item["entity"], item["file"], item["row_count"], item["checksum"]) for item in second["files"]]
    assert first["generation_id"] == second["generation_id"]
    assert first_projection == second_projection
    assert len(first["entities"]) == 20
    assert first["file_count"] > 20
    assert root.joinpath("manifest.json").is_file()


def test_csv_parquet_manifest_and_file_validation(generated_dataset):
    root, manifest, _ = generated_dataset
    formats = {item["format"] for item in manifest["files"]}
    assert formats == {"csv", "parquet"}
    result = validate(root, root / "manifest.json")
    assert result["status"] == "PASS", result["findings"]
    assert result["verified_rows"] == manifest["row_count"]


def test_generated_relationships_are_coherent(generated_dataset):
    root, manifest, _ = generated_dataset
    entities = load_entities(manifest, root)
    hotels = {row["hotel_id"] for row in entities["hotels"]}
    rooms = {row["room_id"] for row in entities["rooms"]}
    guests = {row["guest_id"] for row in entities["guests"]}
    reservations = {row["reservation_id"] for row in entities["reservations"]}
    assert all(row["hotel_id"] in hotels for row in entities["rooms"])
    assert all(row["hotel_id"] in hotels and row["room_id"] in rooms and row["guest_id"] in guests for row in entities["reservations"])
    assert all(row["reservation_id"] in reservations for row in entities["payments"])
    assert all(row["reservation_id"] in reservations for row in entities["stays"])


def test_manifest_is_machine_readable_and_generation_bounded(generated_dataset):
    root, manifest, _ = generated_dataset
    persisted = json.loads((root / "manifest.json").read_text())
    assert persisted["generation_id"] == manifest["generation_id"]
    assert persisted["load_id"].startswith("load_")
    assert all(item["expected_target"].startswith("RAW.") for item in persisted["files"])
    assert all(item["checksum"] and item["row_count"] > 0 for item in persisted["files"])
