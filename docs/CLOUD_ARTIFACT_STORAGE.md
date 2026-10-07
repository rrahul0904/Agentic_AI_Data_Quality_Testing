# Cloud artifact storage

ADE keeps normalized control-plane, investigation/evidence, and quality state in its
database adapters. Generated/exportable evidence bundles, source receipts, reports, and
other binary artifacts use a separate provider-neutral artifact seam.

## Filesystem mode

The default remains deterministic for local development and single-node demos:

```text
ADE_ARTIFACT_STORE_MODE=filesystem
ADE_ARTIFACT_ROOT=/state/artifacts
```

Every write produces SHA-256 integrity metadata. Reads fail closed if metadata is
missing or the persisted bytes no longer match the recorded digest.

## S3-compatible mode

```text
ADE_ARTIFACT_STORE_MODE=s3
ADE_ARTIFACT_BUCKET=<bucket>
ADE_ARTIFACT_PREFIX=ade
ADE_ARTIFACT_REGION=us-east-1
ADE_ARTIFACT_ENDPOINT_URL=              # optional; set for an S3-compatible endpoint
```

Authentication uses the standard boto3/AWS credential chain. Do not place access keys
in the ConfigMap or artifact receipt. Kubernetes deployments can inject standard AWS
environment variables through the existing `ade-api-secrets` Secret, or use workload
identity/instance roles. Docker operators should use their secret-management mechanism
or an environment override rather than committing credentials.

When `s3` is selected, ADE does not fall back to filesystem storage. Write/read errors
are surfaced as artifact-store errors. S3 objects carry the SHA-256 digest as object
metadata; every ADE read verifies the downloaded bytes against that digest.

The hosted runtime also mirrors a managed Git project's `.ade/project-source.json` into
`project-sources/<commit-sha>/receipt.json`, preserving the exact analyzed source
revision independently of the ephemeral worker checkout.

## CI certification

`prototype-persistence-ci` starts a networked S3 API compatibility server on localhost
alongside PostgreSQL. The server is provided by Moto and is exercised through boto3 over
HTTP; it is not an in-process stub. The gate tests:
- filesystem integrity and traversal rejection;
- networked S3-compatible put/get behavior;
- missing digest rejection;
- tamper detection;
- PostgreSQL control-plane/investigation/quality persistence;
- managed project-source contracts.

This certifies ADE's provider-neutral S3 API contract. It does not claim external
certification against AWS S3, MinIO, or every vendor-specific S3 implementation; those
remain target-environment certification steps.
