import importlib.util
import io
import json
import secrets
import zipfile
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Annotated, Any

import yaml
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlmodel import Session, select

from rarelink import __version__
from rarelink.config import Settings, get_settings
from rarelink.database import (
    DatabaseSchemaError,
    create_db_and_tables,
    get_session,
    verify_production_schema,
)
from rarelink.domain import (
    ApprovalRequest,
    CapabilityRead,
    ExperimentContract,
    ExperimentCreate,
    ExperimentStatus,
    PhysicalApprovalRevocation,
    PhysicalJobApproval,
    PhysicalJobCreate,
    PhysicalJobStatus,
    PhysicalModelReleaseApproval,
    PhysicalModelVerification,
    PhysicalPrivacyBudgetCreate,
    PhysicalPrivacySpendCreate,
    PhysicalSecondApproval,
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
    PhysicalControlEvent,
    PhysicalFederationJob,
    PhysicalHeartbeatReceipt,
    PhysicalJobApprovalRecord,
    PhysicalJobApprovalRevocation,
    PhysicalPrivacyBudget,
    PhysicalPrivacySpend,
    PhysicalSite,
    Study,
    TrainingJob,
)
from rarelink.privacy import (
    PrivacyBudgetError,
    PrivacySpendInput,
    SqlPrivacyBudgetLedger,
)
from rarelink.security import (
    OfflineOIDCAdapter,
    OIDCClaimsConfig,
    OIDCValidationError,
    PhysicalPermission,
    PhysicalPermissionDenied,
    PhysicalPrincipal,
    PhysicalRole,
    PhysicalSiteScopeDenied,
    require_permission,
    require_site_scope,
    verify_heartbeat_signature,
)
from rarelink.security.http_boundary import validate_physical_cors
from rarelink.security.jwks import (
    TrustedJWKSCache,
    build_preloaded_jwks_provider,
)
from rarelink.security.model_signing import (
    ModelReleaseManifest,
    ModelSigningError,
    sign_model_release,
)
from rarelink.security.physical_rbac import PhysicalAccessControlError
from rarelink.services.agents import build_research_agent
from rarelink.services.federation import build_federation_runner
from rarelink.services.ledger import append_event, list_events
from rarelink.services.local_inference import probe_spark_inference
from rarelink.services.physical_approval import (
    PhysicalApprovalServiceError,
    canonical_contract_sha256,
    ensure_job_second_approval,
    verify_contract_unchanged,
)
from rarelink.services.physical_audit import (
    append_physical_event,
    verify_physical_event_chain,
)
from rarelink.services.physical_controller import (
    JobConflictError,
    JobNotFoundError,
    JobValidationError,
    NvflareCliAdapter,
    PhysicalControllerError,
    PhysicalFederationController,
    sha256_file,
    validate_exported_job,
)
from rarelink.services.physical_store import SqlPhysicalJobStore
from rarelink.services.policy import sanitize_site_aggregate
from rarelink.services.training_jobs import execute_training_job, recover_interrupted_jobs
from rarelink.services.workflow import InvalidTransition, transition

_oidc_jwks_provider: TrustedJWKSCache | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _oidc_jwks_provider
    validate_physical_cors(settings)
    create_db_and_tables()
    if (
        settings.rarelink_physical_mode == "physical"
        and settings.rarelink_physical_auth_mode == "oidc"
        and settings.rarelink_oidc_jwks_uri
    ):
        _oidc_jwks_provider = build_preloaded_jwks_provider(settings)
    recover_interrupted_jobs()
    try:
        yield
    finally:
        _oidc_jwks_provider = None


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
async def physical_security_headers(request, call_next):  # type: ignore[no-untyped-def]
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if request.url.path.startswith("/api/physical"):
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    if settings.app_env == "production" and request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


@app.middleware("http")
async def demo_access_gate(request, call_next):  # type: ignore[no-untyped-def]
    """Optional lightweight gate for a public competition demo.

    This is deliberately not presented as production identity management. A
    deployment sets the token in the server environment; the Vite demo client
    can send it as a header while evaluators use the same access code.
    """
    expected = settings.rarelink_demo_access_token
    if not expected or request.url.path in {
        "/api/health",
        "/api/health/live",
        "/api/health/ready",
        "/docs",
        "/openapi.json",
    }:
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


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    normalized = value if value.tzinfo else value.replace(tzinfo=UTC)
    return normalized.astimezone(UTC)


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
        "dataset_fingerprint": site.dataset_fingerprint,
        "receipt_sha256": site.receipt_sha256,
        "last_heartbeat_at": site.last_heartbeat_at,
        "contains_patient_data": False,
    }


def physical_site_is_fresh(site: PhysicalSite, config: Settings) -> bool:
    if site.last_heartbeat_at is None:
        return False
    observed_at = site.last_heartbeat_at
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=UTC)
    age = (datetime.now(UTC) - observed_at).total_seconds()
    return age <= config.rarelink_physical_heartbeat_max_age_seconds * 2


def physical_job_view(job: PhysicalFederationJob, config: Settings) -> dict[str, Any]:
    approval_count = int(bool(job.proposed_by)) + int(bool(job.second_approved_by))
    if config.rarelink_physical_mode == "physical":
        approval_expires_at = as_utc(job.second_approval_expires_at)
        approval_valid = bool(
            job.second_approved_by
            and approval_expires_at
            and approval_expires_at > datetime.now(UTC)
            and not job.second_approval_revocation_id
        )
        if job.second_approval_revocation_id:
            approval_state = "SECOND_APPROVAL_REVOKED"
        elif approval_valid:
            approval_state = "SECOND_APPROVAL_RECORDED"
        elif job.second_approved_by:
            approval_state = "SECOND_APPROVAL_EXPIRED"
        else:
            approval_state = "SECOND_APPROVAL_PENDING"
        approval_required = 2
    else:
        approval_state = "LEGACY_SINGLE_REQUEST"
        approval_required = 1
        approval_expires_at = None
        approval_valid = True
    return {
        "deployment_mode": config.rarelink_physical_mode,
        "id": job.id,
        "study_id": job.study_id,
        "external_job_id": job.external_job_id,
        "strategy": job.strategy,
        "status": job.status,
        "contract_sha256": job.contract_sha256,
        "expected_sites": as_json(job.expected_sites_json, []),
        "dataset_fingerprints": as_json(job.dataset_fingerprints_json, {}),
        "connected_sites": as_json(job.connected_sites_json, []),
        "total_rounds": job.total_rounds,
        "local_epochs": job.local_epochs,
        "current_round": job.current_round,
        "received_updates": job.received_updates,
        "quorum_required": job.quorum_required,
        "approval_count": approval_count,
        "approval_required": approval_required,
        "approval_state": approval_state,
        "approval_valid": approval_valid,
        "approval_expires_at": approval_expires_at,
        "approval_revoked_at": as_utc(job.second_approval_revoked_at),
        "global_model_sha256": job.global_model_sha256,
        "model_release": (
            {
                "manifest_sha256": job.model_release_manifest_sha256,
                "key_fingerprint_sha256": job.model_signing_key_fingerprint_sha256,
                "signature": job.global_model_signature,
                "released_at": as_utc(job.model_released_at),
                "algorithm": "Ed25519",
            }
            if job.global_model_signature
            else None
        ),
        "metrics": as_json(job.metrics_json),
        "error": job.error,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "completed_at": job.completed_at,
        "contains_patient_data": False,
    }


