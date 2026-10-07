# Cloud project sources

ADE hosted startup no longer requires a developer-machine bind mount for `/workspace`.
The hosted API resolves a project source before constructing the existing API and agent
runtime, then points `ADE_PROJECT_ROOT` at the materialized project.

## Modes

### `embedded_demo`

The production/release/Kubernetes examples default to the deterministic synthetic
project already baked into the API image. This makes a clean Prototype 1.0 deployment
bootable without external project credentials.

### `filesystem`

Set `ADE_PROJECT_SOURCE_MODE=filesystem` and `ADE_PROJECT_ROOT` to a directory already
available inside the runtime. This preserves local/operator-managed filesystem behavior.

### `git`

Set:

```text
ADE_PROJECT_SOURCE_MODE=git
ADE_PROJECT_GIT_URL=https://github.com/OWNER/REPOSITORY.git
ADE_PROJECT_GIT_REF=<branch-tag-or-commit>   # recommended
ADE_WORKSPACE_ROOT=/workspaces
```

The prototype Git adapter deliberately accepts HTTPS only, rejects embedded credentials,
query parameters and fragments, disables interactive prompts, materializes beneath a
hash-derived managed path, removes `.git`, rejects project-content symlinks, and writes
`.ade/project-source.json` with the exact checked-out commit SHA.

An explicit ref is cacheable and reproducible. If the ref is omitted, ADE refreshes the
repository default branch on each hosted process start instead of treating a moving
branch as immutable evidence.

Private-repository authentication is intentionally not smuggled into the URL. It should
be added through a secret-backed GitHub/App credential adapter as a separate bounded
slice so tokens never become part of receipts, process arguments, or error messages.
