export type QualityMapping = {
  mapping_id: string; source_asset_id: string; source_name: string; path_asset_ids: string[];
  orchestrator_asset_ids: string[]; target_asset_id: string; target_name: string;
  key_column: string | null; key_columns: string[]; key_inference: string; evidence: string;
};

export type QualityCheck = {
  check_id: string; mapping_id: string; name: string; category: string; executor: string | null;
  execution_support: "AVAILABLE" | "ADAPTER_REQUIRED"; severity: "INFO" | "WARNING" | "ERROR" | "CRITICAL";
  enabled: boolean; archived?: boolean; requires_review: boolean; provenance: string; evidence: string; params: Record<string, unknown>;
  contract?: Record<string, unknown>;
};

export type QualityPlan = {
  plan_id: string; project_id: string; environment: string; analysis_run_id: string; name: string;
  status: "DRAFT" | "APPROVED"; revision: number; created_at: string; updated_at: string;
  approved_at: string | null; approved_by: string | null; mappings: QualityMapping[]; checks: QualityCheck[];
  unmapped: { sources: Array<{ asset_id: string; name: string }>; targets: Array<{ asset_id: string; name: string }> };
  summary: Record<string, number>;
};

export type QualityPlanRun = {
  run_id: string; plan_id: string; plan_revision: number; status: string; started_at: string; completed_at: string;
  summary: { executed: number; status_counts: Record<string, number> };
  results: Array<{ check_id: string; name: string; category: string; status: string; result: Record<string, unknown> }>;
};

export type QualityPlanRunSummary = Omit<QualityPlanRun, "results"> & {
  result_count: number;
  status_counts: Record<string, number>;
  details_available: boolean;
};

export type QualityPlanRevision = {
  revision: number; status: string; event: string; changed_by: string; recorded_at: string;
  plan: QualityPlan;
};

export type QualitySchedule = {
  schedule_id: string; plan_id: string; trigger_type: "INTERVAL" | "EVENT";
  interval_minutes: number | null; event_name: string | null; status: "ACTIVE" | "PAUSED";
  next_run_at: string | null; last_run_at: string | null; created_by: string;
  created_at: string; updated_at: string;
};

export type QualityRunRequest = {
  request_id: string; plan_id: string; plan_revision: number; trigger_type: string; trigger_ref: string;
  status: string; attempt: number; max_attempts: number; timeout_seconds: number;
  cancel_requested: boolean; run_id: string | null; error: string | null;
  created_at: string; started_at: string | null; completed_at: string | null;
};

export type QualityPlanWorkspace = {
  plan: QualityPlan | null; capabilities: Record<string, unknown>; runs: QualityPlanRunSummary[];
  revisions: QualityPlanRevision[];
  schedules: QualitySchedule[]; requests: QualityRunRequest[];
  automationCapabilities: Record<string, unknown>;
  runPage?: number; runPageSize?: number; runTotal?: number; runHasNext?: boolean;
};
