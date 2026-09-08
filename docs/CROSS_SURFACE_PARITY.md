# Cross-surface capability matrix

Statuses describe product exposure, not external live certification.

| Capability | CLI | Textual TUI | API | Web | Notes |
|---|---|---|---|---|---|
| Project discovery | EXPOSED | EXPOSED | EXPOSED | EXPOSED_READ_ONLY | Web consumes overview/inventory; CLI/TUI perform direct discovery |
| Deterministic review | EXPOSED | EXPOSED | EXPOSED | PARTIAL | Web exposes review domain/state; execution controls remain API/CLI/TUI |
| GitHub/GitLab review delivery | EXPOSED | PARTIAL | EXPOSED | PARTIAL | live credentials required |
| Production Data Diff | EXPOSED | EXPOSED | EXPOSED | PARTIAL | Web currently renders local/demo parity evidence; production parameter entry is API/CLI/TUI |
| dbt unit-test generation | EXPOSED | EXPOSED | EXPOSED via domain tool | NOT_EXPOSED | generation is approval/review oriented; Web dbt page is assurance/read-only |
| Trace replay | EXPOSED | EXPOSED | EXPOSED | EXPOSED | centralized redaction applies before display |
| Session replay | EXPOSED | EXPOSED | EXPOSED | EXPOSED | runtime/session replay routes are distinct |
| Provider/configuration state | EXPOSED | EXPOSED | EXPOSED | EXPOSED | configuration present does not imply live certification |
| Parity/certification evidence | SCRIPTS/GENERIC TOOL | PARTIAL | INDIRECT | NOT_EXPOSED | authoritative machine evidence is CI/script generated; this divergence is intentional |
| Agent natural-language workflow | EXPOSED through `agentic` | EXPOSED | EXPOSED | EXPOSED | external provider may be `SKIP_EXTERNAL` |

## Intentional differences

The Web operator console prioritizes read/triage workflows and does not currently duplicate every low-level generation or certification command. Those operations remain available through governed CLI/TUI/API or release scripts. This is documented rather than represented as full cross-surface parity.

All surfaces share deterministic engines and policy boundaries; exposure differences are presentation/API choices, not separate implementations.
