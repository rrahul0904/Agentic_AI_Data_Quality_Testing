export type ConnectionKind = "postgres" | "snowflake" | "airflow" | "dbt" | "files";

export type ConnectionProfile = {
  id: string;
  name: string;
  kind: ConnectionKind;
  environment: string;
  source: "manual" | "runtime";
  enabled: boolean;
  config: Record<string, string | number | boolean>;
  updatedAt: string;
};

export type ConnectionTestResult = {
  status: "PASS" | "FAIL" | "UNVERIFIED";
  detail: string;
  source: string;
  testedAt: string;
  metadata?: Record<string, unknown>;
};

export type PipelineLayer = "Sources" | "Ingestion" | "Transformation" | "Targets" | "Quality / other";

export type DiscoveredChildAsset = {
  id: string;
  name: string;
  type: "Column" | "Airflow task";
  detail?: string;
};

export type AssetEvidence = {
  source: string;
  collectedAt: string;
  collectionMethod: string;
  classification: "LIVE_RUNTIME" | "GENERATED_ARTIFACT" | "FILESYSTEM";
  confidence: "HIGH" | "MEDIUM" | "LOW";
  location: string;
};

export type DiscoveredAsset = {
  id: string;
  connectionId: string;
  catalog?: string;
  schema?: string;
  name: string;
  type: string;
  detail?: string;
  metadata?: {
    primaryKeys?: Array<{ column: string; constraint: string }>;
    foreignKeys?: Array<{
      column: string;
      constraint: string;
      referencedSchema: string;
      referencedTable: string;
      referencedColumn: string;
    }>;
  };
  children?: DiscoveredChildAsset[];
  proposedLayer?: PipelineLayer;
  roleStatus?: "PROPOSED";
  evidence?: AssetEvidence;
};

export type DiscoveryCategory = {
  id: string;
  label: string;
  status: "OBSERVED" | "EMPTY" | "UNAVAILABLE";
  count?: number;
  detail: string;
};

export type DiscoveryResult = {
  status: "PASS" | "FAIL" | "UNVERIFIED";
  detail: string;
  source: string;
  collectionMethod?: string;
  discoveredAt: string;
  assets: DiscoveredAsset[];
  categories?: DiscoveryCategory[];
  sourceTableId?: string;
  /** Version of the discovery contract used to produce this persisted result. */
  discoveryVersion?: number;
};

/** Version 2 explicitly includes reachable dbt test resources in table scope. */
export const DBT_DISCOVERY_VERSION = 2;

export function dbtDiscoveryNeedsRefresh(result: Pick<DiscoveryResult, "status" | "discoveryVersion"> | undefined): boolean {
  return result?.status === "PASS" && result.discoveryVersion !== DBT_DISCOVERY_VERSION;
}

export type SelectedSourceTable = {
  id: string;
  database: string;
  schema: string;
  table: string;
  columns: Array<{ name: string; type?: string; nullable?: unknown }>;
};

export type DbtLineageResource = {
  unique_id?: string;
  name?: string;
  resource_type?: string;
  database?: string;
  schema?: string;
  depends_on?: { nodes?: unknown[] };
};

export function isPostgresSourceTableAsset(
  asset: { catalog?: string; schema?: string; name?: string },
  sourceTable: Pick<SelectedSourceTable, "database" | "schema" | "table">,
): boolean {
  return (asset.catalog ?? "") === sourceTable.database
    && (asset.schema ?? "") === sourceTable.schema
    && (asset.name ?? "") === sourceTable.table;
}

/** Match the actual task-group identity in a discovered DAG; never fuzzy-match its DAG name. */
export function airflowDagLoadsSourceTable(taskNames: string[], tableName: string): boolean {
  const taskGroupPrefix = `load_${tableName.trim().toLowerCase()}.`;
  return Boolean(tableName.trim()) && taskNames.some((taskName) => taskName.trim().toLowerCase().startsWith(taskGroupPrefix));
}

/** An ingestion target must be the exact configured database's raw base table. */
export function isSnowflakeRawTargetForSourceTable(
  asset: { catalog?: string; schema?: string; name?: string; type?: string },
  tableName: string,
  configuredDatabase: string,
): boolean {
  return Boolean(tableName.trim() && configuredDatabase.trim())
    && (asset.name ?? "").trim().toLowerCase() === tableName.trim().toLowerCase()
    && (asset.catalog ?? "").trim().toLowerCase() === configuredDatabase.trim().toLowerCase()
    && (asset.schema ?? "").trim().toLowerCase() === "raw"
    && ["base table", "table"].includes((asset.type ?? "").trim().toLowerCase());
}

/**
 * Return dbt models and tests reachable from the exact source node for a
 * selected PostgreSQL table. The manifest dependency graph is authoritative;
 * substring/name similarity is intentionally not used, so `guests` cannot
 * select `reservation_guests` by name alone. Tests stay definitions here,
 * not execution results.
 */
