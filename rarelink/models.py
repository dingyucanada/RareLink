from datetime import datetime
from uuid import uuid4

from sqlmodel import Field, SQLModel

from rarelink.domain import (
    ExperimentStatus,
    PhysicalJobStatus,
    PhysicalSiteStatus,
    StudyStatus,
    TrainingJobStatus,
    utc_now,
)


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


class Study(SQLModel, table=True):
    id: str = Field(default_factory=lambda: new_id("study"), primary_key=True)
    title: str = Field(index=True)
    research_question: str
    disease_area: str
    status: StudyStatus = Field(default=StudyStatus.DRAFT, index=True)
    protocol_json: str | None = None
    feasibility_json: str | None = None
    contract_json: str | None = None
    review_markdown: str | None = None
    report_markdown: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class Experiment(SQLModel, table=True):
    id: str = Field(default_factory=lambda: new_id("exp"), primary_key=True)
    study_id: str = Field(index=True, foreign_key="study.id")
    strategy: str = Field(index=True)
    hypothesis: str
    parameters_json: str = "{}"
    status: ExperimentStatus = Field(default=ExperimentStatus.PENDING, index=True)
    metrics_json: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None


class AuditEvent(SQLModel, table=True):
    id: str = Field(default_factory=lambda: new_id("evt"), primary_key=True)
    study_id: str = Field(index=True, foreign_key="study.id")
    event_type: str = Field(index=True)
    actor: str
    payload_json: str = "{}"
    created_at: datetime = Field(default_factory=utc_now, index=True)


class AgentArtifact(SQLModel, table=True):
    id: str = Field(default_factory=lambda: new_id("agent"), primary_key=True)
    study_id: str = Field(index=True, foreign_key="study.id")
    role: str = Field(index=True)
    artifact_type: str = Field(index=True)
    content_json: str
    source: str = Field(index=True)
    created_at: datetime = Field(default_factory=utc_now, index=True)


class TrainingJob(SQLModel, table=True):
    id: str = Field(default_factory=lambda: new_id("job"), primary_key=True)
    study_id: str = Field(index=True, foreign_key="study.id")
    experiment_id: str = Field(index=True, foreign_key="experiment.id")
    strategy: str = Field(index=True)
    backend: str = Field(default="nvflare", index=True)
    status: TrainingJobStatus = Field(default=TrainingJobStatus.QUEUED, index=True)
    progress: int = 0
    message: str = "Queued"
    workspace: str | None = None
    log_path: str | None = None
    global_model_path: str | None = None
    summary_json: str | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=utc_now, index=True)
    started_at: datetime | None = None
    completed_at: datetime | None = None


class PhysicalSite(SQLModel, table=True):
    site_id: str = Field(primary_key=True)
    display_name: str
    organization: str = Field(index=True)
    expected: bool = Field(default=True, index=True)
    status: PhysicalSiteStatus = Field(default=PhysicalSiteStatus.UNKNOWN, index=True)
    certificate_status: str = "UNKNOWN"
    data_ready: bool = False
    gpu_ready: bool = False
    monai_ready: bool = False
    nvflare_ready: bool = False
    current_job_id: str | None = Field(default=None, index=True)
    current_round: int = 0
    total_rounds: int = 0
    free_memory_percent: float | None = None
    free_disk_percent: float | None = None
    dataset_fingerprint: str | None = Field(default=None, index=True)
    receipt_sha256: str | None = None
    heartbeat_json: str | None = None
    last_heartbeat_at: datetime | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class PhysicalHeartbeatReceipt(SQLModel, table=True):
    heartbeat_id: str = Field(primary_key=True)
    site_id: str = Field(index=True, foreign_key="physicalsite.site_id")
    payload_sha256: str
    captured_at: datetime
    received_at: datetime = Field(default_factory=utc_now, index=True)


class PhysicalControlEvent(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    event_id: str = Field(
        default_factory=lambda: new_id("physical-event"),
        index=True,
        sa_column_kwargs={"unique": True},
    )
    action: str = Field(index=True)
    actor: str = Field(index=True)
    resource_type: str = Field(index=True)
    resource_id: str = Field(index=True)
    outcome: str = Field(index=True)
    payload_json: str = "{}"
    previous_hash: str
    event_hash: str = Field(index=True)
    algorithm: str
    key_id: str | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utc_now, index=True)


class PhysicalFederationJob(SQLModel, table=True):
    id: str = Field(default_factory=lambda: new_id("physical-job"), primary_key=True)
    study_id: str | None = Field(default=None, index=True)
    external_job_id: str | None = Field(default=None, index=True)
    submit_token_sha256: str | None = Field(default=None, index=True)
    strategy: str = Field(index=True)
    status: PhysicalJobStatus = Field(default=PhysicalJobStatus.DRAFT, index=True)
    bundle_sha256: str | None = None
    expected_sites_json: str
    dataset_fingerprints_json: str = "{}"
    connected_sites_json: str = "[]"
    total_rounds: int
    local_epochs: int
    current_round: int = 0
    received_updates: int = 0
    quorum_required: int
    job_directory: str
    approved_by: str | None = None
    approval_note: str | None = None
    attempt: int = 0
    previous_external_job_ids_json: str = "[]"
    global_model_path: str | None = None
    global_model_sha256: str | None = None
    metrics_json: str | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=utc_now, index=True)
    updated_at: datetime = Field(default_factory=utc_now, index=True)
    completed_at: datetime | None = None
