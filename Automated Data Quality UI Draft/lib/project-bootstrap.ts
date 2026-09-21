import { access, readFile, readdir } from "node:fs/promises";
import path from "node:path";

export type ConnectionEvidence = {
  id: "postgres" | "files" | "airflow" | "dbt" | "snowflake";
  system: string;
  status: string;
  source: string;
  lastVerified: string | null;
  evidence: "Observed" | "Parsed" | "Runtime unverified";
  detail: string;
};

export type DiscoveryEvidence = {
  id: ConnectionEvidence["id"];
  objectCount: number;
  summary: string;
  source: string;
  evidence: ConnectionEvidence["evidence"];
};

export type ProjectBootstrap = {
  generatedAt: string;
  canonicalRoot: string;
  apiBase: string | null;
  apiMode: string;
  project: {
    name: string;
    domain: string;
    environment: string;
    implementationState: string;
    dataPreset: string;
    referenceDate: string;
  };
  inventory: {
    csvFiles: number;
    parquetFiles: number;
    jsonFiles: number;
    totalSourceFiles: number;
    runtimeDbtModels: number;
    runtimeDbtTests: number;
    runtimeDbtSnapshots: number;
    runtimeAirflowDags: number;
    snowflakeSqlFiles: number;
    snowpipeDefinitions: number;
    postgresTables: number;
  };
  connections: ConnectionEvidence[];
  discovery: DiscoveryEvidence[];
  execution: {
    dbt: string;
    airflowLineage: string;
    endToEnd: string;
  };
  warnings: string[];
};

const DEFAULT_ROOT = "/Users/297159/Documents/Agentic_AI/Automated Data Quality Testing";

export function extractYamlScalar(content: string, key: string): string | null {
  const match = content.match(new RegExp(`^\\s*${key}:\\s*["']?([^"'\\n#]+)`, "m"));
  return match?.[1]?.trim() ?? null;
}

async function countFiles(directory: string, extension: string): Promise<number> {
  try {
    const entries = await readdir(directory, { withFileTypes: true });
    const counts = await Promise.all(entries.map(async (entry) => {
      const entryPath = path.join(directory, entry.name);
      if (entry.isDirectory()) return countFiles(entryPath, extension);
      return entry.isFile() && entry.name.toLowerCase().endsWith(extension) ? 1 : 0;
    }));
    return counts.reduce((sum, count) => sum + count, 0);
  } catch {
    return 0;
  }
}

export async function collectLocalInventory(canonicalRoot = DEFAULT_ROOT) {
  const sourceDir = path.join(canonicalRoot, "data/hospitality");
  const [csvFiles, parquetFiles, jsonFiles, runtimeDbtModels, runtimeAirflowDags, snowflakeSqlFiles, snowpipeDefinitions] = await Promise.all([
    countFiles(sourceDir, ".csv"),
    countFiles(sourceDir, ".parquet"),
    countFiles(sourceDir, ".json"),
    countFiles(path.join(canonicalRoot, "runtime/hospitality-data-reliability-lab/dbt/models"), ".sql"),
    countFiles(path.join(canonicalRoot, "runtime/hospitality-data-reliability-lab/airflow/dags"), ".py"),
    countFiles(path.join(canonicalRoot, "snowflake/testbed"), ".sql"),
    countFiles(path.join(canonicalRoot, "snowflake/testbed/pipes"), ".sql"),
  ]);
  return { csvFiles, parquetFiles, jsonFiles, totalSourceFiles: csvFiles + parquetFiles + jsonFiles, runtimeDbtModels, runtimeAirflowDags, snowflakeSqlFiles, snowpipeDefinitions };
}

async function fetchJson(base: string, endpoint: string, timeoutMs = 5000): Promise<Record<string, unknown> | null> {
  try {
    const response = await fetch(`${base}${endpoint}`, { cache: "no-store", signal: AbortSignal.timeout(timeoutMs) });
    if (!response.ok) return null;
    return await response.json() as Record<string, unknown>;
  } catch {
    return null;
  }
}

