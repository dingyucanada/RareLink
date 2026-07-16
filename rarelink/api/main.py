import importlib.util
import io
import json
import secrets
import zipfile
from contextlib import asynccontextmanager
from typing import Annotated, Any

import yaml
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from sqlmodel import Session, select

from rarelink import __version__
from rarelink.config import Settings, get_settings
from rarelink.database import create_db_and_tables, get_session
from rarelink.domain import (
    ApprovalRequest,
    CapabilityRead,
    ExperimentContract,
    ExperimentCreate,
    ExperimentStatus,
    StudyCreate,
    StudyStatus,
    utc_now,
)
from rarelink.imaging.preview import build_synthetic_imaging_preview
from rarelink.models import AgentArtifact, AuditEvent, Experiment, Study, TrainingJob
from rarelink.services.agents import build_research_agent
from rarelink.services.federation import build_federation_runner
from rarelink.services.ledger import append_event, list_events
from rarelink.services.policy import sanitize_site_aggregate
from rarelink.services.training_jobs import execute_training_job, recover_interrupted_jobs
from rarelink.services.workflow import InvalidTransition, transition


@asynccontextmanager
async def lifespan(_app: FastAPI):
    create_db_and_tables()
    recover_interrupted_jobs()
    yield


app = FastAPI(
    title="RareLink API",
    version=__version__,
    description="Research-only agentic federated learning control plane",
    lifespan=lifespan,
)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def demo_access_gate(request, call_next):  # type: ignore[no-untyped-def]
    """Optional lightweight gate for a public competition demo.

    This is deliberately not presented as production identity management. A
    deployment sets the token in the server environment; the Vite demo client
    can send it as a header while evaluators use the same access code.
    """
    expected = settings.rarelink_demo_access_token
    if not expected or request.url.path in {"/api/health", "/docs", "/openapi.json"}:
        return await call_next(request)
    provided = request.headers.get("X-RareLink-Demo-Token") or request.query_params.get(
        "access_token", ""
    )
    if not secrets.compare_digest(provided, expected):
        return JSONResponse(status_code=401, content={"detail": "Demo access token required"})
    return await call_next(request)

SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def as_json(value: str | None, default: Any = None) -> Any:
    return json.loads(value) if value else default


def study_view(study: Study) -> dict[str, Any]:
    return {
        "id": study.id,
        "title": study.title,
        "research_question": study.research_question,
        "disease_area": study.disease_area,
        "status": study.status,
        "protocol": as_json(study.protocol_json),
        "feasibility": as_json(study.feasibility_json),
        "contract": as_json(study.contract_json),
        "review_markdown": study.review_markdown,
        "report_markdown": study.report_markdown,
        "created_at": study.created_at,
        "updated_at": study.updated_at,
    }


def experiment_view(experiment: Experiment) -> dict[str, Any]:
    return {
        "id": experiment.id,
        "study_id": experiment.study_id,
        "strategy": experiment.strategy,
        "hypothesis": experiment.hypothesis,
        "parameters": as_json(experiment.parameters_json, {}),
        "status": experiment.status,
        "metrics": as_json(experiment.metrics_json),
        "created_at": experiment.created_at,
        "completed_at": experiment.completed_at,
    }


def event_view(event: AuditEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "study_id": event.study_id,
        "event_type": event.event_type,
        "actor": event.actor,
        "payload": as_json(event.payload_json, {}),
        "created_at": event.created_at,
    }


def artifact_view(artifact: AgentArtifact) -> dict[str, Any]:
    return {
        "id": artifact.id,
        "study_id": artifact.study_id,
        "role": artifact.role,
        "artifact_type": artifact.artifact_type,
        "content": as_json(artifact.content_json, {}),
        "source": artifact.source,
        "created_at": artifact.created_at,
    }


