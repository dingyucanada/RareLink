import importlib.util
import io
import json
import secrets
import zipfile
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Annotated, Any

import yaml
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
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
    PhysicalJobApproval,
    PhysicalJobCreate,
    PhysicalJobStatus,
    PhysicalModelVerification,
    PhysicalSiteCreate,
    PhysicalSiteHeartbeat,
    PhysicalSiteStatus,
    StudyCreate,
    StudyStatus,
    utc_now,
)
from rarelink.imaging.preview import build_synthetic_imaging_preview
from rarelink.models import (
    AgentArtifact,
    AuditEvent,
    Experiment,
    PhysicalFederationJob,
    PhysicalHeartbeatReceipt,
    PhysicalSite,
    Study,
    TrainingJob,
)
from rarelink.security import verify_heartbeat_signature
from rarelink.services.agents import build_research_agent
from rarelink.services.federation import build_federation_runner
from rarelink.services.ledger import append_event, list_events
from rarelink.services.local_inference import probe_spark_inference
from rarelink.services.physical_controller import (
    JobConflictError,
    JobNotFoundError,
    JobValidationError,
    NvflareCliAdapter,
    PhysicalControllerError,
    PhysicalFederationController,
    validate_exported_job,
)
from rarelink.services.physical_store import SqlPhysicalJobStore
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


def physical_site_view(site: PhysicalSite, config: Settings) -> dict[str, Any]:
    status = site.status
    if site.last_heartbeat_at:
        observed_at = site.last_heartbeat_at
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=UTC)
        age = (datetime.now(UTC) - observed_at).total_seconds()
        if age > config.rarelink_physical_heartbeat_max_age_seconds * 2:
            status = PhysicalSiteStatus.OFFLINE
    return {
        "deployment_mode": config.rarelink_physical_mode,
        "site_id": site.site_id,
        "display_name": site.display_name,
        "organization": site.organization,
        "expected": site.expected,
        "status": status,
        "certificate_status": site.certificate_status,
        "data_ready": site.data_ready,
        "gpu_ready": site.gpu_ready,
        "monai_ready": site.monai_ready,
        "nvflare_ready": site.nvflare_ready,
        "current_job_id": site.current_job_id,
        "current_round": site.current_round,
        "total_rounds": site.total_rounds,
        "free_memory_percent": site.free_memory_percent,
        "free_disk_percent": site.free_disk_percent,
        "receipt_sha256": site.receipt_sha256,
        "last_heartbeat_at": site.last_heartbeat_at,
        "contains_patient_data": False,
    }


def physical_job_view(job: PhysicalFederationJob, config: Settings) -> dict[str, Any]:
    return {
        "deployment_mode": config.rarelink_physical_mode,
        "id": job.id,
        "study_id": job.study_id,
        "external_job_id": job.external_job_id,
        "strategy": job.strategy,
        "status": job.status,
        "expected_sites": as_json(job.expected_sites_json, []),
        "connected_sites": as_json(job.connected_sites_json, []),
        "total_rounds": job.total_rounds,
        "local_epochs": job.local_epochs,
        "current_round": job.current_round,
        "received_updates": job.received_updates,
        "quorum_required": job.quorum_required,
        "approved_by": job.approved_by,
        "global_model_sha256": job.global_model_sha256,
        "metrics": as_json(job.metrics_json),
        "error": job.error,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "completed_at": job.completed_at,
        "contains_patient_data": False,
    }


def require_physical_enabled(config: Settings) -> None:
    if config.rarelink_physical_mode == "disabled":
        raise HTTPException(
            status_code=503,
            detail="Physical federation control plane is disabled",
        )


def require_physical_operator(request: Request, config: Settings) -> None:
    require_physical_enabled(config)
    expected = config.rarelink_physical_operator_token
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="Physical federation operator authentication is not configured",
        )
    provided = request.headers.get("X-RareLink-Operator-Token", "")
    if not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Physical federation operator token required")


def build_physical_controller(
    session: Session,
    config: Settings,
) -> tuple[PhysicalFederationController, Path]:
    if not config.rarelink_nvflare_admin_kit:
        raise HTTPException(status_code=503, detail="NVFLARE admin kit is not configured")
    admin_kit = Path(config.rarelink_nvflare_admin_kit).resolve()
    if not (admin_kit / "startup").is_dir():
        raise HTTPException(status_code=503, detail="NVFLARE admin kit is unavailable")
    controller = PhysicalFederationController(
        NvflareCliAdapter(executable=config.rarelink_nvflare_executable),
        SqlPhysicalJobStore(session),
    )
    return controller, admin_kit


