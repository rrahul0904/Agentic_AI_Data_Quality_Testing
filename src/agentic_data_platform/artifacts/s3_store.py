from __future__ import annotations

from typing import Any

from .store import (
    ArtifactIntegrityError,
    ArtifactReceipt,
    ArtifactStoreError,
    canonical_json_bytes,
    sha256_bytes,
    validate_artifact_key,
)


class S3ArtifactStore:
    """S3-compatible artifact adapter with SHA-256 metadata verification."""

    def __init__(
        self,
        *,
        bucket: str,
        prefix: str = "ade",
        endpoint_url: str | None = None,
        region_name: str | None = None,
        client: Any | None = None,
    ):
        if not bucket or not bucket.strip():
            raise ArtifactStoreError("ADE_ARTIFACT_BUCKET is required for s3 artifact storage")
        self.bucket = bucket.strip()
        self.prefix = prefix.strip("/")
        if self.prefix:
            validate_artifact_key(self.prefix)
        if client is None:
            try:
                import boto3
            except ImportError as exc:  # pragma: no cover - guarded by cloud packaging/CI
                raise ArtifactStoreError("boto3 is required for s3 artifact storage; install ADE with the cloud extra") from exc
            kwargs: dict[str, str] = {}
            if endpoint_url:
                kwargs["endpoint_url"] = endpoint_url
            if region_name:
                kwargs["region_name"] = region_name
            client = boto3.client("s3", **kwargs)
        self.client = client

    def _object_key(self, key: str) -> str:
        validate_artifact_key(key)
        return f"{self.prefix}/{key}" if self.prefix else key

    def put_bytes(self, key: str, data: bytes, *, content_type: str = "application/octet-stream") -> ArtifactReceipt:
        if not isinstance(data, bytes):
            raise TypeError("artifact data must be bytes")
        digest = sha256_bytes(data)
        object_key = self._object_key(key)
        try:
            response = self.client.put_object(
                Bucket=self.bucket,
                Key=object_key,
                Body=data,
                ContentType=content_type,
                Metadata={"sha256": digest},
            )
        except Exception as exc:
            raise ArtifactStoreError(f"s3 artifact write failed for key: {key}") from exc
        etag = str(response.get("ETag") or "").strip('"') or None
        return ArtifactReceipt(key, digest, len(data), content_type, "s3", etag)

    def get_bytes(self, key: str) -> bytes:
        object_key = self._object_key(key)
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=object_key)
            data = response["Body"].read()
        except Exception as exc:
            raise ArtifactStoreError(f"s3 artifact read failed for key: {key}") from exc
        expected = (response.get("Metadata") or {}).get("sha256")
        if not expected:
            raise ArtifactIntegrityError(f"s3 artifact digest metadata is missing: {key}")
        digest = sha256_bytes(data)
        if digest != expected:
            raise ArtifactIntegrityError(f"s3 artifact digest verification failed: {key}")
        return data

    def put_json(self, key: str, payload: object) -> ArtifactReceipt:
        return self.put_bytes(key, canonical_json_bytes(payload), content_type="application/json")