def job_view(job: TrainingJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "study_id": job.study_id,
        "experiment_id": job.experiment_id,
        "strategy": job.strategy,
        "backend": job.backend,
        "status": job.status,
        "progress": job.progress,
        "message": job.message,
        "workspace": job.workspace,
        "log_path": job.log_path,
        "global_model_path": job.global_model_path,
        "summary": as_json(job.summary_json),
        "error": job.error,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
    }


def store_agent_artifact(
    session: Session,
    study_id: str,
    role: str,
    artifact_type: str,
    content: dict[str, Any],
    source: str,
) -> AgentArtifact:
    artifact = AgentArtifact(
        study_id=study_id,
        role=role,
        artifact_type=artifact_type,
        content_json=json.dumps(content, ensure_ascii=False),
        source=source,
    )
    session.add(artifact)
    return artifact


def require_study(session: Session, study_id: str) -> Study:
    study = session.get(Study, study_id)
    if not study:
        raise HTTPException(status_code=404, detail="Study not found")
    return study


def move(study: Study, target: StudyStatus) -> None:
    try:
        study.status = transition(study.status, target)
    except InvalidTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    study.updated_at = utc_now()


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "rarelink"}


@app.get("/api/system/capabilities", response_model=CapabilityRead)
def capabilities(config: SettingsDep) -> CapabilityRead:
    torch_spec = importlib.util.find_spec("torch")
    gpu_available = False
    if torch_spec:
        import torch

        gpu_available = bool(torch.cuda.is_available())
    return CapabilityRead(
        app_version=__version__,
        environment=config.app_env,
        federation_mode=config.rarelink_fl_mode,
        step_mode="step-3.7" if config.step_api_key and config.rarelink_allow_llm else "template",
        gpu_available=gpu_available,
        monai_available=importlib.util.find_spec("monai") is not None,
        nvflare_available=importlib.util.find_spec("nvflare") is not None,
    )


def _read_json_if_present(path) -> dict[str, Any] | None:  # type: ignore[no-untyped-def]
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


@app.get("/api/system/evidence")
def system_evidence(config: SettingsDep) -> dict[str, Any]:
    repeated = _read_json_if_present(
        config.artifact_root / "repeated-benchmark" / "repeated-summary.json"
    )
    provisioned = _read_json_if_present(
        config.artifact_root / "nvflare-secure-provision" / "mtls-evidence.json"
    )
    runtime = _read_json_if_present(
        config.artifact_root / "nvflare-secure-provision" / "mtls-runtime-evidence.json"
    )
    return {
        "repeated_benchmark": repeated,
        "mtls_provisioning": provisioned,
        "mtls_runtime": runtime,
        "privacy_comparison": repeated.get("privacy_comparison") if repeated else None,
        "contains_patient_data": False,
        "evidence_scope": "synthetic_competition_engineering",
    }


@app.post("/api/studies", status_code=201)
def create_study(payload: StudyCreate, session: SessionDep) -> dict[str, Any]:
    study = Study(**payload.model_dump())
    session.add(study)
    session.flush()
    append_event(session, study.id, "study.created", "researcher", payload.model_dump())
    session.commit()
    session.refresh(study)
    return study_view(study)


@app.get("/api/studies")
def get_studies(session: SessionDep) -> list[dict[str, Any]]:
    statement = select(Study).order_by(Study.created_at.desc())
    return [study_view(study) for study in session.exec(statement).all()]


@app.get("/api/studies/{study_id}")
def get_study(study_id: str, session: SessionDep) -> dict[str, Any]:
    return study_view(require_study(session, study_id))