def physical_controller_error(exc: PhysicalControllerError) -> HTTPException:
    if isinstance(exc, JobNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, JobConflictError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, JobValidationError):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=502, detail=str(exc))


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
    local_inference = probe_spark_inference(config, timeout_seconds=0.35)
    return CapabilityRead(
        app_version=__version__,
        environment=config.app_env,
        federation_mode=config.rarelink_fl_mode,
        step_mode="step-3.7" if config.step_api_key and config.rarelink_allow_llm else "template",
        gpu_available=gpu_available,
        monai_available=importlib.util.find_spec("monai") is not None,
        nvflare_available=importlib.util.find_spec("nvflare") is not None,
        agent_backend=config.rarelink_agent_backend,
        local_inference_configured=bool(local_inference["configured"]),
        local_inference_available=bool(local_inference["available"]),
        local_inference_model=local_inference["model"],
        local_inference_endpoint=local_inference["endpoint"],
        local_inference_boundary=local_inference["data_boundary"],
    )


@app.post("/api/physical/sites", status_code=201)
def register_physical_site(
    payload: PhysicalSiteCreate,
    request: Request,
    session: SessionDep,
    config: SettingsDep,
) -> dict[str, Any]:
    require_physical_operator(request, config)
    if session.get(PhysicalSite, payload.site_id):
        raise HTTPException(status_code=409, detail="Physical site is already registered")
    site = PhysicalSite(
        site_id=payload.site_id,
        display_name=payload.display_name,
        organization=payload.organization,
        expected=payload.expected,
    )
    session.add(site)
    session.commit()
    session.refresh(site)
    return physical_site_view(site, config)


@app.get("/api/physical/sites")
def list_physical_sites(session: SessionDep, config: SettingsDep) -> list[dict[str, Any]]:
    statement = select(PhysicalSite).order_by(PhysicalSite.site_id)
    return [physical_site_view(site, config) for site in session.exec(statement).all()]


