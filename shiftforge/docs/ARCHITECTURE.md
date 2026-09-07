# Architecture

```text
Local repo / pasted SQL
        |
        v
  Repository Scanner
        |
        v
  dbt Context Extractor ------> manifest/catalog (phase 2)
        |
        v
  Compatibility Analyzer
   | deterministic rules
   | physical design checks
   | semantic-risk detector
        |
        +------ blocked/ambiguous ------> Optional LLM remediation agent
        |
        v
  Converted workspace (sibling tree)
        |
        v
  Isolated dbt compile / parse / tests
        |
        v
  Migration report + diffs + review UI
```

## Launch services

- **CLI:** primary local/privacy-safe product for real dbt repositories.
- **API:** stateless conversion endpoint for the web experience and integrations.
- **Web UI:** paste/review MVP today; repository upload/Git integration in phase 2.
- **Worker (phase 2):** queued large-repository conversions, compile/test jobs, retry policy.
- **Metadata DB (phase 2):** projects, conversion runs, findings, approvals, artifacts.

## Conversion philosophy

A migration tool should not ask an LLM to rewrite every query blindly. Safe syntax changes are deterministic and testable; semantic changes are explicit review items. This reduces cost, makes output reproducible, and produces an audit trail suitable for enterprise migration programs.