def physical_privacy_budget_view(
    budget: PhysicalPrivacyBudget,
    spends: list[PhysicalPrivacySpend],
) -> dict[str, Any]:
    return {
        "schema_version": "rarelink-privacy-budget-view-v1",
        "budget_id": budget.id,
        "job_id": budget.job_id,
        "contract_sha256": budget.contract_sha256,
        "max_epsilon": budget.max_epsilon,
        "delta": budget.delta,
        "consumed_epsilon": budget.consumed_epsilon,
        "remaining_epsilon": max(0.0, budget.max_epsilon - budget.consumed_epsilon),
        "status": budget.status,
        "ledger_head_sha256": budget.ledger_head_sha256,
        "spends": [
            {
                "spend_id": spend.id,
                "site_id": spend.site_id,
                "round_number": spend.round_number,
                "cumulative_epsilon": spend.cumulative_epsilon,
                "delta": spend.delta,
                "accountant": spend.accountant,
                "optimizer_steps": spend.optimizer_steps,
                "receipt_sha256": spend.receipt_sha256,
                "created_at": spend.created_at,
            }
            for spend in spends
        ],
        "raw_gradient_exported": False,
        "patient_data_exported": False,
    }


def physical_event_view(event: PhysicalControlEvent) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "action": event.action,
        "actor": event.actor,
        "resource_type": event.resource_type,
        "resource_id": event.resource_id,
        "outcome": event.outcome,
        "payload": as_json(event.payload_json, {}),
        "previous_hash": event.previous_hash,
        "event_hash": event.event_hash,
        "algorithm": event.algorithm,
        "key_id": event.key_id,
        "created_at": event.created_at,
        "contains_patient_data": False,
        "contains_secret": False,
        "contains_local_path": False,
    }


def require_physical_enabled(config: Settings) -> None:
    if config.rarelink_physical_mode == "disabled":
        raise HTTPException(
            status_code=503,
            detail="Physical federation control plane is disabled",
        )
    if (
        config.rarelink_physical_mode == "physical"
        and len(config.rarelink_audit_hmac_key) < 32
    ):
        raise HTTPException(
            status_code=503,
            detail="Physical mode requires a managed audit HMAC key",
        )


def require_physical_principal(
    request: Request,
    config: Settings,
    permission: PhysicalPermission,
) -> PhysicalPrincipal:
    require_physical_enabled(config)
    if config.rarelink_physical_auth_mode == "legacy-token":
        if config.rarelink_physical_mode == "physical":
            raise HTTPException(
                status_code=503,
                detail="Physical mode requires OIDC operator authentication",
            )
        expected = config.rarelink_physical_operator_token
        if not expected:
            raise HTTPException(
                status_code=503,
                detail="Physical federation operator authentication is not configured",
            )
        provided = request.headers.get("X-RareLink-Operator-Token", "")
        if not secrets.compare_digest(provided, expected):
            raise HTTPException(
                status_code=401,
                detail="Physical federation operator token required",
            )
        principal = PhysicalPrincipal(
            subject_id="legacy-isolated-operator",
            roles=frozenset(PhysicalRole),
            organization="isolated-integration",
        )
    else:
        authorization = request.headers.get("Authorization", "")
        scheme, separator, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not separator or not token:
            raise HTTPException(status_code=401, detail="OIDC bearer token required")
        try:
            oidc_config = OIDCClaimsConfig(
                issuer=config.rarelink_oidc_issuer,
                audience=config.rarelink_oidc_audience,
                role_claim=config.rarelink_oidc_roles_claim,
                organization_claim=config.rarelink_oidc_organization_claim,
                site_claim=config.rarelink_oidc_sites_claim,
            )
            if config.rarelink_oidc_jwks_uri:
                if _oidc_jwks_provider is None:
                    raise ValueError("OIDC signing-key provider is unavailable")
                trusted_jwks = _oidc_jwks_provider
            else:
                trusted_jwks = config.physical_oidc_jwks
                if not trusted_jwks.get("keys"):
                    raise ValueError("OIDC JWKS is empty")
            principal = OfflineOIDCAdapter(
                oidc_config,
                trusted_jwks,
            ).authenticate(token)
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=503,
                detail="Physical OIDC authentication is not configured",
            ) from None
        except OIDCValidationError:
            raise HTTPException(
                status_code=401,
                detail="OIDC identity validation failed",
            ) from None
    try:
        require_permission(principal, permission)
    except PhysicalPermissionDenied as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None
    return principal


def require_physical_site_scope(
    principal: PhysicalPrincipal,
    site_ids: list[str],
    config: Settings,
) -> None:
    if config.rarelink_physical_auth_mode == "legacy-token":
        return
    if not site_ids or any(not isinstance(site_id, str) for site_id in site_ids):
        raise HTTPException(status_code=409, detail="Physical site scope is invalid")
    try:
        require_site_scope(principal, frozenset(site_ids))
    except PhysicalSiteScopeDenied as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None


def require_physical_job_scope(
    principal: PhysicalPrincipal,
    job: PhysicalFederationJob,
    config: Settings,
) -> None:
    expected_sites = as_json(job.expected_sites_json, [])
    if not isinstance(expected_sites, list):
        raise HTTPException(status_code=409, detail="Physical job site scope is invalid")
    require_physical_site_scope(principal, expected_sites, config)


