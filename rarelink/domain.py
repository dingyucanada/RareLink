from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

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
