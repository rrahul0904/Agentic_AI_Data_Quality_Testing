export type AnalysisNode = {
  node_id: string;
  kind: string;
  name: string;
  properties: Record<string, unknown>;
};

export type AnalysisEdge = {
  edge_id: string;
  source_id: string;
  target_id: string;
  edge_type: string;
  properties: Record<string, unknown>;
};

export type AssetClassification = {
  asset_id: string;
  roles: string[];
  confidence: number;
  source: "DETERMINISTIC" | "OPENAI" | "USER";
  evidence_ids: string[];
  rationale: string;
  requires_review: boolean;
  status: "DETERMINISTIC" | "DETERMINISTIC_PROPOSED" | "AI_PROPOSED";
  lineage_state?: "PLANNED" | "OBSERVED" | "AI_REVIEWED";
  runtime_status?: string;
  runtime_started_at?: string | null;
  runtime_completed_at?: string | null;
  runtime_evidence_ids?: string[];
};

export type RelationshipClassification = {
  edge_id: string;
  source_asset_id: string;
  target_asset_id: string;
  relationship: string;
  confidence: number;
  source: "DETERMINISTIC" | "OPENAI" | "USER";
  evidence_ids: string[];
  rationale: string;
  requires_review: boolean;
  status: "DETERMINISTIC" | "DETERMINISTIC_PROPOSED" | "AI_PROPOSED";
  pipeline_ids: string[];
  lineage_state?: "PLANNED" | "OBSERVED" | "AI_REVIEWED";
  runtime_status?: string;
  runtime_started_at?: string | null;
  runtime_completed_at?: string | null;
  runtime_evidence_ids?: string[];
};

export type AnalysisEvidence = {
  evidence_id: string;
  kind: string;
  source: string;
  maturity: "PLANNED" | "DECLARED" | "OBSERVED" | "VERIFIED";
  payload: Record<string, unknown>;
  observed_at: string;
};

export type AnalyzerRun = { analyzer_id: string; name: string; status: string; facts: number; detail: string };
export type AnalysisPipeline = { pipeline_id: string; name: string; root_asset_ids: string[]; node_ids: string[]; edge_ids: string[]; status: string; requires_review: boolean; technology_kinds: string[] };
export type RuntimeSystem = { status: string; started_at?: string | null; completed_at?: string | null; evidence_id?: string };
export type RuntimeSummary = { status: string; refreshed_at?: string | null; lineage_state: string; systems: Record<string, RuntimeSystem>; observed_edge_count: number; observed_node_count: number; note?: string };
export type AILineageReview = {
  review_id: string;
  analysis_run_id: string;
  scope: string;
  created_at: string;
  status: string;
  reason?: string;
  model?: string;
  provider?: string;
  prompt_version?: string;
  latency_ms?: number;
  validation?: { status?: string; contract?: string; citations?: string; scope?: string; execution_authority?: string; reason?: string };
  evidence_state?: string;
  outcome?: string;
  uncertainty?: string;
  next_action?: string;
  answer?: { outcome?: string; evidence?: Array<{ evidence_id?: string; href?: string }>; uncertainty?: string; next_action?: string };
  subjects_requested: number;
  evidence_links?: Array<{ evidence_id?: string; href?: string }>;
  reviews: Array<{ subject_id: string; confidence: number; model_confidence?: number; confidence_basis?: string; reasoning: string; conflicts: string[]; evidence_ids: string[]; evidence_links?: Array<{ evidence_id?: string; href?: string }>; needs_human_approval: boolean }>;
};

export type ProjectAnalysisReport = {
  run_id: string;
  project_id: string;
  environment: string;
  status: string;
  created_at: string;
  graph: { nodes: AnalysisNode[]; edges: AnalysisEdge[]; node_types: Record<string, number>; edge_types: Record<string, number> };
  evidence: AnalysisEvidence[];
  asset_classifications: AssetClassification[];
  relationship_classifications: RelationshipClassification[];
  exceptions: Array<{ exception_id: string; exception_type: string; subject_id: string; reason: string }>;
  agent: Record<string, unknown>;
  analyzers: AnalyzerRun[];
  pipelines: AnalysisPipeline[];
  summary: { assets: number; relationships: number; classified_assets: number; classified_relationships: number; exceptions: number; ai_status: string; top_level_assets: number; child_assets: number; pipelines: number };
  runtime?: RuntimeSummary;
};

export type AssetDecision = { role: string; status: "USER_VERIFIED" | "REJECTED"; updated_at: string; note?: string; evidence_ids?: string[] };
export type RelationshipDecision = { relationship: string; status: "USER_VERIFIED" | "REJECTED"; updated_at: string; note?: string; evidence_ids?: string[]; source_asset_id?: string; target_asset_id?: string; user_created?: boolean };
export type AnalysisDecisions = { assets: Record<string, AssetDecision>; relationships: Record<string, RelationshipDecision> };

export type ProjectAnalysisWorkspace = {
  report: ProjectAnalysisReport | null;
  capabilities: Record<string, unknown>;
  decisions: AnalysisDecisions;
  ai_review?: AILineageReview | null;
};
