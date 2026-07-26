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
  organization_id: string;
  created_by: string;
  participating_sites: string[];
  revision: number;
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

export interface StudySiteMembership {
  id: string;
  study_id: string;
  site_id: string;
  display_name: string;
  organization: string;
  status: "INVITED" | "ACTIVE" | "PAUSED" | "WITHDRAWN";
  data_use_approved: boolean;
  certificate_bound: boolean;
  dataset_fingerprint: string | null;
  invited_by: string;
  activated_by: string | null;
  created_at: string;
  updated_at: string;
  activated_at: string | null;
  withdrawn_at: string | null;
  contains_patient_data: false;
  local_path_exported: false;
}

export interface RegisteredModelVersion {
  id: string;
  study_id: string;
  name: string;
  semantic_version: string;
  model_family: string;
  artifact_sha256: string;
  source_job_id: string | null;
  evidence_package_id: string | null;
  validation_tier: "L1_CODE" | "L2_ISOLATED" | "L3_PHYSICAL" | "L4_HOSPITAL";
  status:
    | "CANDIDATE"
    | "STATISTICAL_REVIEW"
    | "SECURITY_REVIEW"
    | "APPROVED"
    | "RELEASED"
    | "REVOKED";
  metrics: Record<string, unknown>;
  signature_present: boolean;
  signing_key_fingerprint_sha256: string | null;
  created_by: string;
  approved_by: string | null;
  released_by: string | null;
  revoked_by: string | null;
  created_at: string;
  updated_at: string;
  approved_at: string | null;
  released_at: string | null;
  revoked_at: string | null;
  model_binary_exported: false;
  contains_patient_data: false;
}

export interface RegisteredEvidencePackage {
  id: string;
  study_id: string;
  package_sha256: string;
  manifest_sha256: string;
  model_sha256: string;
  signing_key_fingerprint_sha256: string;
  signature_present: boolean;
  validation_tier: "L1_CODE" | "L2_ISOLATED" | "L3_PHYSICAL" | "L4_HOSPITAL";
  status: "REGISTERED" | "VERIFIED" | "RELEASED" | "REVOKED";
  site_count: number;
  required_quorum: number;
  gates: {
    quorum: boolean;
    privacy: boolean;
    security: boolean;
    dual_approval: boolean;
    no_sensitive_data: boolean;
  };
  verifier_version: string;
  registered_by: string;
  verified_by: string | null;
  released_by: string | null;
  revoked_by: string | null;
  created_at: string;
  updated_at: string;
  verified_at: string | null;
  released_at: string | null;
  revoked_at: string | null;
  contains_patient_data: false;
  private_key_exported: false;
  signature_exported: false;
}

