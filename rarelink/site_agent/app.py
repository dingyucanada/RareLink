"""FastAPI application for one hospital's physical RareLink Site Agent."""

from __future__ import annotations

import hmac
import time
import uuid
from collections.abc import Callable

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from rarelink.site_agent.checkpoint import verify_checkpoint_receipt
from rarelink.site_agent.config import SiteAgentSettings
from rarelink.site_agent.executor import SiteTaskExecutor, build_site_executor
from rarelink.site_agent.health import HealthProvider, collect_health, health_is_ready
from rarelink.site_agent.heartbeat import to_central_heartbeat
from rarelink.site_agent.receipt import ReceiptSigner
from rarelink.site_agent.schemas import (
    CheckpointMetadata,
    HealthSnapshot,
    HeartbeatEnvelope,
    TaskActionRequest,
    TaskActionResponse,
    TaskRecord,
)
from rarelink.site_agent.service import (
    CheckpointPreconditionError,
    ExecutorActionError,
    PreflightFailedError,
    TaskConflictError,
    TaskNotFoundError,
    TaskService,
)
from rarelink.site_agent.store import TaskStore


def create_site_agent_app(
    settings: SiteAgentSettings,
    *,
    executor: SiteTaskExecutor | None = None,
    health_provider: HealthProvider | None = None,
) -> FastAPI:
    app = FastAPI(
        title="RareLink Physical Site Agent",
        version="0.2.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    signer = ReceiptSigner(settings.site_id, settings.receipt_hmac_key.get_secret_value())
    store = TaskStore(settings.state_database)
    probe = health_provider or (lambda: collect_health(settings))
    checkpoint_provider = None
    if settings.checkpoint_root is not None and settings.checkpoint_receipt is not None:
        checkpoint_root = settings.checkpoint_root
        checkpoint_receipt = settings.checkpoint_receipt

        def local_checkpoint_provider(task: TaskRecord) -> CheckpointMetadata:
            return verify_checkpoint_receipt(
                receipt_path=checkpoint_receipt,
                checkpoint_root=checkpoint_root,
                task=task,
            )

        checkpoint_provider = local_checkpoint_provider
    service = TaskService(
        store,
        signer,
        executor or build_site_executor(settings),
        readiness_guard=lambda: health_is_ready(probe()),
        resource_probe=probe,
        checkpoint_provider=checkpoint_provider,
        require_checkpoint_for_pause=settings.require_checkpoint_for_pause,
        require_checkpoint_for_recover=settings.require_checkpoint_for_recover,
    )
    service.reconcile_interrupted_transitions()
    bearer = HTTPBearer(auto_error=False)

    def require_token(
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer),  # noqa: B008
    ) -> None:
        supplied = credentials.credentials if credentials else ""
        expected = settings.api_token.get_secret_value()
        if credentials is None or credentials.scheme.lower() != "bearer" or not hmac.compare_digest(
            supplied, expected
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid site-agent credential",
                headers={"WWW-Authenticate": "Bearer"},
            )

    def handle_action(action: Callable[[], TaskActionResponse]) -> TaskActionResponse:
        try:
            return action()
        except TaskNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except TaskConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ExecutorActionError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except PreflightFailedError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except CheckpointPreconditionError as exc:
            raise HTTPException(status_code=412, detail=str(exc)) from exc

    @app.get("/health/live")
    def live() -> dict[str, object]:
        return {
            "status": "alive",
            "service": "rarelink-site-agent",
            "patient_data_exported": False,
        }

    @app.get(
        "/v1/site/ready",
        response_model=HealthSnapshot,
        dependencies=[Depends(require_token)],
    )
    def ready() -> HealthSnapshot:
        return probe()

    @app.get(
        "/v1/site/heartbeat",
        response_model=HeartbeatEnvelope,
        dependencies=[Depends(require_token)],
    )
    def heartbeat() -> HeartbeatEnvelope:
        health = probe()
        tasks = service.list_tasks()
        timestamp = int(time.time())
        heartbeat_id = f"heartbeat-{uuid.uuid4().hex}"
        payload = to_central_heartbeat(
            heartbeat_id=heartbeat_id,
            health=health,
            tasks=tasks,
        )
        digest, signature = signer.sign_heartbeat(
            timestamp=timestamp,
            heartbeat_id=heartbeat_id,
            payload=payload,
        )
        return HeartbeatEnvelope(
            site_id=settings.site_id,
            timestamp=timestamp,
            heartbeat_id=heartbeat_id,
            payload=payload,
            payload_sha256=digest,
            key_id=signer.key_id,
            signature=signature,
        )

    @app.get(
        "/v1/tasks",
        response_model=list[TaskRecord],
        dependencies=[Depends(require_token)],
    )
    def list_tasks() -> list[TaskRecord]:
        return service.list_tasks()

    @app.post(
        "/v1/tasks/start",
        response_model=TaskActionResponse,
        dependencies=[Depends(require_token)],
    )
    def start_task(request: TaskActionRequest) -> TaskActionResponse:
        return handle_action(lambda: service.start(request))

    @app.post(
        "/v1/tasks/stop",
        response_model=TaskActionResponse,
        dependencies=[Depends(require_token)],
    )
    def stop_task(request: TaskActionRequest) -> TaskActionResponse:
        return handle_action(lambda: service.stop(request))

    @app.post(
        "/v1/tasks/pause",
        response_model=TaskActionResponse,
        dependencies=[Depends(require_token)],
    )
    def pause_task(request: TaskActionRequest) -> TaskActionResponse:
        return handle_action(lambda: service.pause(request))

    @app.post(
        "/v1/tasks/recover",
        response_model=TaskActionResponse,
        dependencies=[Depends(require_token)],
    )
    def recover_task(request: TaskActionRequest) -> TaskActionResponse:
        return handle_action(lambda: service.recover(request))

    return app
