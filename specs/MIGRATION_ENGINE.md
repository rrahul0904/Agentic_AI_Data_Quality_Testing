# Migration engine

ShiftForge remains a standalone Python package. The root
`ShiftForgeAdapter` imports its deterministic engine through a structured
JSON-compatible boundary for scan, inventory, conversion, validation, findings,
and blockers. Dry-run conversion is available for inspection; writing output
remains a Builder-controlled operation.
