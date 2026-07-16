export type StudyStatus =
  | "DRAFT"
  | "PROTOCOL_REVIEW"
  | "FEASIBILITY_RUNNING"
  | "FEASIBILITY_REVIEW"
  | "CONTRACT_LOCKED"
  | "TRAINING_RUNNING"
  | "RESULTS_REVIEW"
  | "PRIVACY_REVIEW"
  | "REPORT_READY"
  | "ARCHIVED"
  | "FAILED_RETRYABLE"
  | "FAILED_FINAL"
  | "BLOCKED_BY_POLICY";

export interface Protocol {
  title: string;
  hypothesis: string;
  modalities: string[];
  inclusion_criteria: string[];
  primary_endpoint: string;
  guardrail_metrics: string[];
  limitations: string[];
  source: string;
}

export interface PolicyDecision {
  result: string;
  rule: string;
  blocked_fields: string[];
}

export interface SiteSummary {
  site_id: string;
  sample_count: number;
  usable_count: number;
  missing_modality_rate: number;
  label_completeness: number;
  spacing_summary: string;
  age_buckets: Record<string, number | string>;
  quality_flags: string[];
}

export interface Study {
  id: string;
  title: string;
  research_question: string;
  disease_area: string;
  status: StudyStatus;
  protocol: Protocol | null;
  feasibility: {
    mode: string;
    sites: SiteSummary[];
    policy_decisions: PolicyDecision[];
    total_usable_count: number;
    finding: string;
  } | null;
  contract: Record<string, unknown> | null;
  review_markdown: string | null;
  report_markdown: string | null;
  created_at: string;
  updated_at: string;
}

export interface SiteMetric {
  site_id: string;
  dice: number;
  hd95: number;
}

export interface Experiment {
  id: string;
  strategy: string;
  hypothesis: string;
  status: "PENDING" | "RUNNING" | "COMPLETED" | "FAILED";
  metrics: {
    mean_dice: number;
    worst_site_dice: number;
    site_dice_std: number;
    hd95: number;
    sites: SiteMetric[];
  } | null;
}

export interface AuditEvent {
  id: string;
  event_type: string;
  actor: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface AgentArtifact {
  id: string;
  role: string;
  artifact_type: string;
  content: Record<string, unknown>;
  source: string;
  created_at: string;
}

export interface EvidenceBrief {
  leading_strategy: string;
  recommendation: string;
  evidence: string[];
  fairness_findings: string[];
  limitations: string[];
  source: string;
}

export interface TrainingJob {
  id: string;
  experiment_id: string;
  strategy: string;
  backend: string;
  status: "QUEUED" | "RUNNING" | "COMPLETED" | "FAILED";
  progress: number;
  message: string;
  workspace: string | null;
  log_path: string | null;
  global_model_path: string | null;
  error: string | null;
}

export interface Capabilities {
  app_version: string;
  environment: string;
  federation_mode: string;
  step_mode: string;
  gpu_available: boolean;
  monai_available: boolean;
  nvflare_available: boolean;
}

export interface ImagingModality {
  name: string;
  pixels: number[][];
}

export interface ImagingPreview {
  dataset_id: string;
  site_id: string;
  case_id: string;
  synthetic: boolean;
  sent_to_llm: boolean;
  slice_index: number;
  shape: [number, number];
  spacing: number[] | null;
  label_pixels: number[][];
  modalities: ImagingModality[];
}

interface RepeatedMetricSummary {
  n: number;
  mean: number;
  std: number;
  ci95: [number, number];
}

export interface SystemEvidence {
  repeated_benchmark: {
    complete: boolean;
    seeds: number[];
    trial_count: number;
    worst_site_win_rate: Record<string, number>;
    strategy_summaries: Record<string, {
      trial_count: number;
      metrics: {
        mean_dice: RepeatedMetricSummary;
        worst_site_dice: RepeatedMetricSummary;
      };
    }>;
    interpretation_boundary: string;
  } | null;
  mtls_provisioning: {
    connection_security: string;
    shared_root_ca: boolean;
    participant_count: number;
  } | null;
  mtls_runtime: {
    server_started: boolean;
    registered_client_count: number;
    connection_security: string;
    sensitive_runtime_tokens_included: boolean;
  } | null;
  privacy_comparison: {
    mechanism: string;
    epsilon_parameter_per_call: number;
    fraction_shared: number;
    accounting_scope: string;
    end_to_end_sample_dp_claimed: boolean;
  } | null;
}