export interface ResearchOperationsSummary {
  schema_version: "rarelink-research-operations-summary-v1";
  organization_id: string | null;
  studies: { total: number; by_status: Record<string, number> };
  sites: { total: number; by_status: Record<string, number> };
  models: { total: number; by_status: Record<string, number> };
  evidence_packages: { total: number; by_status: Record<string, number> };
  alerts: {
    sites_paused_or_withdrawn: number;
    models_waiting_for_review: number;
    evidence_waiting_for_verification: number;
  };
  contains_patient_data: false;
  contains_secret: false;
  local_paths_exported: false;
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

export interface PhysicalSite {
  deployment_mode: "disabled" | "isolated-integration" | "physical";
  site_id: string;
  display_name: string;
  organization: string;
  expected: boolean;
  status: "UNKNOWN" | "READY" | "DEGRADED" | "OFFLINE" | "TRAINING";
  certificate_status: string;
  data_ready: boolean;
  gpu_ready: boolean;
  monai_ready: boolean;
  nvflare_ready: boolean;
  current_job_id: string | null;
  current_round: number;
  total_rounds: number;
  free_memory_percent: number | null;
  free_disk_percent: number | null;
  dataset_fingerprint: string | null;
  receipt_sha256: string | null;
  last_heartbeat_at: string | null;
  contains_patient_data: false;
}

export interface PhysicalFederationJob {
  deployment_mode: "disabled" | "isolated-integration" | "physical";
  id: string;
  study_id: string | null;
  external_job_id: string | null;
  strategy: "fedavg" | "fedprox" | "fedavg_dpsgd";
  status:
    | "DRAFT"
    | "APPROVAL_PENDING"
    | "SUBMITTED"
    | "WAITING_FOR_SITES"
    | "RUNNING"
    | "COMPLETED"
    | "READY_FOR_REVIEW"
    | "FAILED"
    | "ABORTED";
  contract_sha256: string | null;
  expected_sites: string[];
  dataset_fingerprints: Record<string, string>;
  connected_sites: string[];
  total_rounds: number;
  local_epochs: number;
  current_round: number;
  received_updates: number;
  quorum_required: number;
  approval_count: number;
  approval_required: number;
  approval_state: string;
  approval_valid: boolean;
  approval_expires_at: string | null;
  approval_revoked_at: string | null;
  global_model_sha256: string | null;
  model_release: {
    manifest_sha256: string;
    key_fingerprint_sha256: string;
    signature: string;
    released_at: string;
    algorithm: "Ed25519";
  } | null;
  metrics: Record<string, unknown> | null;
  error: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  contains_patient_data: false;
}

export interface PhysicalAuditSummary {
  schema_version: string;
  verified: boolean;
  event_count: number;
  head_event_hash: string | null;
  head_algorithm: string | null;
  updated_at: string | null;
  events_exported: false;
  actors_exported: false;
  contains_patient_data: false;
}

export interface PhysicalReviewReadiness {
  schema_version: string;
  job_id: string;
  external_job_id: string | null;
  review_status: "READY_FOR_REVIEW" | "BLOCKED";
  ready: boolean;
  gates: Record<string, boolean>;
  unmet_gates: string[];
  model_path_exported: false;
  secret_exported: false;
  patient_data_exported: false;
}

export interface Capabilities {
  app_version: string;
  environment: string;
  federation_mode: string;
  step_mode: string;
  gpu_available: boolean;
  monai_available: boolean;
  nvflare_available: boolean;
  agent_backend: string;
  local_inference_configured: boolean;
  local_inference_available: boolean;
  local_inference_model: string | null;
  local_inference_endpoint: string | null;
  local_inference_boundary: string;
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
  cross_device_mtls: {
    same_physical_device: boolean;
    connection_security: string;
    registration: {
      reconnect_succeeded: boolean;
      successful_registration_count: number;
    };
    negative_control: {
      wrong_identity_rejected: boolean;
      reason_category: string;
    };
  } | null;
  agent_redteam: {
    case_count: number;
    passed_count: number;
    pass_rate: number;
    all_passed: boolean;
    enforcement: string;
  } | null;
  public_benchmark: {
    dataset_id: string;
    public_benchmark_verified: boolean;
    public_mri_intake_verified?: boolean;
    training_executed: boolean;
    case_count: number;
    site_count: number;
    modalities: string[];
    source: {
      name: string;
      url: string;
      archive_md5_verified: boolean;
      archive_sha256_recorded: boolean;
    };
    claim_boundary: string;
  } | null;
  privacy_comparison: {
    mechanism: string;
    epsilon?: number;
    delta?: number;
    epsilon_parameter_per_call?: number;
    fraction_shared?: number;
    noise_multiplier?: number;
    max_grad_norm?: number;
    rounds_accounted?: number;
    sample_level_dp_accounted?: boolean;
    accounting_scope: string;
    end_to_end_sample_dp_claimed: boolean;
  } | null;
  local_inference: {
    backend: string;
    model: string;
    endpoint_scope: string;
    remote_step_api_called: boolean;
    raw_patient_data_transmitted: boolean;
    role: string;
    latency_ms: number;
    usage: Record<string, unknown>;
    prompt_or_response_content_persisted: boolean;
    gpu_snapshot_before: GpuSnapshot;
    gpu_snapshot_after: GpuSnapshot;
    claim_boundary: string;
  } | null;
  local_inference_redteam: {
    case_count: number;
    passed_count: number;
    all_passed: boolean;
    local_model_request_count: number;
    deterministic_output_gate_count: number;
    prompts_or_model_responses_included: boolean;
    remote_step_api_called: boolean;
    claim_boundary: string;
  } | null;
  local_inference_verification: {
    evidence_present: boolean;
    checks: Record<string, boolean>;
    passed: boolean;
    claim_boundary: string;
  } | null;
  local_inference_benchmark: {
    safe_fixed_workload: boolean;
    peak_safe_throughput: {
      concurrency: number;
      accepted_requests_per_second: number;
    } | null;
    claim_boundary: string;
  } | null;
  step_inference: {
    backend: string;
    model: string;
    endpoint_scope: string;
    remote_step_api_called: boolean;
    raw_patient_data_transmitted: boolean;
    role: string;
    latency_ms: number;
    usage: Record<string, unknown>;
    prompt_or_response_content_persisted: boolean;
    output_safety_gate_passed: boolean;
    claim_boundary: string;
  } | null;
}

export interface GpuSnapshot {
  available: boolean;
  gpus: Array<{
    name: string;
    memory_total_mib: number;
    memory_used_mib: number;
    gpu_utilization_percent: number;
    temperature_c: number;
  }>;
}

export interface MsdRunReceipt {
  available: boolean;
  dataset?: string;
  execution?: {
    status: string;
    strategy: string;
    rounds: number;
    local_epochs: number;
    elapsed_seconds: number;
    peak_gpu_memory_mb: number;
    simulated_sites: boolean;
  };
  aggregate_metrics?: {
    mean_dice: number;
    worst_site_dice: number;
    site_dice_std: number;
    hd95: number;
    sites: SiteMetric[];
  };
  files?: Array<{ name: string; sha256: string }>;
  site_receipts?: Array<SiteMetric & {
    round: number;
    elapsed_seconds: number;
    peak_gpu_memory_mb: number;
  }>;
  boundary?: string;
}

export interface MsdRunVerification {
  passed: boolean;
  checks: Record<string, boolean>;
  verified_at: string;
  receipt: MsdRunReceipt;
}