def physical_read_principal(
    request: Request,
    config: Settings,
    permission: PhysicalPermission,
) -> PhysicalPrincipal | None:
    """Protect production reads while preserving isolated/demo compatibility."""
    if config.rarelink_physical_mode != "physical":
        return None
    return require_physical_principal(request, config, permission)


def principal_can_read_job(
    principal: PhysicalPrincipal,
    job: PhysicalFederationJob,
) -> bool:
    expected_sites = as_json(job.expected_sites_json, [])
    return (
        isinstance(expected_sites, list)
        and bool(expected_sites)
        and all(isinstance(site_id, str) for site_id in expected_sites)
        and set(expected_sites).issubset(principal.site_ids)
    )


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


def physical_approval_error(
    exc: PhysicalApprovalServiceError | PhysicalAccessControlError,
) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


def require_current_physical_contract(
    session: Session,
    job: PhysicalFederationJob,
    config: Settings,
) -> int:
    if not job.contract_sha256:
        raise HTTPException(
            status_code=409,
            detail="Physical job predates contract locking and must be recreated",
        )
    try:
        verify_contract_unchanged(job, job.contract_sha256)
    except PhysicalApprovalServiceError as exc:
        raise physical_approval_error(exc) from exc
    require_active_physical_privacy_budget(session, job)
    approval_count = int(bool(job.proposed_by)) + int(bool(job.second_approved_by))
    if config.rarelink_physical_mode != "physical":
        return approval_count
    approval = session.exec(
        select(PhysicalJobApprovalRecord).where(
            PhysicalJobApprovalRecord.job_id == job.id
        )
    ).first()
    revocation = session.exec(
        select(PhysicalJobApprovalRevocation).where(
            PhysicalJobApprovalRevocation.job_id == job.id
        )
    ).first()
    approval_expires_at = as_utc(approval.expires_at) if approval else None
    job_approval_expires_at = as_utc(job.second_approval_expires_at)
    if (
        not approval
        or revocation is not None
        or job.second_approval_revocation_id is not None
        or approval.contract_sha256 != job.contract_sha256
        or approval.approver_subject_id != job.second_approved_by
        or job.second_approved_by == job.proposed_by
        or approval_expires_at is None
        or job_approval_expires_at is None
        or approval_expires_at != job_approval_expires_at
        or approval_expires_at <= datetime.now(UTC)
    ):
        raise HTTPException(
            status_code=409,
            detail="Physical mode requires a current distinct second contract approval",
        )
    return 2


def require_active_physical_privacy_budget(
    session: Session,
    job: PhysicalFederationJob,
) -> PhysicalPrivacyBudget | None:
    """Require the immutable DP budget and exported Opacus contract when applicable."""
    if job.strategy != "fedavg_dpsgd":
        return None
    budget = session.exec(
        select(PhysicalPrivacyBudget).where(PhysicalPrivacyBudget.job_id == job.id)
    ).first()
    if (
        budget is None
        or budget.contract_sha256 != job.contract_sha256
        or budget.status != "ACTIVE"
    ):
        raise HTTPException(
            status_code=409,
            detail="DP-SGD physical jobs require an active locked privacy budget",
        )
    try:
        bundle = validate_exported_job(Path(job.job_directory))
    except PhysicalControllerError as exc:
        raise physical_controller_error(exc) from exc
    privacy_contract = bundle.privacy_contract
    if (
        bundle.bundle_sha256 != job.bundle_sha256
        or privacy_contract.get("accountant") != "rdp"
        or privacy_contract.get("delta") != budget.delta
    ):
        raise HTTPException(
            status_code=409,
            detail="DP-SGD bundle or privacy parameters changed after contract locking",
        )
    return budget


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


@app.get("/api/health/live")
def liveness() -> dict[str, str]:
    return {"status": "alive", "service": "rarelink"}


@app.get("/api/health/ready")
def readiness(
    session: SessionDep,
    config: SettingsDep,
) -> Any:
    try:
        session.execute(text("SELECT 1"))
        database_engine = session.get_bind()
        backend = database_engine.dialect.name
        if backend == "sqlite":
            if config.rarelink_physical_mode == "physical":
                raise DatabaseSchemaError("Physical mode cannot use SQLite")
            revision = "development-sqlite"
        else:
            revision = verify_production_schema(database_engine)
    except (DatabaseSchemaError, SQLAlchemyError):
        return JSONResponse(
            status_code=503,
            content={
                "status": "not_ready",
                "service": "rarelink",
                "database": "unavailable_or_stale",
            },
        )
    response = {
        "status": "ready",
        "service": "rarelink",
        "database": backend,
        "schema_revision": revision,
    }
    if (
        config.rarelink_physical_mode == "physical"
        and config.rarelink_physical_auth_mode == "oidc"
        and config.rarelink_oidc_jwks_uri
    ):
        if _oidc_jwks_provider is None:
            return JSONResponse(
                status_code=503,
                content={
                    "status": "not_ready",
                    "service": "rarelink",
                    "oidc_signing_keys": "unavailable",
                },
            )
        oidc_status = _oidc_jwks_provider.safe_status()
        if not oidc_status["loaded"] or not oidc_status["fresh"]:
            return JSONResponse(
                status_code=503,
                content={
                    "status": "not_ready",
                    "service": "rarelink",
                    "oidc_signing_keys": "unavailable",
                },
            )
        response["oidc_signing_keys"] = "ready"
    return response


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
    principal = require_physical_principal(
        request,
        config,
        PhysicalPermission.SITE_REGISTER,
    )
    require_physical_site_scope(principal, [payload.site_id], config)
    if session.get(PhysicalSite, payload.site_id):
        raise HTTPException(status_code=409, detail="Physical site is already registered")
    site = PhysicalSite(
        site_id=payload.site_id,
        display_name=payload.display_name,
        organization=payload.organization,
        expected=payload.expected,
    )
    session.add(site)
    append_physical_event(
        session,
        action="site.register",
        actor=principal.subject_id,
        resource_type="physical-site",
        resource_id=site.site_id,
        outcome="accepted",
        payload={
            "organization": site.organization,
            "expected": site.expected,
        },
        hmac_key=config.rarelink_audit_hmac_key,
    )
    session.commit()
    session.refresh(site)
    return physical_site_view(site, config)


