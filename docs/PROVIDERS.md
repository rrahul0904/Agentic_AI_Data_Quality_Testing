# Provider and warehouse certification

## Model providers

The ProviderRegistry registers 22 configurations: OpenAI, Anthropic, OpenRouter, Gemini, Azure OpenAI, Vertex AI, Bedrock, Groq, Mistral, Together, xAI, DeepInfra, NVIDIA, Cerebras, Perplexity, Vercel AI Gateway, Cohere, Ollama, LM Studio, Databricks AI Gateway, Snowflake Cortex, and explicitly authorized GitHub Copilot.

Contract/mock tests verify normalization and configuration behavior. **They are not live certification.** Structural certification leaves network operations `NOT_RUN`; live mode returns `SKIP_EXTERNAL` when credentials/model configuration are absent.

## Warehouse targets

The certification framework enumerates Snowflake, BigQuery, Databricks, PostgreSQL, Redshift, Trino, ClickHouse, DuckDB, MySQL, SQL Server, Oracle, SQLite, and MongoDB.

DuckDB/SQLite can be exercised locally. External warehouse live state depends on connector installation and credentials. An implemented adapter with no remote execution remains implemented/structurally tested, not live certified.

## Authoritative evidence layers

| Layer | Evidence |
|---|---|
| Contract/unit | mocked/local protocol behavior |
| Local integration | actual local engine/connector execution |
| Live integration | real external service call |
| Release CI | exact-head CI job result |

Missing external configuration is `SKIP_EXTERNAL` or `BLOCKED_EXTERNAL`, never a synthetic `PASS`.

See `ENVIRONMENT.md` for exact variables.
