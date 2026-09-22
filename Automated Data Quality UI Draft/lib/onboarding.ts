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

export type PipelineLayer = "Sources" | "Ingestion" | "Transformation" | "Targets";

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
};

export type SelectedSourceTable = {
  id: string;
  database: string;
  schema: string;
  table: string;
  columns: Array<{ name: string; type?: string; nullable?: unknown }>;
};

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