@app.post("/api/physical/sites/{site_id}/heartbeat")
def receive_physical_site_heartbeat(
    site_id: str,
    payload: PhysicalSiteHeartbeat,
    request: Request,
    session: SessionDep,
    config: SettingsDep,
) -> dict[str, Any]:
    require_physical_enabled(config)
    site = session.get(PhysicalSite, site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Physical site is not registered")
    if payload.contains_patient_data:
        raise HTTPException(status_code=422, detail="Heartbeat must not contain patient data")
    if session.get(PhysicalHeartbeatReceipt, payload.heartbeat_id):
        raise HTTPException(status_code=409, detail="Heartbeat has already been accepted")

    secret = config.physical_site_secret_map.get(site_id)
    if not secret:
        raise HTTPException(
            status_code=503,
            detail="Physical site authentication is not configured",
        )
    timestamp_header = request.headers.get("X-RareLink-Site-Timestamp", "")
    signature = request.headers.get("X-RareLink-Site-Signature", "")
    try:
        timestamp = int(timestamp_header)
        captured_at = payload.captured_at
        if captured_at.tzinfo is None:
            captured_at = captured_at.replace(tzinfo=UTC)
        if (
            abs(int(captured_at.timestamp()) - timestamp)
            > config.rarelink_physical_heartbeat_max_age_seconds
        ):
            raise ValueError("Heartbeat health snapshot is outside the accepted replay window")
        serialized = payload.model_dump(mode="json")
        digest = verify_heartbeat_signature(
            site_id=site_id,
            timestamp=timestamp,
            heartbeat_id=payload.heartbeat_id,
            payload=serialized,
            secret=secret,
            signature=signature,
            max_age_seconds=config.rarelink_physical_heartbeat_max_age_seconds,
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    receipt = PhysicalHeartbeatReceipt(
        heartbeat_id=payload.heartbeat_id,
        site_id=site_id,
        payload_sha256=digest,
        captured_at=payload.captured_at,
    )
    site.status = payload.status
    site.certificate_status = payload.certificate_status
    site.data_ready = payload.data_ready
    site.gpu_ready = payload.gpu_ready
    site.monai_ready = payload.monai_ready
    site.nvflare_ready = payload.nvflare_ready
    site.current_job_id = payload.current_job_id
    site.current_round = payload.current_round
    site.total_rounds = payload.total_rounds
    site.free_memory_percent = payload.free_memory_percent
    site.free_disk_percent = payload.free_disk_percent
    site.receipt_sha256 = payload.receipt_sha256
    site.heartbeat_json = json.dumps(serialized, ensure_ascii=False, sort_keys=True)
    site.last_heartbeat_at = utc_now()
    site.updated_at = utc_now()
    session.add(receipt)
    session.add(site)
    session.commit()
    session.refresh(site)
    return physical_site_view(site, config)


@app.post("/api/physical/jobs", status_code=201)
def create_physical_job(
    payload: PhysicalJobCreate,
    request: Request,
    session: SessionDep,
    config: SettingsDep,
) -> dict[str, Any]:
    require_physical_operator(request, config)
    if payload.study_id and not session.get(Study, payload.study_id):
        raise HTTPException(status_code=422, detail="Linked study does not exist")
    expected_sites = list(dict.fromkeys(payload.expected_sites))
    if len(expected_sites) != len(payload.expected_sites):
        raise HTTPException(status_code=422, detail="Expected physical sites must be unique")
    registered = {
        site.site_id
        for site in session.exec(
            select(PhysicalSite).where(PhysicalSite.site_id.in_(expected_sites))
        ).all()
    }
    missing = sorted(set(expected_sites) - registered)
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"Expected physical sites are not registered: {', '.join(missing)}",
        )
    try:
        bundle = validate_exported_job(Path(payload.job_directory))
    except PhysicalControllerError as exc:
        raise physical_controller_error(exc) from exc
    if (
        bundle.strategy != payload.strategy
        or list(bundle.expected_sites) != expected_sites
        or bundle.total_rounds != payload.total_rounds
        or bundle.local_epochs != payload.local_epochs
    ):
        raise HTTPException(
            status_code=422,
            detail="Requested job metadata does not match the validated exported bundle",
        )
    job = PhysicalFederationJob(
        study_id=payload.study_id,
        strategy=bundle.strategy,
        status=PhysicalJobStatus.APPROVAL_PENDING,
        bundle_sha256=bundle.bundle_sha256,
        expected_sites_json=json.dumps(expected_sites),
        total_rounds=bundle.total_rounds,
        local_epochs=bundle.local_epochs,
        quorum_required=len(expected_sites),
        job_directory=payload.job_directory,
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return physical_job_view(job, config)


@app.get("/api/physical/jobs")
def list_physical_jobs(session: SessionDep, config: SettingsDep) -> list[dict[str, Any]]:
    statement = select(PhysicalFederationJob).order_by(PhysicalFederationJob.created_at.desc())
    return [physical_job_view(job, config) for job in session.exec(statement).all()]


@app.post("/api/physical/jobs/{job_id}:submit")
def submit_physical_job(
    job_id: str,
    payload: PhysicalJobApproval,
    request: Request,
    session: SessionDep,
    config: SettingsDep,
) -> dict[str, Any]:
    require_physical_operator(request, config)
    job = session.get(PhysicalFederationJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Physical job not found")
    if job.status not in {"APPROVAL_PENDING", "SUBMITTED"}:
        raise HTTPException(status_code=409, detail="Physical job is not awaiting submission")
    job.approved_by = payload.approved_by
    job.approval_note = payload.note
    job.updated_at = utc_now()
    session.add(job)
    session.commit()
    controller, admin_kit = build_physical_controller(session, config)
    try:
        controller.submit(
            job_id,
            admin_kit=admin_kit,
            submit_token=payload.submit_token,
        )
    except PhysicalControllerError as exc:
        raise physical_controller_error(exc) from exc
    session.expire_all()
    refreshed = session.get(PhysicalFederationJob, job_id)
    if not refreshed:
        raise HTTPException(status_code=500, detail="Physical job persistence failed")
    return physical_job_view(refreshed, config)


@app.post("/api/physical/jobs/{job_id}:sync")
def sync_physical_job(
    job_id: str,
    request: Request,
    session: SessionDep,
    config: SettingsDep,
) -> dict[str, Any]:
    require_physical_operator(request, config)
    controller, admin_kit = build_physical_controller(session, config)
    try:
        controller.status(job_id, admin_kit=admin_kit)
    except PhysicalControllerError as exc:
        raise physical_controller_error(exc) from exc
    session.expire_all()
    job = session.get(PhysicalFederationJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Physical job not found")
    return physical_job_view(job, config)


@app.post("/api/physical/jobs/{job_id}:abort")
def abort_physical_job(
    job_id: str,
    request: Request,
    session: SessionDep,
    config: SettingsDep,
) -> dict[str, Any]:
    require_physical_operator(request, config)
    controller, admin_kit = build_physical_controller(session, config)
    try:
        controller.abort(job_id, admin_kit=admin_kit)
    except PhysicalControllerError as exc:
        raise physical_controller_error(exc) from exc
    session.expire_all()
    job = session.get(PhysicalFederationJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Physical job not found")
    return physical_job_view(job, config)


@app.post("/api/physical/jobs/{job_id}:retry")
def retry_physical_job(
    job_id: str,
    payload: PhysicalJobApproval,
    request: Request,
    session: SessionDep,
    config: SettingsDep,
) -> dict[str, Any]:
    require_physical_operator(request, config)
    controller, admin_kit = build_physical_controller(session, config)
    try:
        controller.retry(
            job_id,
            admin_kit=admin_kit,
            submit_token=payload.submit_token,
        )
    except PhysicalControllerError as exc:
        raise physical_controller_error(exc) from exc
    session.expire_all()
    job = session.get(PhysicalFederationJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Physical job not found")
    job.approved_by = payload.approved_by
    job.approval_note = payload.note
    session.add(job)
    session.commit()
    session.refresh(job)
    return physical_job_view(job, config)


@app.post("/api/physical/jobs/{job_id}:resume")
def resume_physical_job(
    job_id: str,
    payload: PhysicalJobApproval,
    request: Request,
    session: SessionDep,
    config: SettingsDep,
) -> dict[str, Any]:
    require_physical_operator(request, config)
    controller, admin_kit = build_physical_controller(session, config)
    try:
        controller.resume(
            job_id,
            admin_kit=admin_kit,
            submit_token=payload.submit_token,
        )
    except PhysicalControllerError as exc:
        raise physical_controller_error(exc) from exc
    session.expire_all()
    job = session.get(PhysicalFederationJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Physical job not found")
    return physical_job_view(job, config)


@app.post("/api/physical/jobs/{job_id}:verify-model")
def verify_physical_global_model(
    job_id: str,
    payload: PhysicalModelVerification,
    request: Request,
    session: SessionDep,
    config: SettingsDep,
) -> dict[str, Any]:
    """Bind a completed 3/3 job to a coordinator-local model digest.

    The supplied path is used only inside the coordinator and is never included
    in the response or persisted in an audit payload exposed to the browser.
    """
    require_physical_operator(request, config)
    controller, _admin_kit = build_physical_controller(session, config)
    try:
        receipt = controller.verify_global_model(
            job_id,
            Path(payload.model_path),
            expected_sha256=payload.expected_sha256,
        )
    except PhysicalControllerError as exc:
        raise physical_controller_error(exc) from exc
    session.expire_all()
    return receipt


def _read_json_if_present(path) -> dict[str, Any] | None:  # type: ignore[no-untyped-def]
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def step_agent_receipt(config: Settings) -> dict[str, Any] | None:
    """Load a metadata-only receipt from a successful guarded Step call.

    The receipt is produced only after structured-output validation and the
    output safety gate succeed. It intentionally has no prompt, completion,
    API key, image, identifier, or aggregate value to expose through the API.
    """
    return _read_json_if_present(
        config.artifact_root / "step-agent-inference" / "last-inference.json"
    )


@app.get("/api/system/step-agent")
def get_step_agent_runtime(config: SettingsDep) -> dict[str, Any]:
    receipt = step_agent_receipt(config)
    if receipt:
        return {"available": True, "receipt": receipt}
    return {
        "available": False,
        "configured": bool(config.step_api_key and config.rarelink_allow_llm),
        "model": config.step_model if config.step_api_key else None,
        "boundary": (
            "A live receipt appears only after a guarded Step Agent request succeeds; "
            "configuration alone is not presented as a successful model call."
        ),
    }


def _sha256_file(path) -> str:  # type: ignore[no-untyped-def]
    """Return a file digest without exposing the file's contents to the API."""
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def msd_run_receipt(config: Settings) -> dict[str, Any] | None:
    """Load aggregate-only evidence from the completed DGX Spark MSD run.

    This is intentionally separate from the interactive workflow sandbox: the
    endpoint only reads the committed run receipt and never returns images,
    labels, case IDs, credentials, or model weights.
    """
    root = config.artifact_root / "spark-msd-real-20260720"
    summary_path = root / "fedavg-summary.json"
    if not summary_path.exists():
        return None
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    metric_paths = sorted((root / "metrics").glob("site-*-round-*.json"))
    metrics = [json.loads(path.read_text(encoding="utf-8")) for path in metric_paths]
    return {
        "available": True,
        "dataset": "MSD Task01 · public four-modal brain tumour MRI",
        "execution": {
            "status": summary.get("status"),
            "strategy": summary.get("strategy"),
            "rounds": summary.get("rounds"),
            "local_epochs": summary.get("local_epochs"),
            "elapsed_seconds": summary.get("elapsed_seconds"),
            "peak_gpu_memory_mb": summary.get("peak_gpu_memory_mb"),
            "simulated_sites": summary.get("simulated_sites"),
        },
        "aggregate_metrics": summary.get("metrics"),
        "files": [
            {"name": "fedavg-summary.json", "sha256": _sha256_file(summary_path)},
            *[
                {"name": path.name, "sha256": _sha256_file(path)}
                for path in metric_paths
            ],
        ],
        "site_receipts": [
            {
                "site_id": metric.get("site_id"),
                "round": metric.get("round"),
                "dice": metric.get("mean_dice"),
                "hd95": metric.get("hd95"),
                "elapsed_seconds": metric.get("elapsed_seconds"),
                "peak_gpu_memory_mb": metric.get("peak_gpu_memory_mb"),
            }
            for metric in metrics
        ],
        "boundary": (
            "24-case public MSD Task01 engineering smoke test on one Spark with three logical "
            "sites; not paediatric, clinical-performance, or real cross-hospital evidence."
        ),
    }


@app.get("/api/system/msd-run")
def get_msd_run(config: SettingsDep) -> dict[str, Any]:
    return msd_run_receipt(config) or {"available": False}


@app.post("/api/system/msd-run:verify")
def verify_msd_run(config: SettingsDep) -> dict[str, Any]:
    receipt = msd_run_receipt(config)
    if not receipt:
        raise HTTPException(status_code=404, detail="No committed MSD Spark receipt is available")
    metrics = receipt["aggregate_metrics"] or {}
    site_receipts = receipt["site_receipts"]
    expected_sites = {"site-a", "site-b", "site-c"}
    checks = {
        "three_logical_sites": {item["site_id"] for item in site_receipts} == expected_sites,
        "all_three_updates_aggregated": len(metrics.get("sites", [])) == 3,
        "global_model_persisted": receipt["execution"]["status"] == "completed_with_global_model",
        "aggregate_only_receipt": all(
            "case" not in json.dumps(item).lower() and "patient" not in json.dumps(item).lower()
            for item in site_receipts
        ),
        "integrity_hashes_present": len(receipt["files"]) == 4
        and all(len(item["sha256"]) == 64 for item in receipt["files"]),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "verified_at": utc_now(),
        "receipt": receipt,
    }


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
    cross_device = _read_json_if_present(
        config.artifact_root
        / "nvflare-secure-provision"
        / "cross-device-mtls-evidence.json"
    )
    agent_redteam = _read_json_if_present(
        config.artifact_root / "agent-redteam" / "summary.json"
    )
    public_benchmark = _read_json_if_present(
        config.artifact_root / "public-benchmark" / "latest-intake-validation.json"
    ) or _read_json_if_present(
        config.artifact_root / "public-benchmark" / "msd-task01-validation.json"
    )
    local_inference = _read_json_if_present(
        config.artifact_root / "spark-local-inference" / "last-inference.json"
    )
    local_inference_redteam = _read_json_if_present(
        config.artifact_root / "spark-local-inference" / "redteam-summary.json"
    )
    local_inference_verification = _read_json_if_present(
        config.artifact_root / "spark-local-inference" / "verification.json"
    )
    local_inference_benchmark = _read_json_if_present(
        config.artifact_root / "spark-local-inference" / "concurrency-benchmark.json"
    )
    step_inference = step_agent_receipt(config)
    return {
        "repeated_benchmark": repeated,
        "mtls_provisioning": provisioned,
        "mtls_runtime": runtime,
        "cross_device_mtls": cross_device,
        "agent_redteam": agent_redteam,
        "public_benchmark": public_benchmark,
        "local_inference": local_inference,
        "local_inference_redteam": local_inference_redteam,
        "local_inference_verification": local_inference_verification,
        "local_inference_benchmark": local_inference_benchmark,
        "step_inference": step_inference,
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
