# Unified Project Context and Low-Cost Agent Runtime

ADE now has a single project-aware context path for repository files, uploaded documents, pasted text, deterministic engineering tools, and the governed LLM runtime.

## Design

```text
Repository code ─┐
PDF / DOCX ──────┤
Pasted text ─────┤
Business rules ──┤
                 ▼
        project/.ade/training.db
             SQLite FTS5
                 │
                 ▼
        bounded context selection
                 │
User question ───┼──────────────┐
                 ▼              ▼
              LLM agent   deterministic tools
                 │              │
                 └──── evidence ┘
                        │
                        ▼
                 grounded answer
```

Documents and repository files are retrieved locally before an LLM request. The first implementation intentionally does **not** require an embeddings API or vector database.

## Supported document inputs

- PDF with extractable text
- DOCX
- TXT / Markdown
- SQL / Python
- YAML / JSON / CSV

Image-only/scanned PDFs are rejected with an explicit error. OCR is intentionally not performed implicitly.

The default upload limit is 20 MB and can be changed with `ADE_KNOWLEDGE_UPLOAD_MAX_BYTES`.

## Project indexing

The runtime indexes bounded repository context such as:

- README / AGENTS / CLAUDE files
- docs and specs
- dbt SQL/YAML
- Airflow DAG Python
- model SQL/YAML

Indexing is hash-aware: unchanged sources are not duplicated.

## Web API

```text
GET  /api/v1/knowledge/status
GET  /api/v1/knowledge/search?query=...
POST /api/v1/knowledge/index-project
POST /api/v1/knowledge/ingest-text
POST /api/v1/knowledge/upload
POST /api/v1/agent/query
```

`/api/v1/agent/query` uses the governed LLM runtime automatically when the selected provider is configured. With no provider credentials it preserves the deterministic router.

Request modes:

- `auto` — live agent when configured, otherwise deterministic fallback
- `live` — require an LLM and return `BLOCKED_EXTERNAL` when credentials are absent
- `deterministic` — never call an LLM

## CLI

Index the current project:

```bash
ade knowledge index --project /path/to/project
```

Upload a local document into project context:

```bash
ade knowledge ingest /path/to/Revenue-Business-Rules.docx --project /path/to/project
```

Search:

```bash
ade knowledge search "RevPAR refunds" --project /path/to/project
```

Ask the same project-aware agent from the terminal:

```bash
ade ask "Why is today's revenue report low?" --project /path/to/project
```

The web and terminal paths use the same project-local training, runtime-session and trace stores.

## OpenAI configuration

Do not commit secrets.

```bash
export OPENAI_API_KEY='...'
export ADE_AGENT_PROVIDER='openai'
export ADE_AGENT_MODEL='gpt-5.6-luna'
```

Default cost controls:

```bash
ADE_AGENT_MAX_STEPS=8
ADE_AGENT_CONTEXT_TOKENS=32000
ADE_AGENT_CONTEXT_CHUNKS=6
ADE_AGENT_MAX_OUTPUT_TOKENS=1600
ADE_OPENAI_REASONING_EFFORT=low
```

All settings are overridable.

## Evidence hierarchy

The agent prompt enforces this hierarchy:

1. direct deterministic measurement / query results
2. runtime evidence such as Airflow/dbt execution state
3. code/static lineage and SQL analysis
4. approved project documents and business rules
5. LLM interpretation

Documentation may describe intended behavior, but it cannot override measured runtime facts.

## Safety

The project-aware LLM receives only read-only ToolRegistry definitions. Mutating tools are not exposed in this runtime.

The agent may propose remediation, but production mutation remains on ADE's existing approval-gated execution path.

## Cost strategy

The low-cost design is deliberate:

- local SQLite FTS retrieval, no embedding API calls
- only a bounded number of relevant chunks are injected
- read-only tools retrieve facts instead of asking the model to infer them
- bounded agent steps
- bounded completion size
- low reasoning effort by default
- model remains configurable

For difficult investigations the user can raise reasoning effort or switch models without changing the architecture.