@app.get("/api/studies/{study_id}/imaging-preview")
def get_imaging_preview(
    study_id: str,
    site_id: str,
    session: SessionDep,
    config: SettingsDep,
) -> dict[str, Any]:
    study = require_study(session, study_id)
    contract = as_json(study.contract_json, {})
    dataset_version = contract.get("dataset_version", "synthetic-demo-v1")
    manifest = config.data_root / dataset_version / "manifest.json"
    if not manifest.exists():
        raise HTTPException(status_code=404, detail="Imaging preview manifest not found")
    try:
        return build_synthetic_imaging_preview(manifest, site_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/studies/{study_id}/protocol:generate")
def generate_protocol(
    study_id: str,
    session: SessionDep,
    config: SettingsDep,
) -> dict[str, Any]:
    study = require_study(session, study_id)
    if study.status != StudyStatus.DRAFT:
        raise HTTPException(status_code=409, detail="Protocol can only be generated from DRAFT")

    protocol = build_research_agent(config).generate_protocol(
        study.title, study.research_question, study.disease_area
    )
    study.protocol_json = protocol.model_dump_json()
    move(study, StudyStatus.PROTOCOL_REVIEW)
    artifact = store_agent_artifact(
        session,
        study.id,
        "research-director-agent",
        "research_protocol",
        protocol.model_dump(),
        protocol.source,
    )
    session.flush()
    append_event(
        session,
        study.id,
        "protocol.generated",
        "research-director-agent",
        {
            "source": protocol.source,
            "artifact_id": artifact.id,
            "protocol_hash_input": protocol.model_dump(),
        },
    )
    session.add(study)
    session.commit()
    session.refresh(study)
    return study_view(study)


@app.post("/api/studies/{study_id}/approve")
def approve_study(
    study_id: str,
    approval: ApprovalRequest,
    session: SessionDep,
) -> dict[str, Any]:
    study = require_study(session, study_id)
    targets = {
        StudyStatus.PROTOCOL_REVIEW: StudyStatus.FEASIBILITY_RUNNING,
        StudyStatus.RESULTS_REVIEW: StudyStatus.PRIVACY_REVIEW,
        StudyStatus.REPORT_READY: StudyStatus.ARCHIVED,
    }
    target = targets.get(study.status)
    if not target:
        raise HTTPException(
            status_code=409,
            detail=f"No approval action is valid from {study.status}",
        )
    previous = study.status
    move(study, target)
    append_event(
        session,
        study.id,
        "study.approved",
        approval.approved_by,
        {"from": previous, "to": target, "note": approval.note},
    )
    session.add(study)
    session.commit()
    session.refresh(study)
    return study_view(study)


@app.post("/api/studies/{study_id}/feasibility:run")
def run_feasibility(
    study_id: str,
    session: SessionDep,
    config: SettingsDep,
) -> dict[str, Any]:
    study = require_study(session, study_id)
    if study.status != StudyStatus.FEASIBILITY_RUNNING:
        raise HTTPException(
            status_code=409,
            detail="Approve the protocol before feasibility analysis",
        )

    raw_sites = [
        {
            "site_id": "site-a",
            "sample_count": 34,
            "usable_count": 30,
            "missing_modality_rate": 0.08,
            "label_completeness": 0.94,
            "spacing_summary": "median 1.0 x 1.0 x 1.2 mm",
            "age_buckets": {"0-5": 2, "6-12": 14, "13-18": 18},
            "quality_flags": ["two scans require review"],
            "patient_id_list": ["blocked-demo-value"],
        },
        {
            "site_id": "site-b",
            "sample_count": 28,
            "usable_count": 25,
            "missing_modality_rate": 0.11,
            "label_completeness": 0.89,
            "spacing_summary": "median 0.9 x 0.9 x 1.0 mm",
            "age_buckets": {"0-5": 6, "6-12": 9, "13-18": 13},
            "quality_flags": ["FLAIR missingness above cohort median"],
        },
        {
            "site_id": "site-c",
            "sample_count": 17,
            "usable_count": 14,
            "missing_modality_rate": 0.18,
            "label_completeness": 0.82,
            "spacing_summary": "median 1.2 x 1.2 x 2.0 mm",
            "age_buckets": {"0-5": 3, "6-12": 6, "13-18": 8},
            "quality_flags": ["slice thickness shift detected"],
        },
    ]
    decisions = [
        sanitize_site_aggregate(site, config.rarelink_min_group_size) for site in raw_sites
    ]
    feasibility = {
        "mode": "simulated_sites",
        "sites": [decision.payload for decision in decisions],
        "policy_decisions": [decision.model_dump(exclude={"payload"}) for decision in decisions],
        "total_usable_count": sum(int(decision.payload["usable_count"]) for decision in decisions),
        "finding": "Site C has higher missingness and a slice-thickness distribution shift.",
    }
    study.feasibility_json = json.dumps(feasibility, ensure_ascii=False)
    move(study, StudyStatus.FEASIBILITY_REVIEW)
    append_event(
        session,
        study.id,
        "feasibility.completed",
        "site-data-steward-agent",
        {
            "mode": "simulated_sites",
            "blocked_fields": [field for item in decisions for field in item.blocked_fields],
        },
    )
    session.add(study)
    session.commit()
    session.refresh(study)
    return study_view(study)


@app.post("/api/studies/{study_id}/contract:lock")
def lock_contract(
    study_id: str,
    contract: ExperimentContract,
    session: SessionDep,
) -> dict[str, Any]:
    study = require_study(session, study_id)
    if study.status != StudyStatus.FEASIBILITY_REVIEW:
        raise HTTPException(status_code=409, detail="Feasibility results must be reviewed first")
    if contract.raw_data_egress or contract.llm_raw_data_access:
        raise HTTPException(
            status_code=422,
            detail="The competition contract forbids raw data egress",
        )
    study.contract_json = contract.model_dump_json()
    move(study, StudyStatus.CONTRACT_LOCKED)
    append_event(
        session,
        study.id,
        "contract.locked",
        contract.approved_by,
        contract.model_dump(),
    )
    session.add(study)
    session.commit()
    session.refresh(study)
    return study_view(study)


@app.post("/api/studies/{study_id}/contract:propose")
def propose_contract(
    study_id: str,
    session: SessionDep,
    config: SettingsDep,
) -> dict[str, Any]:
    study = require_study(session, study_id)
    if study.status != StudyStatus.FEASIBILITY_REVIEW:
        raise HTTPException(status_code=409, detail="Feasibility results must be reviewed first")
    existing = session.exec(
        select(AgentArtifact)
        .where(
            AgentArtifact.study_id == study.id,
            AgentArtifact.artifact_type == "experiment_proposal",
        )
        .order_by(AgentArtifact.created_at.desc())
    ).first()
    if existing:
        return artifact_view(existing)

    proposal = build_research_agent(config).propose_experiment(
        as_json(study.protocol_json, {}),
        as_json(study.feasibility_json, {}),
    )
    artifact = store_agent_artifact(
        session,
        study.id,
        "experiment-designer-agent",
        "experiment_proposal",
        proposal.model_dump(),
        proposal.source,
    )
    session.flush()
    append_event(
        session,
        study.id,
        "agent.experiment-proposal.created",
        "experiment-designer-agent",
        {
            "artifact_id": artifact.id,
            "source": proposal.source,
            "strategies": proposal.strategies,
            "requires_human_approval": True,
        },
    )
    session.commit()
    session.refresh(artifact)
    return artifact_view(artifact)


@app.post("/api/studies/{study_id}/experiments", status_code=201)
def create_experiment(
    study_id: str,
    payload: ExperimentCreate,
    session: SessionDep,
) -> dict[str, Any]:
    study = require_study(session, study_id)
    if study.status not in {StudyStatus.CONTRACT_LOCKED, StudyStatus.TRAINING_RUNNING}:
        raise HTTPException(status_code=409, detail="Lock the experiment contract first")
    contract = ExperimentContract.model_validate_json(study.contract_json or "{}")
    strategy = payload.strategy.lower()
    if strategy not in contract.strategies:
        raise HTTPException(status_code=422, detail="Strategy is outside the locked contract")
    duplicate = session.exec(
        select(Experiment).where(
            Experiment.study_id == study.id,
            Experiment.strategy == strategy,
        )
    ).first()
    if duplicate:
        raise HTTPException(
            status_code=409,
            detail="An experiment for this strategy already exists",
        )
    experiment = Experiment(
        study_id=study.id,
        strategy=strategy,
        hypothesis=payload.hypothesis,
        parameters_json=json.dumps(payload.parameters, sort_keys=True),
    )
    session.add(experiment)
    append_event(
        session,
        study.id,
        "experiment.created",
        "federated-experiment-agent",
        {"experiment_id": experiment.id, "strategy": strategy},
    )
    session.commit()
    session.refresh(experiment)
    return experiment_view(experiment)


@app.get("/api/studies/{study_id}/experiments")
def get_experiments(study_id: str, session: SessionDep) -> list[dict[str, Any]]:
    require_study(session, study_id)
    statement = (
        select(Experiment).where(Experiment.study_id == study_id).order_by(Experiment.created_at)
    )
    return [experiment_view(item) for item in session.exec(statement).all()]


@app.post("/api/experiments/{experiment_id}:run")
def run_experiment(
    experiment_id: str,
    background_tasks: BackgroundTasks,
    session: SessionDep,
    config: SettingsDep,
) -> dict[str, Any]:
    experiment = session.get(Experiment, experiment_id)
    if not experiment:
        raise HTTPException(status_code=404, detail="Experiment not found")
    if experiment.status not in {ExperimentStatus.PENDING, ExperimentStatus.FAILED}:
        raise HTTPException(status_code=409, detail="Only pending or failed experiments can be run")
    study = require_study(session, experiment.study_id)
    if study.status in {StudyStatus.CONTRACT_LOCKED, StudyStatus.FAILED_RETRYABLE}:
        move(study, StudyStatus.TRAINING_RUNNING)
    elif study.status != StudyStatus.TRAINING_RUNNING:
        raise HTTPException(status_code=409, detail="Study is not accepting training jobs")

    experiment.status = ExperimentStatus.RUNNING
    session.add(experiment)
    session.commit()

    contract = ExperimentContract.model_validate_json(study.contract_json or "{}")
    if config.rarelink_fl_mode == "nvflare":
        job = TrainingJob(
            study_id=study.id,
            experiment_id=experiment.id,
            strategy=experiment.strategy,
            backend="monai" if experiment.strategy == "local" else "nvflare",
            message="Queued behind the DGX Spark unified-memory guard",
        )
        session.add(job)
        session.flush()
        append_event(
            session,
            study.id,
            "training-job.queued",
            "federated-experiment-agent",
            {
                "job_id": job.id,
                "experiment_id": experiment.id,
                "strategy": experiment.strategy,
                "backend": job.backend,
            },
        )
        session.commit()
        background_tasks.add_task(execute_training_job, job.id)
        session.refresh(experiment)
        return experiment_view(experiment)

    try:
        runner = build_federation_runner(config.rarelink_fl_mode)
        metrics = runner.run(
            experiment.strategy,
            as_json(experiment.parameters_json, {}),
            contract,
        )
        experiment.metrics_json = metrics.model_dump_json()
        experiment.status = ExperimentStatus.COMPLETED
        experiment.completed_at = utc_now()
        append_event(
            session,
            study.id,
            "experiment.completed",
            "federated-experiment-agent",
            {
                "experiment_id": experiment.id,
                "strategy": experiment.strategy,
                "mode": config.rarelink_fl_mode,
                "metrics": metrics.model_dump(),
            },
        )
    except Exception as exc:
        experiment.status = ExperimentStatus.FAILED
        append_event(
            session,
            study.id,
            "experiment.failed",
            "federated-experiment-agent",
            {"experiment_id": experiment.id, "error": str(exc)},
        )
        session.add(experiment)
        session.commit()
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    completed = set(
        session.exec(
            select(Experiment.strategy).where(
                Experiment.study_id == study.id,
                Experiment.status == ExperimentStatus.COMPLETED,
            )
        ).all()
    )
    if set(contract.strategies).issubset(completed):
        move(study, StudyStatus.RESULTS_REVIEW)
    session.add(experiment)
    session.add(study)
    session.commit()
    session.refresh(experiment)
    return experiment_view(experiment)


@app.post("/api/studies/{study_id}/review:generate")
def generate_review(
    study_id: str,
    session: SessionDep,
    config: SettingsDep,
) -> dict[str, Any]:
    study = require_study(session, study_id)
    if study.status != StudyStatus.RESULTS_REVIEW:
        raise HTTPException(status_code=409, detail="Complete all contracted experiments first")
    experiments = session.exec(
        select(Experiment).where(
            Experiment.study_id == study.id,
            Experiment.status == ExperimentStatus.COMPLETED,
        )
    ).all()
    experiment_evidence = [
        {
            "experiment_id": item.id,
            "strategy": item.strategy,
            "parameters": as_json(item.parameters_json, {}),
            "metrics": as_json(item.metrics_json, {}),
        }
        for item in experiments
    ]
    review = build_research_agent(config).review_evidence(
        as_json(study.contract_json, {}), experiment_evidence
    )
    store_agent_artifact(
        session,
        study.id,
        "statistical-review-agent",
        "evidence_review",
        review.model_dump(),
        review.source,
    )
    study.review_markdown = "\n".join(
        [
            "## Statistical evidence review",
            "",
            f"**Leading strategy:** {review.leading_strategy}",
            "",
            review.recommendation,
            "",
            "### Evidence",
            *(f"- {item}" for item in review.evidence),
            "",
            "### Fairness findings",
            *(f"- {item}" for item in review.fairness_findings),
            "",
            "### Limitations",
            *(f"- {item}" for item in review.limitations),
        ]
    )
    append_event(
        session,
        study.id,
        "review.generated",
        "statistical-review-agent",
        {
            "evidence_experiment_ids": [item.id for item in experiments],
            "source": review.source,
            "leading_strategy": review.leading_strategy,
        },
    )
    session.add(study)
    session.commit()
    session.refresh(study)
    return study_view(study)


@app.post("/api/studies/{study_id}/evidence-brief:generate")
def generate_evidence_brief(
    study_id: str,
    session: SessionDep,
    config: SettingsDep,
) -> dict[str, Any]:
    """Generate a judge-facing explanation from aggregate evidence only.

    Unlike the final review, this is available as soon as one locked experiment
    has completed. It never changes study state and is intentionally separate
    from the human-approved research report.
    """
    study = require_study(session, study_id)
    existing = session.exec(
        select(AgentArtifact)
        .where(
            AgentArtifact.study_id == study.id,
            AgentArtifact.artifact_type == "evidence_brief",
        )
        .order_by(AgentArtifact.created_at.desc())
    ).first()
    if existing:
        return artifact_view(existing)
    experiments = session.exec(
        select(Experiment)
        .where(
            Experiment.study_id == study.id,
            Experiment.status == ExperimentStatus.COMPLETED,
        )
        .order_by(Experiment.created_at)
    ).all()
    if not experiments:
        raise HTTPException(status_code=409, detail="Complete at least one experiment first")
    evidence = [
        {
            "experiment_id": item.id,
            "strategy": item.strategy,
            "parameters": as_json(item.parameters_json, {}),
            "metrics": as_json(item.metrics_json, {}),
        }
        for item in experiments
    ]
    contract = as_json(study.contract_json, {})
    repeated = _read_json_if_present(
        config.artifact_root / "repeated-benchmark" / "repeated-summary.json"
    )
    if repeated:
        contract["repeated_benchmark"] = repeated
    review = build_research_agent(config).review_evidence(contract, evidence)
    artifact = store_agent_artifact(
        session,
        study.id,
        "evidence-narrator-agent",
        "evidence_brief",
        review.model_dump(),
        review.source,
    )
    session.flush()
    append_event(
        session,
        study.id,
        "agent.evidence-brief.created",
        "evidence-narrator-agent",
        {
            "artifact_id": artifact.id,
            "source": review.source,
            "completed_experiment_ids": [item.id for item in experiments],
            "input_boundary": "aggregate_metrics_only",
        },
    )
    session.commit()
    session.refresh(artifact)
    return artifact_view(artifact)


@app.post("/api/studies/{study_id}/report:generate")
def generate_report(
    study_id: str,
    session: SessionDep,
    config: SettingsDep,
) -> dict[str, Any]:
    study = require_study(session, study_id)
    if study.status != StudyStatus.PRIVACY_REVIEW:
        raise HTTPException(status_code=409, detail="Human approval of results is required")
    experiments = session.exec(
        select(Experiment).where(Experiment.study_id == study.id).order_by(Experiment.created_at)
    ).all()
    rows = [
        f"| {item.id} | {item.strategy} | "
        f"{as_json(item.metrics_json, {}).get('mean_dice', 0):.4f} | "
        f"{as_json(item.metrics_json, {}).get('worst_site_dice', 0):.4f} |"
        for item in experiments
    ]
    events = list_events(session, study.id)
    feasibility = as_json(study.feasibility_json, {})
    privacy = build_research_agent(config).assess_privacy(
        feasibility,
        {
            "event_count": len(events),
            "event_types": sorted({item.event_type for item in events}),
            "contains_patient_level_data": False,
        },
    )
    store_agent_artifact(
        session,
        study.id,
        "privacy-review-agent",
        "privacy_assessment",
        privacy.model_dump(),
        privacy.source,
    )
    if not privacy.safe_for_aggregate_report:
        append_event(
            session,
            study.id,
            "report.blocked-by-privacy-agent",
            "privacy-review-agent",
            {"outcome": privacy.outcome, "source": privacy.source},
        )
        session.commit()
        raise HTTPException(status_code=409, detail="Privacy Agent blocked aggregate reporting")

    review_artifact = session.exec(
        select(AgentArtifact)
        .where(
            AgentArtifact.study_id == study.id,
            AgentArtifact.artifact_type == "evidence_review",
        )
        .order_by(AgentArtifact.created_at.desc())
    ).first()
    if not review_artifact:
        raise HTTPException(status_code=409, detail="Statistical review artifact is missing")
    evidence = {
        "study": {
            "title": study.title,
            "research_question": study.research_question,
            "disease_area": study.disease_area,
        },
        "protocol": as_json(study.protocol_json, {}),
        "contract": as_json(study.contract_json, {}),
        "experiments": [experiment_view(item) for item in experiments],
        "statistical_review": as_json(review_artifact.content_json, {}),
        "privacy_assessment": privacy.model_dump(),
    }
    narrative = build_research_agent(config).write_narrative(evidence)
    store_agent_artifact(
        session,
        study.id,
        "research-writing-agent",
        "research_narrative",
        narrative.model_dump(),
        narrative.source,
    )
    study.report_markdown = "\n".join(
        [
            f"# {narrative.title}",
            "",
            "> Research-use engineering demonstration; not a clinical diagnostic result.",
            "",
            "## Executive summary",
            "",
            narrative.executive_summary,
            "",
            "## Methods",
            *(f"- {item}" for item in narrative.methods),
            "",
            "## Findings",
            *(f"- {item}" for item in narrative.findings),
            "",
            "## Experiment ledger",
            "",
            "| Experiment | Strategy | Mean Dice | Worst-site Dice |",
            "|---|---:|---:|---:|",
            *rows,
            "",
            "## Limitations",
            *(f"- {item}" for item in narrative.limitations),
            "",
            "## Next steps",
            *(f"- {item}" for item in narrative.next_steps),
            "",
            "## Privacy assessment",
            "",
            f"Outcome: **{privacy.outcome}**",
            *(f"- {item}" for item in privacy.checks),
        ]
    )
    move(study, StudyStatus.REPORT_READY)
    append_event(
        session,
        study.id,
        "report.generated",
        "research-writing-agent",
        {
            "experiment_ids": [item.id for item in experiments],
            "privacy_source": privacy.source,
            "writing_source": narrative.source,
        },
    )
    session.add(study)
    session.commit()
    session.refresh(study)
    return study_view(study)


@app.get("/api/studies/{study_id}/events")
def get_events(study_id: str, session: SessionDep) -> list[dict[str, Any]]:
    require_study(session, study_id)
    return [event_view(item) for item in list_events(session, study_id)]


@app.get("/api/studies/{study_id}/agent-artifacts")
def get_agent_artifacts(study_id: str, session: SessionDep) -> list[dict[str, Any]]:
    require_study(session, study_id)
    statement = (
        select(AgentArtifact)
        .where(AgentArtifact.study_id == study_id)
        .order_by(AgentArtifact.created_at)
    )
    return [artifact_view(item) for item in session.exec(statement).all()]


@app.get("/api/studies/{study_id}/training-jobs")
def get_training_jobs(study_id: str, session: SessionDep) -> list[dict[str, Any]]:
    require_study(session, study_id)
    statement = (
        select(TrainingJob).where(TrainingJob.study_id == study_id).order_by(TrainingJob.created_at)
    )
    return [job_view(item) for item in session.exec(statement).all()]


@app.get("/api/studies/{study_id}/export")
def export_study(study_id: str, session: SessionDep) -> Response:
    study = require_study(session, study_id)
    if study.status not in {StudyStatus.REPORT_READY, StudyStatus.ARCHIVED}:
        raise HTTPException(status_code=409, detail="The research report is not ready for export")

    experiments = session.exec(
        select(Experiment).where(Experiment.study_id == study.id).order_by(Experiment.created_at)
    ).all()
    events = list_events(session, study.id)
    agent_artifacts = session.exec(
        select(AgentArtifact)
        .where(AgentArtifact.study_id == study.id)
        .order_by(AgentArtifact.created_at)
    ).all()
    training_jobs = session.exec(
        select(TrainingJob).where(TrainingJob.study_id == study.id).order_by(TrainingJob.created_at)
    ).all()
    reproduce = {
        "study_id": study.id,
        "app_version": __version__,
        "federation_mode": settings.rarelink_fl_mode,
        "contract": as_json(study.contract_json, {}),
        "experiments": [
            {
                "experiment_id": item.id,
                "strategy": item.strategy,
                "parameters": as_json(item.parameters_json, {}),
                "metrics": as_json(item.metrics_json, {}),
            }
            for item in experiments
        ],
    }
    manifest = {
        "study_id": study.id,
        "title": study.title,
        "status": study.status,
        "created_at": study.created_at.isoformat(),
        "exported_at": utc_now().isoformat(),
        "research_use_only": True,
        "simulated_sites": True,
        "contains_patient_level_data": False,
    }

    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        archive.writestr("protocol.json", study.protocol_json or "{}")
        archive.writestr("federated_feasibility.json", study.feasibility_json or "{}")
        archive.writestr("experiment_contract.json", study.contract_json or "{}")
        archive.writestr(
            "experiments.json",
            json.dumps([experiment_view(item) for item in experiments], default=str, indent=2),
        )
        archive.writestr(
            "experiment_ledger.jsonl",
            "\n".join(
                json.dumps(event_view(item), ensure_ascii=False, default=str) for item in events
            ),
        )
        archive.writestr(
            "agent_artifacts.json",
            json.dumps(
                [artifact_view(item) for item in agent_artifacts],
                ensure_ascii=False,
                default=str,
                indent=2,
            ),
        )
        archive.writestr(
            "training_jobs.json",
            json.dumps(
                [job_view(item) for item in training_jobs],
                ensure_ascii=False,
                default=str,
                indent=2,
            ),
        )
        archive.writestr("statistical_privacy_review.md", study.review_markdown or "")
        archive.writestr("research_report.md", study.report_markdown or "")
        archive.writestr(
            "reproduce.yaml",
            yaml.safe_dump(reproduce, sort_keys=False, allow_unicode=True),
        )
    return Response(
        content=stream.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="rarelink-{study.id}.zip"',
            "X-Content-Type-Options": "nosniff",
        },
    )