async function resolveApiBase(candidates: string[]): Promise<string | null> {
  for (const candidate of candidates) {
    if (await fetchJson(candidate, "/api/v1/overview", 2000)) return candidate;
  }
  return null;
}

function stringValue(value: unknown, fallback = "Unknown"): string {
  return typeof value === "string" && value ? value : fallback;
}

function numberValue(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

export async function collectProjectBootstrap(options: { canonicalRoot?: string; apiCandidates?: string[] } = {}): Promise<ProjectBootstrap> {
  const canonicalRoot = options.canonicalRoot ?? process.env.ADE_CANONICAL_PROJECT_ROOT ?? DEFAULT_ROOT;
  await access(canonicalRoot);
  const configText = await readFile(path.join(canonicalRoot, "config/hospitality_testbed.yml"), "utf8");
  const local = await collectLocalInventory(canonicalRoot);
  const candidates = options.apiCandidates ?? [process.env.ADE_API_BASE_URL, "http://127.0.0.1:8011", "http://127.0.0.1:8001"].filter((value): value is string => Boolean(value));
  const apiBase = await resolveApiBase(candidates);

  const [overview, postgresStatus, postgresMetadata, airflowStatus, airflowMetadata, dbtStatus, dbtState, snowflakeStatus, snowflakeInventory] = apiBase ? await Promise.all([
    fetchJson(apiBase, "/api/v1/overview"),
    fetchJson(apiBase, "/api/v1/connections/postgres/status"),
    fetchJson(apiBase, "/api/v1/connections/postgres/metadata"),
    fetchJson(apiBase, "/api/v1/connections/airflow/status"),
    fetchJson(apiBase, "/api/v1/connections/airflow/metadata"),
    fetchJson(apiBase, "/api/v1/connections/dbt/status"),
    fetchJson(apiBase, "/api/v1/connections/dbt/state"),
    fetchJson(apiBase, "/api/v1/connections/snowflake/status", 8000),
    fetchJson(apiBase, "/api/v1/snowflake/live-inventory", 12000),
  ]) : [null, null, null, null, null, null, null, null, null];

  const overviewCounts = overview?.counts as Record<string, unknown> | undefined;
  const dbtResources = dbtState?.resource_counts as Record<string, unknown> | undefined;
  const dbtExecution = dbtState?.latest_execution as Record<string, unknown> | undefined;
  const airflowDags = Array.isArray(airflowMetadata?.dags) ? airflowMetadata.dags.length : local.runtimeAirflowDags;
  const postgresTables = numberValue(postgresMetadata?.object_count);
  const dbtModels = numberValue(dbtResources?.model, numberValue(overviewCounts?.dbt_models, local.runtimeDbtModels));
  const dbtTests = numberValue(dbtResources?.test, numberValue(overviewCounts?.dbt_tests));
  const dbtSnapshots = numberValue(dbtResources?.snapshot, numberValue(overviewCounts?.dbt_snapshots));
  const snowflakeObjects = numberValue(snowflakeInventory?.object_count);

  const statusEvidence = (payload: Record<string, unknown> | null): ConnectionEvidence["evidence"] => payload?.status === "CONNECTED" ? "Observed" : "Runtime unverified";
  const lastVerified = (payload: Record<string, unknown> | null) => typeof payload?.last_verified === "string" ? payload.last_verified : null;
  const status = (payload: Record<string, unknown> | null) => stringValue(payload?.status, apiBase ? "UNAVAILABLE" : "API_OFFLINE");

  const connections: ConnectionEvidence[] = [
    { id: "postgres", system: "PostgreSQL", status: status(postgresStatus), source: stringValue(postgresStatus?.source, "ADE connection registry"), lastVerified: lastVerified(postgresStatus), evidence: statusEvidence(postgresStatus), detail: postgresTables ? `${postgresTables} live tables visible` : "No live table inventory returned" },
    { id: "files", system: "Files / object storage", status: local.totalSourceFiles ? "AVAILABLE" : "UNAVAILABLE", source: "Canonical data/hospitality filesystem", lastVerified: new Date().toISOString(), evidence: local.totalSourceFiles ? "Parsed" : "Runtime unverified", detail: `${local.csvFiles} CSV, ${local.parquetFiles} Parquet, ${local.jsonFiles} JSON` },
    { id: "airflow", system: "Apache Airflow", status: status(airflowStatus), source: stringValue(airflowStatus?.source, "ADE Airflow adapter"), lastVerified: lastVerified(airflowStatus), evidence: statusEvidence(airflowStatus), detail: `${airflowDags} DAGs discovered; connection health does not prove execution` },
    { id: "dbt", system: "dbt", status: status(dbtStatus), source: stringValue(dbtStatus?.source, "dbt artifacts"), lastVerified: lastVerified(dbtStatus), evidence: "Parsed", detail: `${dbtModels} models, ${dbtTests} tests; ${stringValue(dbtStatus?.execution_status, "execution unknown")}` },
    { id: "snowflake", system: "Snowflake", status: status(snowflakeStatus), source: stringValue(snowflakeStatus?.source, "ADE Snowflake adapter"), lastVerified: lastVerified(snowflakeStatus), evidence: statusEvidence(snowflakeStatus), detail: snowflakeObjects ? `${snowflakeObjects} live catalog objects; ${local.snowpipeDefinitions} Snowpipe definitions parsed` : "Live catalog unavailable" },
  ];

  const warnings = [
    ...(apiBase ? [] : ["ADE API is offline; live connection evidence is unavailable."]),
    ...(stringValue(dbtStatus?.execution_status, "NOT_RUN_OR_NO_RUN_RESULTS") === "NOT_RUN_OR_NO_RUN_RESULTS" ? ["dbt project parsed successfully, but no run_results.json proves execution."] : []),
    "Connection health proves reachability only; it does not prove end-to-end lineage or data correctness.",
  ];

  return {
    generatedAt: new Date().toISOString(), canonicalRoot,
    apiBase,
    apiMode: stringValue(overview?.mode, apiBase ? "CONNECTED" : "OFFLINE"),
    project: {
      name: "Hospitality Data Reliability",
      domain: "Hospitality Analytics",
      environment: "Development",
      implementationState: "First end-to-end run pending",
      dataPreset: extractYamlScalar(configText, "preset") ?? "unknown",
      referenceDate: extractYamlScalar(configText, "reference_date") ?? "unknown",
    },
    inventory: { ...local, runtimeDbtTests: dbtTests, runtimeDbtSnapshots: dbtSnapshots, runtimeAirflowDags: airflowDags, runtimeDbtModels: dbtModels, postgresTables },
    connections,
    discovery: [
      { id: "postgres", objectCount: postgresTables, summary: `${postgresTables} tables returned by live information_schema discovery`, source: "PostgreSQL information_schema", evidence: postgresTables ? "Observed" : "Runtime unverified" },
      { id: "files", objectCount: local.totalSourceFiles, summary: `${local.csvFiles} CSV + ${local.parquetFiles} Parquet + ${local.jsonFiles} JSON`, source: "Canonical data/hospitality", evidence: "Parsed" },
      { id: "airflow", objectCount: airflowDags, summary: `${airflowDags} DAGs returned by Airflow metadata/code inventory`, source: airflowMetadata ? "Airflow API" : "Canonical DAG directory", evidence: airflowMetadata ? "Observed" : "Parsed" },
      { id: "dbt", objectCount: dbtModels, summary: `${dbtModels} models + ${dbtTests} tests + ${dbtSnapshots} snapshots`, source: "dbt manifest.json", evidence: "Parsed" },
      { id: "snowflake", objectCount: snowflakeObjects, summary: snowflakeObjects ? `${snowflakeObjects} tables/views returned by the live Snowflake catalog` : "Live Snowflake catalog returned no objects", source: snowflakeObjects ? "Snowflake information_schema" : "Live Snowflake catalog unavailable", evidence: snowflakeObjects ? "Observed" : "Runtime unverified" },
    ],
    execution: {
      dbt: stringValue(dbtExecution?.status, stringValue(dbtStatus?.execution_status, "NOT_RUN")),
      airflowLineage: "WAITING_FOR_VERIFIED_PIPELINE_RUN",
      endToEnd: "NOT_RUN",
    },
    warnings,
  };
}
