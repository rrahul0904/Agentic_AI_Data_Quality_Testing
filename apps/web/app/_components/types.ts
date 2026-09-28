export type Availability = "AVAILABLE" | "UNAVAILABLE" | "UNKNOWN" | "PERMISSION_DENIED" | "UNSUPPORTED";

export type Evidence = {
  evidence_id: string;
  tier: string;
  kind: string;
  source: string;
  summary: string;
  payload: Record<string, unknown>;
  correlation?: Record<string, unknown>;
  created_at: string;
};

export type Lifecycle = {
  task_id: string;
  run_id: string;
  dag_id?: string | null;
  scheduled_at?: string | null;
  queued_at?: string | null;
  running_at?: string | null;
  operator_started_at?: string | null;
  ended_at?: string | null;
  metadata_state?: string | null;
  executor_state?: string | null;
  runtime_start_proven: boolean;
  operator_start_proven: boolean;
  task_log_exists?: boolean | null;
  queued_duration_seconds?: number | null;
  executor?: string | null;
  parallelism?: number | null;
  try_number?: number | null;
  evidence_ids: string[];
};

export type Divergence = {
  layer: string;
  component: string;
  expected_state: string;
  observed_state: string;
  occurred_at?: string | null;
  evidence_ids: string[];
  confidence: number;
  proven: boolean;
};

export type Finding = {
  finding_id: string;
  title: string;
  description: string;
  classification: string;
  domain: string;
  confidence: number;
  evidence_ids: string[];
  relationship: string;
  created_at: string;
};

export type Hypothesis = {
  hypothesis_id: string;
  name: string;
  statement: string;
  domain: string;
  status: string;
  confidence: number;
  supporting_evidence_ids: string[];
  contradictory_evidence_ids: string[];
  prerequisites_to_prove?: string[];
  prerequisites_to_disprove?: string[];
};

export type ProgressStep = { id: string; status: string; label: string; at: string; state: string };

export type Investigation = {
  incident_id: string;
  scenario_id: string;
  question: string;
  state: string;
  mode: string;
  anomaly: Record<string, unknown>;
  first_divergence?: string | null;
  structured_first_divergence?: Divergence | null;
  root_cause?: string | null;
  root_cause_confidence: number;
  findings: Finding[];
  hypotheses: Hypothesis[];
  evidence: Evidence[];
  execution_lifecycles: Lifecycle[];
  blast_radius: string[];
  transitions: { transition_id: string; to_state: string; reason: string; created_at: string }[];
  progress?: { state: string; steps: ProgressStep[] };
  remediation?: Record<string, unknown> | null;
  approved: boolean;
  certification: string;
  created_at?: string;
  updated_at?: string;
};

export type AirflowEvidence = {
  status: Availability;
  mode: string;
  reason?: string;
  dag_id: string | null;
  run_id: string | null;
  executor?: string | null;
  parallelism?: number | null;
  tasks: Lifecycle[];
};
