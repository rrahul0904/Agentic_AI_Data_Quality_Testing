# Snowflake-managed MCP external client smoke

The governed semantic platform exposes the Cortex Agent as the client-facing Snowflake-managed MCP tool. This keeps semantic questions behind the Agent instead of exposing unrestricted SQL on the same MCP server.

Snowflake-managed MCP uses OAuth 2.0. The managed endpoint format is:

```text
https://<account_url>/api/v2/databases/<database>/schemas/<schema>/mcp-servers/<server>
```

The repository smoke client uses `tools/list` to prove the configured governed tool is discoverable and `tools/call` to invoke that exact tool with a verified business question.

## Evidence boundary

The smoke deliberately does **not** persist:

- the OAuth bearer token;
- the raw `tools/call` result;
- Cortex Agent reasoning/intermediate traces.

It persists tool metadata hashes, HTTP/transport status, request IDs when returned, response SHA-256 values, and proof that a JSON-RPC result was returned. Business-result parity is certified separately by the Agent/Snowflake/Power BI/Excel parity suite.

## Dry-run

Dry-run requires no OAuth token:

```bash
semantic-platform mcp-smoke \
  --workspace artifacts/semantic_platform_demo \
  --endpoint https://<account>/api/v2/databases/RGA_SYNTHETIC_TESTBED/schemas/AI/mcp-servers/RGA_REINSURANCE_MCP \
  --dry-run
```

The governed tool name and business question are derived from the generated release (`release/ai/mcp_spec.yml` and `release/parity/parity_manifest.json`).

## Live smoke

Obtain an OAuth access token for the Snowflake role that has the required MCP Server and Cortex Agent privileges, then place it in the process environment only:

```bash
export SNOWFLAKE_MCP_ACCESS_TOKEN='<oauth access token>'

semantic-platform mcp-smoke \
  --workspace artifacts/semantic_platform_demo \
  --endpoint https://<account>/api/v2/databases/RGA_SYNTHETIC_TESTBED/schemas/AI/mcp-servers/RGA_REINSURANCE_MCP \
  --confirm
```

By default the evidence is written to:

```text
artifacts/semantic_platform_demo/evidence/mcp_remote_smoke.json
```

## Current Snowflake transport behavior

The client advertises both:

```text
Accept: application/json, text/event-stream
```

Snowflake-managed MCP `tools/call` responses are consumed as Server-Sent Events and terminate with the `[DONE]` event. The client also accepts JSON responses for operations such as `tools/list`.

## Required privileges

The OAuth identity/role still needs the Snowflake privileges for the MCP server and the underlying Cortex Agent/resources. Repository certification cannot manufacture these target-account grants or OAuth credentials.
