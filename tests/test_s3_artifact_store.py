from __future__ import annotations

import os
import uuid

import pytest

from agentic_data_platform.artifacts.factory import create_artifact_store
from agentic_data_platform.artifacts.store import ArtifactIntegrityError


ENDPOINT = os.getenv("ADE_TEST_S3_ENDPOINT")
pytestmark = pytest.mark.skipif(not ENDPOINT, reason="ADE_TEST_S3_ENDPOINT is not configured")


def _client():
    import boto3

    return boto3.client("s3", endpoint_url=ENDPOINT, region_name="us-east-1")


def test_real_s3_compatible_round_trip_and_digest_verification(monkeypatch) -> None:
    client = _client()
    bucket = f"ade-artifacts-{uuid.uuid4().hex[:12]}"
    client.create_bucket(Bucket=bucket)
    monkeypatch.setenv("ADE_ARTIFACT_STORE_MODE", "s3")
    monkeypatch.setenv("ADE_ARTIFACT_BUCKET", bucket)
    monkeypatch.setenv("ADE_ARTIFACT_PREFIX", "prototype-ci")
    monkeypatch.setenv("ADE_ARTIFACT_ENDPOINT_URL", str(ENDPOINT))
    monkeypatch.setenv("ADE_ARTIFACT_REGION", "us-east-1")

    store = create_artifact_store()
    receipt = store.put_json("evidence/run-42/receipt.json", {"verified": True, "run": 42})
    assert receipt.backend == "s3"
    assert receipt.key == "evidence/run-42/receipt.json"
    assert len(receipt.sha256) == 64
    assert store.get_bytes(receipt.key).endswith(b"\n")

    object_key = "prototype-ci/evidence/run-42/receipt.json"
    client.put_object(
        Bucket=bucket,
        Key=object_key,
        Body=b"tampered",
        ContentType="application/json",
        Metadata={"sha256": receipt.sha256},
    )
    with pytest.raises(ArtifactIntegrityError, match="digest verification failed"):
        store.get_bytes(receipt.key)


def test_real_s3_compatible_missing_digest_fails_closed(monkeypatch) -> None:
    client = _client()
    bucket = f"ade-artifacts-{uuid.uuid4().hex[:12]}"
    client.create_bucket(Bucket=bucket)
    client.put_object(Bucket=bucket, Key="ade/unverified.bin", Body=b"data")

    monkeypatch.setenv("ADE_ARTIFACT_STORE_MODE", "s3")
    monkeypatch.setenv("ADE_ARTIFACT_BUCKET", bucket)
    monkeypatch.setenv("ADE_ARTIFACT_PREFIX", "ade")
    monkeypatch.setenv("ADE_ARTIFACT_ENDPOINT_URL", str(ENDPOINT))
    monkeypatch.setenv("ADE_ARTIFACT_REGION", "us-east-1")
    store = create_artifact_store()
    with pytest.raises(ArtifactIntegrityError, match="metadata is missing"):
        store.get_bytes("unverified.bin")
