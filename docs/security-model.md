# Security Model

The platform follows the invariant: AI proposes, deterministic systems verify, and policy controls execution. Connector adapters are read-only by default. The `ToolRegistry` is the sole supported execution boundary and checks registered risk, platform, scopes, enabled status, policy, and production approval.

Approvals are tied to a run, scope, action, and optional environment; they can expire. Destructive operations are denied by baseline policy even when an invocation marks itself approved. Secrets are sourced by the host environment and never included in connector return values.