export function dbtResourceIdsForSourceTable(resources: DbtLineageResource[], tableName: string, targetDatabases: string[]): Set<string> {
  const exactName = tableName.trim().toLowerCase();
  const expectedDatabases = new Set(targetDatabases.map((database) => database.trim().toLowerCase()).filter(Boolean));
  if (!exactName || !expectedDatabases.size) return new Set();

  const sourceIds = resources.flatMap((resource) =>
    resource.resource_type === "source"
      && resource.name?.trim().toLowerCase() === exactName
      && resource.schema?.trim().toLowerCase() === "raw"
      && expectedDatabases.has(resource.database?.trim().toLowerCase() ?? "")
      && resource.unique_id
      ? [resource.unique_id]
      : [],
  );
  // Duplicate source declarations with the same relation name are ambiguous:
  // return no matches rather than combining their lineages.
  if (sourceIds.length !== 1) return new Set();
  const related = new Set(sourceIds);

  let changed = true;
  while (changed) {
    changed = false;
    for (const resource of resources) {
      const id = resource.unique_id;
      if (!id || related.has(id)) continue;
      const dependencies = Array.isArray(resource.depends_on?.nodes) ? resource.depends_on.nodes : [];
      if (dependencies.some((dependency) => typeof dependency === "string" && related.has(dependency))) {
        related.add(id);
        changed = true;
      }
    }
  }
  return new Set(resources.flatMap((resource) =>
    ["model", "test"].includes(resource.resource_type ?? "") && resource.unique_id && related.has(resource.unique_id)
      ? [resource.unique_id]
      : [],
  ));
}

export type OnboardingBootstrap = {
  project: { name: string; domain: string; environment: string; root: string };
  savedConnections: ConnectionProfile[];
  suggestedConnections: ConnectionProfile[];
  savedTests: Record<string, ConnectionTestResult>;
  liveConnectionChecks?: Record<string, ConnectionTestResult>;
  savedDiscoveries: Record<string, DiscoveryResult>;
  selectedAssets: string[];
  selectedSourceTable?: SelectedSourceTable;
  selectedSourceTables?: SelectedSourceTable[];
  savedDiscoveriesByTable?: Record<string, Record<string, DiscoveryResult>>;
  sourceTableScopeId?: string;
  analysisScopeId?: string;
  qualityPlanScopeId?: string;
  scopeWarning?: string;
  projectDefinition?: Record<string, string>;
  projectSavedAt?: string;
  currentProjectId?: string;
  projects?: Array<{ id: string; projectDefinition: Record<string, string>; projectSavedAt?: string; createdAt: string }>;
};

export function validateDiscoveryEvidence(result: DiscoveryResult, connectionId: string): DiscoveryResult {
  if (result.status !== "PASS") return result;
  for (const asset of result.assets) {
    if (!asset.id || !asset.name.trim() || !asset.type.trim()) throw new Error("Discovery returned an asset without an identity, name or type");
    if (asset.connectionId !== connectionId) throw new Error(`Discovery asset ${asset.id} is not bound to the tested connection`);
    if (!asset.proposedLayer || asset.roleStatus !== "PROPOSED") throw new Error(`Discovery asset ${asset.id} is missing its proposed pipeline placement`);
    const evidence = asset.evidence;
    if (!evidence?.source || !evidence.collectedAt || !evidence.collectionMethod || !evidence.classification || !evidence.confidence || !evidence.location) {
      throw new Error(`Discovery asset ${asset.id} is missing required evidence`);
    }
    if (Number.isNaN(Date.parse(evidence.collectedAt))) throw new Error(`Discovery asset ${asset.id} has an invalid evidence timestamp`);
  }
  return result;
}

export const connectionLabels: Record<ConnectionKind, string> = {
  postgres: "PostgreSQL",
  snowflake: "Snowflake",
  airflow: "Apache Airflow",
  dbt: "dbt Core project",
  files: "Files / object storage",
};

const ENV_NAME = /^[A-Za-z_][A-Za-z0-9_]*$/;

export function validateConnectionProfile(profile: ConnectionProfile): ConnectionProfile {
  if (!profile.id || !profile.name.trim()) throw new Error("Connection name is required");
  if ((profile.kind === "postgres" || profile.kind === "snowflake") && !profile.config.authMethod) throw new Error("Authentication method is required");
  for (const [key, item] of Object.entries(profile.config)) {
    if (/password|token|secret|privatekey|dsn/i.test(key)) {
      if (!key.toLowerCase().endsWith("env")) throw new Error(`Raw secret field ${key} is not allowed`);
      if (item && !ENV_NAME.test(String(item))) throw new Error(`${key} must contain an environment-variable name, not a secret value`);
    }
  }
  return { ...profile, name: profile.name.trim(), updatedAt: new Date().toISOString() };
}

export function newConnection(kind: ConnectionKind): ConnectionProfile {
  const id = globalThis.crypto?.randomUUID?.() ?? `${kind}-${Date.now()}`;
  const defaults: Record<ConnectionKind, ConnectionProfile["config"]> = {
    postgres: { authMethod: "DSN / connection URL", host: "", port: 5432, database: "", user: "", dsnEnv: "ADE_POSTGRES_DSN", sslMode: "prefer", schemas: "public" },
    snowflake: { authMethod: "Username + password", account: "", user: "", database: "", schema: "", warehouse: "", role: "", passwordEnv: "ADE_SNOWFLAKE_PASSWORD" },
    airflow: { baseUrl: "", version: "", authMethod: "basic_or_token", username: "", passwordEnv: "ADE_AIRFLOW_PASSWORD", tokenEnv: "ADE_AIRFLOW_TOKEN", dagPattern: "*" },
    dbt: { projectDir: "", profilesPath: "", target: "dev", dbtExecutable: "", manifestPath: "", runResultsPath: "" },
    files: { storageType: "local", rootPath: "", includePattern: "**/*.{csv,parquet,json}", recursive: true },
  };
  return { id, name: `New ${connectionLabels[kind]} connection`, kind, environment: "Development", source: "manual", enabled: true, config: defaults[kind], updatedAt: new Date().toISOString() };
}
