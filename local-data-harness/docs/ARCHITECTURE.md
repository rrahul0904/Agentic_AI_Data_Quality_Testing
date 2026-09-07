# Architecture

```text
CLI / REPL / HTTP API
        |
        v
 AgentRuntime (turn loop + mode policy)
        |
        +------ Provider adapter ------> Mock | Ollama
        |
        v
 ToolRegistry / deterministic tools
   |        |        |       |       |
   SQL     dbt      PII    Files   Discover
   |                                  |
 SQLite                         local binaries/config
        |
        v
 SessionStore (local SQLite traces)
```

## Clean-room mapping to the reference product

- OpenCode-derived agent/server core -> small local `AgentRuntime` + HTTP API.
- Provider abstraction -> `MockProvider` and `OllamaProvider`.
- Deterministic data-engineering tools -> SQL analysis, draft lineage, PII, dbt inspection, discovery.
- Builder/Analyst/Plan permission model -> `ToolRegistry` policy gates.
- Local tracing -> Node built-in SQLite session store.
- TUI -> lightweight REPL for v0.1; richer terminal UI is a later phase.

The draft intentionally does not copy AltimateAI source code; it reproduces the architecture pattern using a much smaller local implementation.

## v0.2 pipeline-quality architecture

```text
                         +------------------+
                         |  LDH Agent / CLI |
                         +---------+--------+
                                   |
                          deterministic tools
                                   |
        +--------------------------+--------------------------+
        |                          |                          |
+-------v--------+        +--------v-------+         +--------v---------+
| Airflow tools |        |   dbt tools    |         | Snowflake tools  |
| static audit  |        | schema/tests   |         | config audit     |
| dags list     |        | parse/test     |         | ping/read query  |
| dags test*    |        | build*         |         | Python connector |
+-------+--------+        +--------+-------+         +--------+---------+
        |                          |                          |
        +--------------------------+--------------------------+
                                   |
                         +---------v---------+
                         |  quality_pipeline |
                         | policy + scoring  |
                         +-------------------+

* write/execution-capable operations are builder-only.
```

The Node runtime never stores Snowflake passwords. Live Snowflake work is delegated to a small Python bridge using the official connector, while static checks remain dependency-free.
