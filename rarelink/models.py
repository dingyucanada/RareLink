from datetime import datetime
from uuid import uuid4

from sqlmodel import Field, SQLModel

from rarelink.domain import ExperimentStatus, StudyStatus, TrainingJobStatus, utc_now


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