@app.get("/api/physical/sites")
def list_physical_sites(
    request: Request,
    session: SessionDep,
    config: SettingsDep,
) -> list[dict[str, Any]]:
    statement = select(PhysicalSite).order_by(PhysicalSite.site_id)
    principal = physical_read_principal(
        request,
        config,
        PhysicalPermission.CONTROL_STATE_READ,
    )
    if principal is not None:
        statement = statement.where(
            PhysicalSite.site_id.in_(sorted(principal.site_ids))
        )
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
    site.dataset_fingerprint = payload.dataset_fingerprint
    site.receipt_sha256 = payload.receipt_sha256
    site.heartbeat_json = json.dumps(serialized, ensure_ascii=False, sort_keys=True)
    site.last_heartbeat_at = utc_now()
    site.updated_at = utc_now()
    active_states = {
        PhysicalJobStatus.APPROVAL_PENDING,
        PhysicalJobStatus.SUBMITTED,
        PhysicalJobStatus.WAITING_FOR_SITES,
        PhysicalJobStatus.RUNNING,
    }
    active_jobs = session.exec(
        select(PhysicalFederationJob).where(
            PhysicalFederationJob.status.in_(active_states)
        )
    ).all()
    for job in active_jobs:
        expected_sites = set(as_json(job.expected_sites_json, []))
        if site_id not in expected_sites:
            continue
        expected_fingerprint = as_json(job.dataset_fingerprints_json, {}).get(site_id)
        if (
            not payload.dataset_fingerprint
            or payload.dataset_fingerprint != expected_fingerprint
        ):
            job.status = PhysicalJobStatus.FAILED
            job.error = "DATASET_VERSION_CHANGED"
            job.updated_at = utc_now()
            site.status = PhysicalSiteStatus.DEGRADED
            session.add(job)
            append_physical_event(
                session,
                action="job.dataset-version-invalidated",
                actor=site_id,
                resource_type="physical-job",
                resource_id=job.id,
                outcome="failed",
                payload={
                    "error_code": "DATASET_VERSION_CHANGED",
                    "site_id": site_id,
                    "new_dataset_fingerprint": payload.dataset_fingerprint,
                    "expected_dataset_fingerprint": expected_fingerprint,
                },
                hmac_key=config.rarelink_audit_hmac_key,
            )
    session.add(receipt)
    session.add(site)
    append_physical_event(
        session,
        action="site.heartbeat-accepted",
        actor=site_id,
        resource_type="physical-site",
        resource_id=site_id,
        outcome="accepted",
        payload={
            "heartbeat_id": payload.heartbeat_id,
            "status": site.status,
            "dataset_fingerprint": payload.dataset_fingerprint,
            "receipt_sha256": payload.receipt_sha256,
            "current_job_id": payload.current_job_id,
            "current_round": payload.current_round,
        },
        hmac_key=config.rarelink_audit_hmac_key,
    )
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
    principal = require_physical_principal(
        request,
        config,
        PhysicalPermission.CONTRACT_CREATE,
    )
    if payload.study_id and not session.get(Study, payload.study_id):
        raise HTTPException(status_code=422, detail="Linked study does not exist")
    expected_sites = list(dict.fromkeys(payload.expected_sites))
    if len(expected_sites) != len(payload.expected_sites):
        raise HTTPException(status_code=422, detail="Expected physical sites must be unique")
    require_physical_site_scope(principal, expected_sites, config)
    registered_sites = session.exec(
        select(PhysicalSite).where(PhysicalSite.site_id.in_(expected_sites))
    ).all()
    registered = {site.site_id for site in registered_sites}
    missing = sorted(set(expected_sites) - registered)
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"Expected physical sites are not registered: {', '.join(missing)}",
        )
    unready = sorted(
        site.site_id
        for site in registered_sites
        if site.status != PhysicalSiteStatus.READY
        or not site.data_ready
        or not site.dataset_fingerprint
        or not physical_site_is_fresh(site, config)
    )
    if unready:
        raise HTTPException(
            status_code=409,
            detail=(
                "Physical sites require READY status and a verified dataset receipt: "
                + ", ".join(unready)
            ),
        )
    dataset_fingerprints = {
        site.site_id: site.dataset_fingerprint for site in registered_sites
    }
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
        dataset_fingerprints_json=json.dumps(
            dataset_fingerprints,
            sort_keys=True,
        ),
        total_rounds=bundle.total_rounds,
        local_epochs=bundle.local_epochs,
        quorum_required=len(expected_sites),
        job_directory=payload.job_directory,
        proposed_by=principal.subject_id,
        proposer_roles_json=json.dumps(
            sorted(role.value for role in principal.roles),
            separators=(",", ":"),
        ),
    )
    try:
        job.contract_sha256 = canonical_contract_sha256(job)
    except PhysicalApprovalServiceError as exc:
        raise physical_approval_error(exc) from exc
    session.add(job)
    append_physical_event(
        session,
        action="job.contract-created",
        actor=principal.subject_id,
        resource_type="physical-job",
        resource_id=job.id,
        outcome="approval-pending",
        payload={
            "strategy": job.strategy,
            "bundle_sha256": job.bundle_sha256,
            "contract_sha256": job.contract_sha256,
            "expected_sites": expected_sites,
            "dataset_fingerprints": dataset_fingerprints,
            "total_rounds": job.total_rounds,
            "local_epochs": job.local_epochs,
            "quorum_required": job.quorum_required,
        },
        hmac_key=config.rarelink_audit_hmac_key,
    )
    session.commit()
    session.refresh(job)
    return physical_job_view(job, config)


@app.get("/api/physical/jobs")
def list_physical_jobs(
    request: Request,
    session: SessionDep,
    config: SettingsDep,
) -> list[dict[str, Any]]:
    statement = select(PhysicalFederationJob).order_by(PhysicalFederationJob.created_at.desc())
    jobs = list(session.exec(statement).all())
    principal = physical_read_principal(
        request,
        config,
        PhysicalPermission.CONTROL_STATE_READ,
    )
    if principal is not None:
        jobs = [job for job in jobs if principal_can_read_job(principal, job)]
    return [physical_job_view(job, config) for job in jobs]


