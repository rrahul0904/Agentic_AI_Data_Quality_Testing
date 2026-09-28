# Ask AI: local backend unavailable versus provider failure

## Incident

Ask AI displayed `fetch failed` while both local listeners were absent: UI `127.0.0.1:3020` and API `127.0.0.1:8011` returned connection refused. A local server outage was incorrectly easy to interpret as an OpenAI-key failure.

## Evidence and resolution

- Restarted the existing demo launcher without rebuilding or reseeding user data. The API and UI both returned HTTP 200.
- An explicit, bounded provider verification returned `COMPLETED` / `verified` for the project override `openai` / `gpt-5.6-terra`.
- A full Ask AI request was persisted in history as `LIVE_RESPONSE` with that provider and model. This confirms the key and question path worked at test time; it does not guarantee future provider availability or answer correctness.
- The server-default banner listed `gpt-4.1-mini`; that is not the project-specific model used by Ask AI.
- A `launchctl submit` background start exited 126 with `Operation not permitted` for the project script under `Documents`. No folder permissions were changed. The running launcher is held in a detached `screen` session named `ade-demo` under the normal user context.
- UI API routes now distinguish backend unavailability/timeouts from model-provider errors, without exposing raw transport internals or claiming that an unavailable backend proves a bad key.

## Regression checks

- `curl` to UI and API endpoints returns HTTP 200 after server start.
- Provider verification returns a scoped verified result only after a live provider request.
- Ask AI history records a `LIVE_RESPONSE` for a scoped question.
- With the backend unavailable, the proxy returns `ASK_AI_BACKEND_UNAVAILABLE` or `ASK_AI_BACKEND_TIMEOUT` instead of the raw `fetch failed` string.
- `npm test`, TypeScript typecheck, and production build pass.
