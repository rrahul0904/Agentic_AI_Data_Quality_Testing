from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentic_data_platform.artifacts.factory import create_artifact_store
from agentic_data_platform.artifacts.store import ArtifactIntegrityError, ArtifactStoreError, FileArtifactStore


def test_filesystem_artifact_round_trip_and_receipt(tmp_path: Path) -> None:
    store = FileArtifactStore(tmp_path / "artifacts")
    receipt = store.put_json("evidence/run-1/report.json", {"status": "verified", "count": 3})
    assert receipt.backend == "filesystem"
    assert receipt.key == "evidence/run-1/report.json"
    assert len(receipt.sha256) == 64
    assert receipt.size > 0
    payload = json.loads(store.get_bytes(receipt.key))
    assert payload == {"count": 3, "status": "verified"}


def test_filesystem_artifact_rejects_path_traversal(tmp_path: Path) -> None:
    store = FileArtifactStore(tmp_path / "artifacts")
    for key in ("../secret", "/absolute", "a/../../secret", "a\\windows"):
        with pytest.raises(ArtifactStoreError):
            store.put_bytes(key, b"nope")


def test_filesystem_artifact_detects_tampering(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    store = FileArtifactStore(root)
    store.put_bytes("receipts/run.bin", b"original")
    (root / "receipts" / "run.bin").write_bytes(b"tampered")
    with pytest.raises(ArtifactIntegrityError, match="digest verification failed"):
        store.get_bytes("receipts/run.bin")


def test_filesystem_artifact_requires_integrity_metadata(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    store = FileArtifactStore(root)
    rogue = root / "rogue.bin"
    rogue.write_bytes(b"unreceipted")
    with pytest.raises(ArtifactIntegrityError, match="metadata is missing"):
        store.get_bytes("rogue.bin")


def test_artifact_factory_defaults_to_filesystem(tmp_path: Path) -> None:
    store = create_artifact_store({"ADE_ARTIFACT_ROOT": str(tmp_path / "artifacts")})
    assert isinstance(store, FileArtifactStore)


def test_artifact_factory_fails_closed_for_invalid_mode() -> None:
    with pytest.raises(ArtifactStoreError, match="filesystem, s3"):
        create_artifact_store({"ADE_ARTIFACT_STORE_MODE": "magic"})


def test_artifact_factory_fails_closed_for_s3_without_bucket() -> None:
    with pytest.raises(ArtifactStoreError, match="ADE_ARTIFACT_BUCKET"):
        create_artifact_store({"ADE_ARTIFACT_STORE_MODE": "s3"})
