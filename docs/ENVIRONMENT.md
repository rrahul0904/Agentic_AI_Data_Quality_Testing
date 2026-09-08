# Environment and external integration reference

No value in this document is a real credential. Missing optional external configuration must produce `SKIP_EXTERNAL`, `BLOCKED_EXTERNAL`, or an unavailable state.

## GitHub review

| Variable | Required for live | Purpose |
|---|---:|---|
| `GITHUB_TOKEN` | direct default adapter only | default GitHub review token |
| `ADE_REVIEW_GITHUB_TOKEN` | yes | live-review token with PR/read/comment/review permissions |
| `ADE_REVIEW_GITHUB_REPOSITORY` | yes | `owner/name` repository |
| `ADE_REVIEW_GITHUB_PR_NUMBER` | yes | target pull request |
| `ADE_REVIEW_GITHUB_API_URL` | no | alternate HTTP(S) GitHub-compatible API base |

Absence of the live token/repository/PR is `SKIP_EXTERNAL`.

## GitLab review

| Variable | Required for live | Purpose |
|---|---:|---|
| `GITLAB_TOKEN` | direct default adapter only | default GitLab token |
| `ADE_REVIEW_GITLAB_TOKEN` | yes | live-review token with MR read/note permissions |
| `ADE_REVIEW_GITLAB_PROJECT` | yes | project path/id |
| `ADE_REVIEW_GITLAB_MR_IID` | yes | merge request IID |
| `ADE_REVIEW_GITLAB_API_URL` | no | GitLab.com or validated self-hosted HTTP(S) `/api/v4` base |

## Snowflake

Generic connector/Data Diff variables: `ADE_SNOWFLAKE_ACCOUNT`, `ADE_SNOWFLAKE_USER`, `ADE_SNOWFLAKE_PASSWORD`, `ADE_SNOWFLAKE_DATABASE`, `ADE_SNOWFLAKE_SCHEMA`, `ADE_SNOWFLAKE_WAREHOUSE`, `ADE_SNOWFLAKE_ROLE`.

The dedicated live proving-ground harness uses `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER`, `SNOWFLAKE_PASSWORD`, `SNOWFLAKE_DATABASE`, `SNOWFLAKE_SCHEMA`, `SNOWFLAKE_WAREHOUSE`, and optional `SNOWFLAKE_ROLE`. dbt live mutation additionally requires `ADE_DBT_LIVE_MUTATION_APPROVED=true`.

## External Airflow

`ADE_AIRFLOW_BASE_URL` and either `ADE_AIRFLOW_TOKEN` or both `ADE_AIRFLOW_USERNAME`/`ADE_AIRFLOW_PASSWORD` are required for live REST execution. `ADE_AIRFLOW_VERSION` selects version behavior. Mutating live tests require `ADE_AIRFLOW_LIVE_MUTATION_APPROVED=true`.

## Data Diff external harness

`ADE_DATA_DIFF_SOURCE_PLATFORM`, `ADE_DATA_DIFF_TARGET_PLATFORM`, `ADE_DATA_DIFF_SOURCE_TABLE`, `ADE_DATA_DIFF_TARGET_TABLE`, `ADE_DATA_DIFF_KEYS`; optional execution controls `ADE_DATA_DIFF_COMPARE_COLUMNS`, `ADE_DATA_DIFF_PARTITION_STRATEGY`, `ADE_DATA_DIFF_MAX_PARTITION_ROWS`, `ADE_DATA_DIFF_DETAIL_LIMIT`, `ADE_DATA_DIFF_TIMEOUT_SECONDS`.

A 100M+ **certification pass** additionally requires explicit known-change expectations: `ADE_DATA_DIFF_EXPECT_STATUS`, `ADE_DATA_DIFF_EXPECT_CHANGED_KEYS`, `ADE_DATA_DIFF_EXPECT_MISSING_KEYS`, and `ADE_DATA_DIFF_EXPECT_EXTRA_KEYS`. Missing expectations produce `NOT_RUN_EXPECTATION_UNCONFIGURED`, not PASS.

Warehouse-specific connector variables include:

- PostgreSQL: `ADE_POSTGRES_DSN`
- Redshift: `ADE_REDSHIFT_DSN`
- MySQL: `ADE_MYSQL_HOST`, `ADE_MYSQL_USER`, `ADE_MYSQL_PASSWORD`, `ADE_MYSQL_DATABASE`
- SQL Server: `ADE_SQLSERVER_CONNECTION_STRING`
- Oracle: `ADE_ORACLE_USER`, `ADE_ORACLE_PASSWORD`, `ADE_ORACLE_DSN`
- ClickHouse: `ADE_CLICKHOUSE_HOST`, `ADE_CLICKHOUSE_USER`, `ADE_CLICKHOUSE_PASSWORD`
- Trino: `ADE_TRINO_HOST`, `ADE_TRINO_USER`, `ADE_TRINO_PORT`, `ADE_TRINO_CATALOG`, `ADE_TRINO_SCHEMA`, `ADE_TRINO_HTTP_SCHEME`
- MongoDB: `ADE_MONGODB_URI`, `ADE_MONGODB_DATABASE`
- BigQuery: `ADE_BIGQUERY_PROJECT` plus runtime Google credentials
- Databricks: `ADE_DATABRICKS_HOST`, `ADE_DATABRICKS_TOKEN`, `ADE_DATABRICKS_HTTP_PATH`, `ADE_DATABRICKS_CATALOG`
- SQLite: `ADE_SQLITE_DATABASE`

## Model providers

Registry variables:

- OpenAI `OPENAI_API_KEY`
- Anthropic `ANTHROPIC_API_KEY`
- OpenRouter `OPENROUTER_API_KEY`
- Gemini `GEMINI_API_KEY`
- Azure OpenAI `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_DEPLOYMENT`, optional `AZURE_OPENAI_API_VERSION`
- Vertex `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`, `GOOGLE_CLOUD_ACCESS_TOKEN`
- Bedrock AWS credential provider chain plus `AWS_REGION` or `AWS_DEFAULT_REGION`
- Groq `GROQ_API_KEY`
- Mistral `MISTRAL_API_KEY`
- Together `TOGETHER_API_KEY`
- xAI `XAI_API_KEY`
- DeepInfra `DEEPINFRA_API_KEY`
- NVIDIA `NVIDIA_API_KEY`
- Cerebras `CEREBRAS_API_KEY`
- Perplexity `PERPLEXITY_API_KEY`
- Vercel AI Gateway `AI_GATEWAY_API_KEY`
- Cohere `COHERE_API_KEY`, optional `COHERE_OPENAI_BASE_URL`
- Ollama optional `OLLAMA_BASE_URL`
- LM Studio optional `LM_STUDIO_BASE_URL`
- Databricks AI Gateway `DATABRICKS_AI_GATEWAY_URL`, `DATABRICKS_TOKEN`
- Snowflake Cortex `SNOWFLAKE_CORTEX_BASE_URL`, `SNOWFLAKE_CORTEX_TOKEN`
- authorized GitHub Copilot `GITHUB_COPILOT_TOKEN`, optional `GITHUB_COPILOT_BASE_URL`

Provider certification needs a model via `ADE_CERT_<PROVIDER>_MODEL` or fallback `ADE_CERT_MODEL`. The dedicated live agent harness uses `ADE_LIVE_AGENT_PROVIDER` and `ADE_LIVE_AGENT_MODEL`.

## Security

Never place real values in `.env.example`, docs, fixtures, snapshots, trace output, or CI logs. Credential-shaped fixtures must remain audit-safe rather than weakening scanners.
