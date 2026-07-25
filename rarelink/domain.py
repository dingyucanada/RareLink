from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(UTC)


class StudyStatus(StrEnum):
    DRAFT = "DRAFT"
    PROTOCOL_REVIEW = "PROTOCOL_REVIEW"
    FEASIBILITY_RUNNING = "FEASIBILITY_RUNNING"
    FEASIBILITY_REVIEW = "FEASIBILITY_REVIEW"
    CONTRACT_LOCKED = "CONTRACT_LOCKED"
    TRAINING_RUNNING = "TRAINING_RUNNING"
    RESULTS_REVIEW = "RESULTS_REVIEW"
    PRIVACY_REVIEW = "PRIVACY_REVIEW"
    REPORT_READY = "REPORT_READY"
    ARCHIVED = "ARCHIVED"
    BLOCKED_BY_POLICY = "BLOCKED_BY_POLICY"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_FINAL = "FAILED_FINAL"


class ExperimentStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class TrainingJobStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class PhysicalSiteStatus(StrEnum):
    UNKNOWN = "UNKNOWN"
    READY = "READY"
    DEGRADED = "DEGRADED"
    OFFLINE = "OFFLINE"
    TRAINING = "TRAINING"


class PhysicalJobStatus(StrEnum):
    DRAFT = "DRAFT"
    APPROVAL_PENDING = "APPROVAL_PENDING"
    SUBMITTED = "SUBMITTED"
    WAITING_FOR_SITES = "WAITING_FOR_SITES"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ABORTED = "ABORTED"


class PhysicalSiteHeartbeat(BaseModel):
    model_config = {"extra": "forbid"}

    heartbeat_id: str = Field(min_length=8, max_length=128)
    agent_version: str = Field(min_length=1, max_length=64)
    status: PhysicalSiteStatus
    certificate_status: str = Field(min_length=2, max_length=32)
    data_ready: bool
    gpu_ready: bool
    monai_ready: bool
    nvflare_ready: bool
    current_job_id: str | None = Field(default=None, max_length=128)
    current_round: int = Field(default=0, ge=0, le=10_000)
    total_rounds: int = Field(default=0, ge=0, le=10_000)
    free_memory_percent: float = Field(ge=0, le=100)
    free_disk_percent: float = Field(ge=0, le=100)
    dataset_fingerprint: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    captured_at: datetime
    contains_patient_data: bool = False


class PhysicalSiteCreate(BaseModel):
    model_config = {"extra": "forbid"}

    site_id: str = Field(pattern=r"^[a-z][a-z0-9-]{2,62}$")
    display_name: str = Field(min_length=2, max_length=160)
    organization: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,62}$")
    expected: bool = True


class PhysicalJobCreate(BaseModel):
    model_config = {"extra": "forbid"}

    study_id: str | None = None
    strategy: str = Field(pattern=r"^(fedavg|fedprox)$")
    expected_sites: list[str] = Field(min_length=3)
    total_rounds: int = Field(ge=1, le=1000)
    local_epochs: int = Field(default=1, ge=1, le=100)
    job_directory: str = Field(min_length=1, max_length=500)


class PhysicalJobApproval(BaseModel):
    model_config = {"extra": "forbid"}

    approved_by: str | None = Field(
        default=None,
        min_length=2,
        max_length=100,
        description=(
            "Deprecated compatibility field; the authenticated principal is authoritative"
        ),
    )
    note: str = Field(min_length=2, max_length=1000)
    submit_token: str = Field(min_length=8, max_length=128)


class PhysicalSecondApproval(BaseModel):
    model_config = {"extra": "forbid"}

    attestation: Literal["CONTRACT_DATA_AND_SECURITY_REVIEWED"]
    note: str = Field(default="", max_length=1000)


class PhysicalApprovalRevocation(BaseModel):
    model_config = {"extra": "forbid"}

    attestation: Literal["REVOKE_PHYSICAL_CONTRACT_APPROVAL"]
    reason: str = Field(min_length=8, max_length=1000)


