from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

from .store import ArtifactStore, ArtifactStoreError, FileArtifactStore


def create_artifact_store(env: Mapping[str, str] | None = None) -> ArtifactStore:
    values = os.environ if env is None else env
    mode = str(values.get("ADE_ARTIFACT_STORE_MODE") or "filesystem").strip().lower()

    if mode == "filesystem":
        root = str(values.get("ADE_ARTIFACT_ROOT") or ".ade/artifacts").strip()
        if not root:
            raise ArtifactStoreError("ADE_ARTIFACT_ROOT is required for filesystem artifact storage")
        return FileArtifactStore(Path(root))

    if mode == "s3":
        bucket = str(values.get("ADE_ARTIFACT_BUCKET") or "").strip()
        if not bucket:
            raise ArtifactStoreError("ADE_ARTIFACT_BUCKET is required for s3 artifact storage")
        prefix = str(values.get("ADE_ARTIFACT_PREFIX") or "ade").strip()
        endpoint_url = str(values.get("ADE_ARTIFACT_ENDPOINT_URL") or "").strip() or None
        region_name = str(values.get("ADE_ARTIFACT_REGION") or values.get("AWS_REGION") or "").strip() or None
        from .s3_store import S3ArtifactStore

        return S3ArtifactStore(
            bucket=bucket,
            prefix=prefix,
            endpoint_url=endpoint_url,
            region_name=region_name,
        )

    raise ArtifactStoreError("ADE_ARTIFACT_STORE_MODE must be one of: filesystem, s3")
