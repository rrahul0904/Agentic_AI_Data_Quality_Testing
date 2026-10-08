from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
from typing import Protocol
import uuid


class ArtifactStoreError(RuntimeError):
    """Raised when an artifact cannot be stored or retrieved safely."""


class ArtifactIntegrityError(ArtifactStoreError):
    """Raised when persisted artifact bytes no longer match their recorded digest."""


@dataclass(frozen=True)
class ArtifactReceipt:
    key: str
    sha256: str
    size: int
    content_type: str
    backend: str
    etag: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class ArtifactStore(Protocol):
    def put_bytes(self, key: str, data: bytes, *, content_type: str = "application/octet-stream") -> ArtifactReceipt: ...

    def get_bytes(self, key: str) -> bytes: ...

    def put_json(self, key: str, payload: object) -> ArtifactReceipt: ...


def validate_artifact_key(key: str) -> tuple[str, ...]:
    candidate = str(key)
    if not candidate or candidate.startswith("/") or "\\" in candidate or "\x00" in candidate:
        raise ArtifactStoreError("artifact key must be a non-empty relative POSIX path")
    parts = candidate.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ArtifactStoreError("artifact key contains an unsafe path segment")
    return tuple(parts)


def canonical_json_bytes(payload: object) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class FileArtifactStore:
    """Digest-verifying filesystem adapter for local/dev and single-node deployments."""

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.metadata_root = self.root / ".ade-metadata"
        self.metadata_root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _metadata_name(key: str) -> str:
        return hashlib.sha256(key.encode("utf-8")).hexdigest() + ".json"

    def _artifact_path(self, key: str) -> Path:
        parts = validate_artifact_key(key)
        cursor = self.root
        for part in parts[:-1]:
            cursor = cursor / part
            if cursor.exists() and cursor.is_symlink():
                raise ArtifactStoreError(f"artifact path traverses a symlink: {key}")
        path = self.root.joinpath(*parts)
        if path.exists() and path.is_symlink():
            raise ArtifactStoreError(f"artifact path resolves to a symlink: {key}")
        return path

    def _metadata_path(self, key: str) -> Path:
        return self.metadata_root / self._metadata_name(key)

    @staticmethod
    def _atomic_write(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
        try:
            with temp.open("xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)

    def put_bytes(self, key: str, data: bytes, *, content_type: str = "application/octet-stream") -> ArtifactReceipt:
        if not isinstance(data, bytes):
            raise TypeError("artifact data must be bytes")
        path = self._artifact_path(key)
        digest = sha256_bytes(data)
        metadata = {
            "schema_version": "ade.artifact-receipt.v1",
            "key": key,
            "sha256": digest,
            "size": len(data),
            "content_type": content_type,
            "backend": "filesystem",
        }
        self._atomic_write(path, data)
        self._atomic_write(self._metadata_path(key), canonical_json_bytes(metadata))
        return ArtifactReceipt(key, digest, len(data), content_type, "filesystem")

    def get_bytes(self, key: str) -> bytes:
        path = self._artifact_path(key)
        metadata_path = self._metadata_path(key)
        if not path.is_file():
            raise ArtifactStoreError(f"artifact does not exist: {key}")
        if not metadata_path.is_file():
            raise ArtifactIntegrityError(f"artifact integrity metadata is missing: {key}")
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ArtifactIntegrityError(f"artifact integrity metadata is invalid: {key}") from exc
        data = path.read_bytes()
        digest = sha256_bytes(data)
        if metadata.get("key") != key or metadata.get("sha256") != digest or metadata.get("size") != len(data):
            raise ArtifactIntegrityError(f"artifact digest verification failed: {key}")
        return data

    def put_json(self, key: str, payload: object) -> ArtifactReceipt:
        return self.put_bytes(key, canonical_json_bytes(payload), content_type="application/json")