class PhysicalModelVerification(BaseModel):
    model_config = {"extra": "forbid"}

    model_path: str = Field(min_length=1, max_length=500)
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class StudyCreate(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    research_question: str = Field(min_length=10, max_length=2000)
    disease_area: str = Field(default="pediatric high-grade glioma", max_length=160)


class Protocol(BaseModel):
    title: str
    research_question: str
    hypothesis: str
    modalities: list[str]
    inclusion_criteria: list[str]
    exclusion_criteria: list[str]
    primary_endpoint: str = "mean_dice"
    guardrail_metrics: list[str] = Field(
        default_factory=lambda: ["worst_site_dice", "site_dice_std", "hd95"]
    )
    allowed_strategies: list[str] = Field(
        default_factory=lambda: ["local", "fedavg", "fedprox", "fedavg_dpsgd"]
    )
    limitations: list[str]
    source: str = "template"


class ExperimentContract(BaseModel):
    contract_id: str
    dataset_version: str = "synthetic-demo-v1"
    split_seed: int = 2026
    sites: list[str] = Field(default_factory=lambda: ["site-a", "site-b", "site-c"])
    task: str = "3d_tumor_segmentation"
    model: str = "segresnet-small"
    strategies: list[str] = Field(
        default_factory=lambda: ["local", "fedavg", "fedprox", "fedavg_dpsgd"]
    )
    rounds: int = Field(default=5, ge=1, le=50)
    local_epochs: int = Field(default=1, ge=1, le=10)
    max_trials: int = Field(default=4, ge=1, le=10)
    primary_metric: str = "mean_dice"
    guardrail_metrics: list[str] = Field(
        default_factory=lambda: ["worst_site_dice", "site_dice_std", "hd95"]
    )
    min_group_size: int = Field(default=5, ge=3, le=20)
    raw_data_egress: bool = False
    llm_raw_data_access: bool = False
    approved_by: str = Field(min_length=2, max_length=100)


class ExperimentProposal(BaseModel):
    dataset_version: str = "synthetic-demo-v1"
    split_seed: int = 2026
    sites: list[str] = Field(default_factory=lambda: ["site-a", "site-b", "site-c"])
    task: str = "3d_tumor_segmentation"
    model: str = "segresnet-small"
    strategies: list[str] = Field(
        default_factory=lambda: ["local", "fedavg", "fedprox", "fedavg_dpsgd"]
    )
    rounds: int = Field(default=5, ge=1, le=50)
    local_epochs: int = Field(default=1, ge=1, le=10)
    max_trials: int = Field(default=4, ge=1, le=10)
    primary_metric: str = "mean_dice"
    guardrail_metrics: list[str] = Field(
        default_factory=lambda: ["worst_site_dice", "site_dice_std", "hd95"]
    )
    min_group_size: int = Field(default=5, ge=3, le=20)
    hypotheses: dict[str, str]
    rationale: list[str]
    source: str = "template"


class EvidenceReview(BaseModel):
    leading_strategy: str
    recommendation: str
    evidence: list[str]
    fairness_findings: list[str]
    limitations: list[str]
    source: str = "template"


class PrivacyAssessment(BaseModel):
    outcome: str
    safe_for_aggregate_report: bool
    checks: list[str]
    blocked_or_suppressed: list[str]
    residual_risks: list[str]
    source: str = "template"


class ResearchNarrative(BaseModel):
    title: str
    executive_summary: str
    methods: list[str]
    findings: list[str]
    limitations: list[str]
    next_steps: list[str]
    source: str = "template"


class ApprovalRequest(BaseModel):
    approved_by: str = Field(min_length=2, max_length=100)
    note: str = Field(default="", max_length=1000)


class ExperimentCreate(BaseModel):
    strategy: str
    hypothesis: str = Field(min_length=8, max_length=1000)
    parameters: dict[str, Any] = Field(default_factory=dict)


class PolicyDecision(BaseModel):
    result: str
    rule: str
    blocked_fields: list[str] = Field(default_factory=list)
    payload: dict[str, Any]


class SiteMetrics(BaseModel):
    site_id: str
    dice: float
    hd95: float | None = None


class ExperimentMetrics(BaseModel):
    mean_dice: float
    worst_site_dice: float
    site_dice_std: float
    hd95: float | None = None
    sites: list[SiteMetrics]


class CapabilityRead(BaseModel):
    app_version: str
    environment: str
    federation_mode: str
    step_mode: str
    gpu_available: bool
    monai_available: bool
    nvflare_available: bool
    agent_backend: str
    local_inference_configured: bool
    local_inference_available: bool
    local_inference_model: str | None = None
    local_inference_endpoint: str | None = None
    local_inference_boundary: str