@app.post("/api/physical/jobs/{job_id}/privacy-budget", status_code=201)
def create_physical_privacy_budget(
    job_id: str,
    payload: PhysicalPrivacyBudgetCreate,
    request: Request,
    session: SessionDep,
    config: SettingsDep,
) -> dict[str, Any]:
    principal = require_physical_principal(
        request,
        config,
        PhysicalPermission.PRIVACY_BUDGET_MANAGE,
    )
    job = session.get(PhysicalFederationJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Physical job not found")
    require_physical_job_scope(principal, job, config)
    if job.status != PhysicalJobStatus.APPROVAL_PENDING:
        raise HTTPException(
            status_code=409,
            detail="Privacy budget must be locked before physical job submission",
        )
    if not job.contract_sha256:
        raise HTTPException(status_code=409, detail="Physical contract is not locked")
    try:
        receipt = SqlPrivacyBudgetLedger(session).create(
            job_id=job.id,
            contract_sha256=job.contract_sha256,
            max_epsilon=payload.max_epsilon,
            delta=payload.delta,
        )
    except PrivacyBudgetError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    append_physical_event(
        session,
        action="job.privacy-budget-locked",
        actor=principal.subject_id,
        resource_type="physical-job",
        resource_id=job.id,
        outcome="accepted",
        payload={
            "budget_id": receipt["budget_id"],
            "contract_sha256": receipt["contract_sha256"],
            "max_epsilon": receipt["max_epsilon"],
            "delta": receipt["delta"],
            "status": receipt["status"],
        },
        hmac_key=config.rarelink_audit_hmac_key,
    )
    session.commit()
    return receipt


@app.get("/api/physical/jobs/{job_id}/privacy-budget")
def get_physical_privacy_budget(
    job_id: str,
    request: Request,
    session: SessionDep,
    config: SettingsDep,
) -> dict[str, Any]:
    job = session.get(PhysicalFederationJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Physical job not found")
    principal = physical_read_principal(
        request,
        config,
        PhysicalPermission.CONTROL_STATE_READ,
    )
    if principal is not None:
        require_physical_job_scope(principal, job, config)
    budget = session.exec(
        select(PhysicalPrivacyBudget).where(PhysicalPrivacyBudget.job_id == job_id)
    ).first()
    if not budget:
        raise HTTPException(status_code=404, detail="Physical privacy budget not found")
    spends = list(
        session.exec(
            select(PhysicalPrivacySpend)
            .where(PhysicalPrivacySpend.budget_id == budget.id)
            .order_by(PhysicalPrivacySpend.created_at)
        ).all()
    )
    return physical_privacy_budget_view(budget, spends)


@app.post("/api/physical/jobs/{job_id}/privacy-spends", status_code=201)
def record_physical_privacy_spend(
    job_id: str,
    payload: PhysicalPrivacySpendCreate,
    request: Request,
    session: SessionDep,
    config: SettingsDep,
) -> dict[str, Any]:
    principal = require_physical_principal(
        request,
        config,
        PhysicalPermission.PRIVACY_SPEND_REPORT,
    )
    job = session.get(PhysicalFederationJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Physical job not found")
    expected_sites = as_json(job.expected_sites_json, [])
    if payload.site_id not in expected_sites:
        raise HTTPException(
            status_code=403,
            detail="Privacy receipt site is outside the locked federation contract",
        )
    require_physical_site_scope(principal, [payload.site_id], config)
    if job.status not in {
        PhysicalJobStatus.SUBMITTED,
        PhysicalJobStatus.WAITING_FOR_SITES,
        PhysicalJobStatus.RUNNING,
    }:
        raise HTTPException(
            status_code=409,
            detail="Privacy spend is accepted only while a physical job is active",
        )
    try:
        receipt = SqlPrivacyBudgetLedger(session).record(
            PrivacySpendInput(
                job_id=job.id,
                site_id=payload.site_id,
                round_number=payload.round_number,
                cumulative_epsilon=payload.cumulative_epsilon,
                delta=payload.delta,
                accountant=payload.accountant,
                optimizer_steps=payload.optimizer_steps,
            )
        )
    except PrivacyBudgetError as exc:
        append_physical_event(
            session,
            action="job.privacy-spend-rejected",
            actor=principal.subject_id,
            resource_type="physical-job",
            resource_id=job.id,
            outcome="blocked",
            payload={
                "site_id": payload.site_id,
                "round_number": payload.round_number,
                "reason_code": "PRIVACY_BUDGET_POLICY_REJECTED",
            },
            hmac_key=config.rarelink_audit_hmac_key,
        )
        session.commit()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    append_physical_event(
        session,
        action="job.privacy-spend-recorded",
        actor=principal.subject_id,
        resource_type="physical-job",
        resource_id=job.id,
        outcome="accepted",
        payload={
            "budget_id": receipt["budget_id"],
            "spend_id": receipt["spend_id"],
            "site_id": receipt["site_id"],
            "round_number": receipt["round_number"],
            "cumulative_epsilon": receipt["cumulative_epsilon"],
            "consumed_epsilon": receipt["consumed_epsilon"],
            "remaining_epsilon": receipt["remaining_epsilon"],
            "receipt_sha256": receipt["receipt_sha256"],
        },
        hmac_key=config.rarelink_audit_hmac_key,
    )
    session.commit()
    return receipt


@app.post("/api/physical/jobs/{job_id}:approve")
def approve_physical_job_contract(
    job_id: str,
    payload: PhysicalSecondApproval,
    request: Request,
    session: SessionDep,
    config: SettingsDep,
) -> dict[str, Any]:
    principal = require_physical_principal(
        request,
        config,
        PhysicalPermission.CONTRACT_APPROVE,
    )
    job = session.get(PhysicalFederationJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Physical job not found")
    require_physical_job_scope(principal, job, config)
    if job.status != PhysicalJobStatus.APPROVAL_PENDING:
        raise HTTPException(
            status_code=409,
            detail="Physical job is not awaiting contract approval",
        )
    if not job.contract_sha256:
        raise HTTPException(
            status_code=409,
            detail="Physical job predates contract locking and must be recreated",
        )
    try:
        verify_contract_unchanged(job, job.contract_sha256)
    except PhysicalApprovalServiceError as exc:
        raise physical_approval_error(exc) from exc
    require_active_physical_privacy_budget(session, job)
    existing = session.exec(
        select(PhysicalJobApprovalRecord).where(
            PhysicalJobApprovalRecord.job_id == job_id
        )
    ).first()
    if existing:
        existing_expires_at = as_utc(existing.expires_at)
        if (
            existing.approver_subject_id == principal.subject_id
            and existing.contract_sha256 == job.contract_sha256
            and existing.attestation == payload.attestation
            and job.second_approved_by == principal.subject_id
            and job.second_approved_at is not None
            and existing_expires_at is not None
            and existing_expires_at == as_utc(job.second_approval_expires_at)
            and existing_expires_at > datetime.now(UTC)
            and not job.second_approval_revocation_id
        ):
            return physical_job_view(job, config)
        raise HTTPException(
            status_code=409,
            detail="Physical job already has a distinct second approval",
        )
    try:
        contract_sha256 = ensure_job_second_approval(
            job,
            principal,
            expected_contract_sha256=job.contract_sha256,
        )
    except (PhysicalApprovalServiceError, PhysicalAccessControlError) as exc:
        raise physical_approval_error(exc) from exc
    approved_at = utc_now()
    approval_expires_at = approved_at + timedelta(
        seconds=config.rarelink_physical_approval_ttl_seconds
    )
    approval = PhysicalJobApprovalRecord(
        job_id=job.id,
        contract_sha256=contract_sha256,
        approver_subject_id=principal.subject_id,
        approver_roles_json=json.dumps(
            sorted(role.value for role in principal.roles),
            separators=(",", ":"),
        ),
        attestation=payload.attestation,
        note_sha256=sha256(payload.note.strip().encode("utf-8")).hexdigest(),
        created_at=approved_at,
        expires_at=approval_expires_at,
    )
    job.second_approved_by = principal.subject_id
    job.second_approval_note_sha256 = approval.note_sha256
    job.second_approved_at = approved_at
    job.second_approval_expires_at = approval_expires_at
    job.updated_at = approved_at
    session.add(approval)
    session.add(job)
    append_physical_event(
        session,
        action="job.contract-second-approved",
        actor=principal.subject_id,
        resource_type="physical-job",
        resource_id=job.id,
        outcome="accepted",
        payload={
            "approval_id": approval.id,
            "contract_sha256": contract_sha256,
            "attestation": approval.attestation,
            "approval_count": 2,
            "expires_at": approval_expires_at.isoformat().replace("+00:00", "Z"),
        },
        hmac_key=config.rarelink_audit_hmac_key,
    )
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Physical job approval was recorded concurrently",
        ) from None
    session.refresh(job)
    return physical_job_view(job, config)


@app.post("/api/physical/jobs/{job_id}:revoke-approval")
def revoke_physical_job_approval(
    job_id: str,
    payload: PhysicalApprovalRevocation,
    request: Request,
    session: SessionDep,
    config: SettingsDep,
) -> dict[str, Any]:
    principal = require_physical_principal(
        request,
        config,
        PhysicalPermission.CONTRACT_REVOKE,
    )
    job = session.get(PhysicalFederationJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Physical job not found")
    require_physical_job_scope(principal, job, config)
    if job.status != PhysicalJobStatus.APPROVAL_PENDING:
        raise HTTPException(
            status_code=409,
            detail="Only a pending contract approval can be revoked; abort an active job",
        )
    if not job.contract_sha256:
        raise HTTPException(status_code=409, detail="Physical contract is not locked")
    try:
        verify_contract_unchanged(job, job.contract_sha256)
    except PhysicalApprovalServiceError as exc:
        raise physical_approval_error(exc) from exc
    approval = session.exec(
        select(PhysicalJobApprovalRecord).where(
            PhysicalJobApprovalRecord.job_id == job_id
        )
    ).first()
    if not approval or approval.approver_subject_id != job.second_approved_by:
        raise HTTPException(
            status_code=409,
            detail="Physical job has no current second approval to revoke",
        )
    existing = session.exec(
        select(PhysicalJobApprovalRevocation).where(
            PhysicalJobApprovalRevocation.job_id == job_id
        )
    ).first()
    if existing:
        if (
            existing.revoked_by == principal.subject_id
            and existing.attestation == payload.attestation
            and job.second_approval_revocation_id == existing.id
        ):
            return physical_job_view(job, config)
        raise HTTPException(
            status_code=409,
            detail="Physical approval was already revoked",
        )
    revoked_at = utc_now()
    revocation = PhysicalJobApprovalRevocation(
        job_id=job.id,
        approval_id=approval.id,
        contract_sha256=job.contract_sha256,
        revoked_by=principal.subject_id,
        attestation=payload.attestation,
        reason_sha256=sha256(payload.reason.strip().encode("utf-8")).hexdigest(),
        created_at=revoked_at,
    )
    job.second_approval_revocation_id = revocation.id
    job.second_approval_revoked_at = revoked_at
    job.updated_at = revoked_at
    session.add(revocation)
    session.add(job)
    append_physical_event(
        session,
        action="job.contract-approval-revoked",
        actor=principal.subject_id,
        resource_type="physical-job",
        resource_id=job.id,
        outcome="revoked",
        payload={
            "approval_id": approval.id,
            "revocation_id": revocation.id,
            "contract_sha256": job.contract_sha256,
            "attestation": payload.attestation,
            "revoked_at": revoked_at.isoformat().replace("+00:00", "Z"),
        },
        hmac_key=config.rarelink_audit_hmac_key,
    )
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Physical approval was revoked concurrently",
        ) from None
    session.refresh(job)
    return physical_job_view(job, config)


@app.post("/api/physical/jobs/{job_id}:submit")
def submit_physical_job(
    job_id: str,
    payload: PhysicalJobApproval,
    request: Request,
    session: SessionDep,
    config: SettingsDep,
) -> dict[str, Any]:
    principal = require_physical_principal(
        request,
        config,
        PhysicalPermission.JOB_SUBMIT,
    )
    job = session.get(PhysicalFederationJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Physical job not found")
    require_physical_job_scope(principal, job, config)
    if job.status not in {"APPROVAL_PENDING", "SUBMITTED"}:
        raise HTTPException(status_code=409, detail="Physical job is not awaiting submission")
    approval_count = require_current_physical_contract(session, job, config)
    require_active_physical_privacy_budget(session, job)
    expected_fingerprints = as_json(job.dataset_fingerprints_json, {})
    current_sites = session.exec(
        select(PhysicalSite).where(
            PhysicalSite.site_id.in_(as_json(job.expected_sites_json, []))
        )
    ).all()
    mismatched = sorted(
        site.site_id
        for site in current_sites
        if site.status != PhysicalSiteStatus.READY
        or site.dataset_fingerprint != expected_fingerprints.get(site.site_id)
        or not physical_site_is_fresh(site, config)
    )
    if len(current_sites) != job.quorum_required or mismatched:
        job.status = PhysicalJobStatus.FAILED
        job.error = "DATASET_VERSION_CHANGED_OR_SITE_NOT_READY"
        job.updated_at = utc_now()
        session.add(job)
        session.commit()
        raise HTTPException(
            status_code=409,
            detail="Physical site readiness or dataset version changed after approval",
        )
    job.approved_by = principal.subject_id
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
    append_physical_event(
        session,
        action="job.submitted",
        actor=principal.subject_id,
        resource_type="physical-job",
        resource_id=job_id,
        outcome="accepted",
        payload={
            "external_job_id": refreshed.external_job_id,
            "strategy": refreshed.strategy,
            "attempt": refreshed.attempt,
            "bundle_sha256": refreshed.bundle_sha256,
            "contract_sha256": refreshed.contract_sha256,
            "approval_count": approval_count,
        },
        hmac_key=config.rarelink_audit_hmac_key,
    )
    session.commit()
    session.refresh(refreshed)
    return physical_job_view(refreshed, config)


@app.post("/api/physical/jobs/{job_id}:sync")
def sync_physical_job(
    job_id: str,
    request: Request,
    session: SessionDep,
    config: SettingsDep,
) -> dict[str, Any]:
    principal = require_physical_principal(
        request,
        config,
        PhysicalPermission.JOB_SYNC,
    )
    job = session.get(PhysicalFederationJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Physical job not found")
    require_physical_job_scope(principal, job, config)
    controller, admin_kit = build_physical_controller(session, config)
    try:
        controller.status(job_id, admin_kit=admin_kit)
    except PhysicalControllerError as exc:
        raise physical_controller_error(exc) from exc
    session.expire_all()
    job = session.get(PhysicalFederationJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Physical job not found")
    append_physical_event(
        session,
        action="job.status-synchronized",
        actor=principal.subject_id,
        resource_type="physical-job",
        resource_id=job_id,
        outcome="accepted",
        payload={
            "status": job.status,
            "external_job_id": job.external_job_id,
            "current_round": job.current_round,
            "received_updates": job.received_updates,
            "error_code": job.error,
        },
        hmac_key=config.rarelink_audit_hmac_key,
    )
    session.commit()
    session.refresh(job)
    return physical_job_view(job, config)


@app.post("/api/physical/jobs/{job_id}:abort")
def abort_physical_job(
    job_id: str,
    request: Request,
    session: SessionDep,
    config: SettingsDep,
) -> dict[str, Any]:
    principal = require_physical_principal(
        request,
        config,
        PhysicalPermission.JOB_ABORT,
    )
    job = session.get(PhysicalFederationJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Physical job not found")
    require_physical_job_scope(principal, job, config)
    controller, admin_kit = build_physical_controller(session, config)
    try:
        controller.abort(job_id, admin_kit=admin_kit)
    except PhysicalControllerError as exc:
        raise physical_controller_error(exc) from exc
    session.expire_all()
    job = session.get(PhysicalFederationJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Physical job not found")
    append_physical_event(
        session,
        action="job.aborted",
        actor=principal.subject_id,
        resource_type="physical-job",
        resource_id=job_id,
        outcome="accepted",
        payload={
            "external_job_id": job.external_job_id,
            "status": job.status,
            "attempt": job.attempt,
        },
        hmac_key=config.rarelink_audit_hmac_key,
    )
    session.commit()
    session.refresh(job)
    return physical_job_view(job, config)


@app.post("/api/physical/jobs/{job_id}:retry")
def retry_physical_job(
    job_id: str,
    payload: PhysicalJobApproval,
    request: Request,
    session: SessionDep,
    config: SettingsDep,
) -> dict[str, Any]:
    principal = require_physical_principal(
        request,
        config,
        PhysicalPermission.JOB_RETRY_RESUME,
    )
    existing = session.get(PhysicalFederationJob, job_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Physical job not found")
    require_physical_job_scope(principal, existing, config)
    if existing.error and existing.error.startswith("DATASET_VERSION_CHANGED"):
        raise HTTPException(
            status_code=409,
            detail="Dataset version changed; create and approve a new physical job contract",
        )
    require_current_physical_contract(session, existing, config)
    require_active_physical_privacy_budget(session, existing)
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
    job.approved_by = principal.subject_id
    job.approval_note = payload.note
    session.add(job)
    append_physical_event(
        session,
        action="job.retried",
        actor=principal.subject_id,
        resource_type="physical-job",
        resource_id=job_id,
        outcome="accepted",
        payload={
            "external_job_id": job.external_job_id,
            "status": job.status,
            "attempt": job.attempt,
        },
        hmac_key=config.rarelink_audit_hmac_key,
    )
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
    principal = require_physical_principal(
        request,
        config,
        PhysicalPermission.JOB_RETRY_RESUME,
    )
    existing = session.get(PhysicalFederationJob, job_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Physical job not found")
    require_physical_job_scope(principal, existing, config)
    if existing.error and existing.error.startswith("DATASET_VERSION_CHANGED"):
        raise HTTPException(
            status_code=409,
            detail="Dataset version changed; create and approve a new physical job contract",
        )
    require_current_physical_contract(session, existing, config)
    require_active_physical_privacy_budget(session, existing)
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
    append_physical_event(
        session,
        action="job.resumed",
        actor=principal.subject_id,
        resource_type="physical-job",
        resource_id=job_id,
        outcome="accepted",
        payload={
            "external_job_id": job.external_job_id,
            "status": job.status,
            "attempt": job.attempt,
        },
        hmac_key=config.rarelink_audit_hmac_key,
    )
    session.commit()
    session.refresh(job)
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
    principal = require_physical_principal(
        request,
        config,
        PhysicalPermission.MODEL_VERIFY,
    )
    job = session.get(PhysicalFederationJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Physical job not found")
    require_physical_job_scope(principal, job, config)
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
    append_physical_event(
        session,
        action="job.global-model-verified",
        actor=principal.subject_id,
        resource_type="physical-job",
        resource_id=job_id,
        outcome="accepted",
        payload={
            "model_file_name": receipt["model_file_name"],
            "global_model_sha256": receipt["global_model_sha256"],
            "verified": receipt["verified"],
        },
        hmac_key=config.rarelink_audit_hmac_key,
    )
    session.commit()
    return receipt


@app.post("/api/physical/jobs/{job_id}:sign-model-release")
def sign_physical_global_model_release(
    job_id: str,
    payload: PhysicalModelReleaseApproval,
    request: Request,
    session: SessionDep,
    config: SettingsDep,
) -> dict[str, Any]:
    """Sign a verified model digest without exporting the key or coordinator path."""
    principal = require_physical_principal(
        request,
        config,
        PhysicalPermission.MODEL_VERIFY,
    )
    job = session.get(PhysicalFederationJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Physical job not found")
    require_physical_job_scope(principal, job, config)
    if (
        job.status != PhysicalJobStatus.COMPLETED
        or not job.external_job_id
        or not job.contract_sha256
        or not job.global_model_sha256
        or not job.global_model_path
    ):
        raise HTTPException(
            status_code=409,
            detail="Only a completed and verified global model can be signed",
        )
    if not secrets.compare_digest(
        job.global_model_sha256,
        payload.expected_model_sha256,
    ):
        raise HTTPException(status_code=409, detail="Expected global model digest changed")
    configured_model_path = Path(job.global_model_path)
    model_path = configured_model_path.resolve()
    if (
        not model_path.is_file()
        or configured_model_path.is_symlink()
        or not secrets.compare_digest(sha256_file(model_path), job.global_model_sha256)
    ):
        raise HTTPException(
            status_code=409,
            detail="Global model file changed after verification",
        )
    if job.global_model_signature:
        return {
            "schema_version": "rarelink-model-release-signature-v1",
            "job_id": job.id,
            "global_model_sha256": job.global_model_sha256,
            "manifest_sha256": job.model_release_manifest_sha256,
            "key_fingerprint_sha256": job.model_signing_key_fingerprint_sha256,
            "signature": job.global_model_signature,
            "algorithm": "Ed25519",
            "released_at": as_utc(job.model_released_at),
            "verified": True,
            "private_key_exported": False,
            "private_key_path_exported": False,
            "model_path_exported": False,
            "patient_data_exported": False,
        }
    if config.rarelink_model_signing_private_key is None:
        raise HTTPException(
            status_code=503,
            detail="Global model signing key is not configured",
        )
    released_at = utc_now()
    manifest = ModelReleaseManifest(
        job_id=job.id,
        external_job_id=job.external_job_id,
        contract_sha256=job.contract_sha256,
        model_sha256=job.global_model_sha256,
        model_file_name=model_path.name,
        approved_at=released_at.isoformat(),
    )
    try:
        signed = sign_model_release(
            manifest,
            private_key_path=config.rarelink_model_signing_private_key,
        )
    except ModelSigningError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    job.global_model_signature = str(signed["signature"])
    job.model_signing_key_fingerprint_sha256 = str(
        signed["key_fingerprint_sha256"]
    )
    job.model_release_manifest_sha256 = str(signed["manifest_sha256"])
    job.model_released_at = released_at
    job.updated_at = released_at
    session.add(job)
    append_physical_event(
        session,
        action="job.global-model-release-signed",
        actor=principal.subject_id,
        resource_type="physical-job",
        resource_id=job.id,
        outcome="accepted",
        payload={
            "global_model_sha256": job.global_model_sha256,
            "manifest_sha256": job.model_release_manifest_sha256,
            "key_fingerprint_sha256": job.model_signing_key_fingerprint_sha256,
            "algorithm": "Ed25519",
            "attestation": payload.attestation,
            "released_at": released_at.isoformat().replace("+00:00", "Z"),
        },
        hmac_key=config.rarelink_audit_hmac_key,
    )
    session.commit()
    return {
        **signed,
        "job_id": job.id,
        "global_model_sha256": job.global_model_sha256,
        "released_at": released_at,
        "model_path_exported": False,
    }


@app.get("/api/physical/events")
def list_physical_events(
    request: Request,
    session: SessionDep,
    config: SettingsDep,
) -> dict[str, Any]:
    principal = require_physical_principal(
        request,
        config,
        PhysicalPermission.AUDIT_READ,
    )
    events = list(
        session.exec(
            select(PhysicalControlEvent).order_by(PhysicalControlEvent.id)
        ).all()
    )
    exported_events = events
    scope_filtered = False
    if config.rarelink_physical_mode == "physical":
        jobs = list(session.exec(select(PhysicalFederationJob)).all())
        allowed_job_ids = {
            job.id for job in jobs if principal_can_read_job(principal, job)
        }
        exported_events = [
            event
            for event in events
            if (
                event.resource_type == "physical-site"
                and event.resource_id in principal.site_ids
            )
            or (
                event.resource_type == "physical-job"
                and event.resource_id in allowed_job_ids
            )
        ]
        scope_filtered = True
    recent_events = exported_events[-200:]
    return {
        "schema_version": "rarelink-physical-audit-chain-v1",
        "verified": verify_physical_event_chain(
            events,
            hmac_key=config.rarelink_audit_hmac_key,
        ),
        "chain_event_count": len(events),
        "event_count": len(exported_events),
        "events": [physical_event_view(event) for event in recent_events],
        "truncated": len(exported_events) > 200,
        "scope_filtered": scope_filtered,
        "contains_patient_data": False,
        "contains_secret": False,
        "contains_local_path": False,
    }


@app.get("/api/physical/audit-summary")
def physical_audit_summary(
    session: SessionDep,
    config: SettingsDep,
) -> dict[str, Any]:
    events = list(
        session.exec(
            select(PhysicalControlEvent).order_by(PhysicalControlEvent.id)
        ).all()
    )
    head = events[-1] if events else None
    return {
        "schema_version": "rarelink-physical-audit-summary-v1",
        "verified": bool(events)
        and verify_physical_event_chain(
            events,
            hmac_key=config.rarelink_audit_hmac_key,
        ),
        "event_count": len(events),
        "head_event_hash": head.event_hash if head else None,
        "head_algorithm": head.algorithm if head else None,
        "updated_at": head.created_at if head else None,
        "events_exported": False,
        "actors_exported": False,
        "contains_patient_data": False,
        "contains_secret": False,
        "contains_local_path": False,
    }


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
