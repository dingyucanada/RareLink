"""Read-only field acceptance for three independently deployed physical sites."""

from __future__ import annotations

import hashlib
import json
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Literal, Protocol
from urllib.parse import urljoin, urlparse

from pydantic import BaseModel, Field, field_validator, model_validator

SHA256 = r"^[0-9a-f]{64}$"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
REQUIRED_SITE_CHECKS = {
    "gpu",
    "memory",
    "disk",
    "certificate",
    "dependencies",
    "dataset_manifest",
}


class PhysicalFieldAcceptanceError(RuntimeError):
    """A field endpoint or its evidence failed the locked acceptance contract."""


class PhysicalSiteTarget(BaseModel):
    model_config = {"extra": "forbid"}

    site_id: str = Field(pattern=r"^[a-z][a-z0-9-]{2,62}$")
    base_url: str = Field(min_length=8, max_length=500)
    device_attestation_sha256: str | None = Field(default=None, pattern=SHA256)

    @field_validator("base_url")
    @classmethod
    def normalize_url(cls, value: str) -> str:
        return value.rstrip("/")


class PhysicalFieldAcceptancePlan(BaseModel):
    """Non-secret plan safe to commit after replacing real host names if required."""

    model_config = {"extra": "forbid"}

    schema_version: Literal["rarelink-physical-field-acceptance-plan-v1"]
    coordinator_base_url: str = Field(min_length=8, max_length=500)
    sites: list[PhysicalSiteTarget] = Field(min_length=3, max_length=3)
    job_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{1,127}$")
    contract_sha256: str = Field(pattern=SHA256)
    expected_rounds: int = Field(ge=1, le=1000)
    quorum_required: Literal[3] = 3
    require_completed_job: bool = False
    require_clients_connected: bool = True
    expected_model_sha256: str | None = Field(default=None, pattern=SHA256)
    requested_evidence_level: Literal["L2", "L3-candidate"] = "L3-candidate"
    allow_loopback_http: bool = False

    @field_validator("coordinator_base_url")
    @classmethod
    def normalize_url(cls, value: str) -> str:
        return value.rstrip("/")

    @model_validator(mode="after")
    def validate_topology(self) -> PhysicalFieldAcceptancePlan:
        site_ids = [site.site_id for site in self.sites]
        if len(set(site_ids)) != 3:
            raise ValueError("Field acceptance requires three distinct site identities")
        urls = [self.coordinator_base_url, *(site.base_url for site in self.sites)]
        parsed = [urlparse(url) for url in urls]
        for item in parsed:
            if item.username or item.password or item.query or item.fragment:
                raise ValueError("Acceptance URLs cannot contain credentials, query, or fragment")
            if item.path not in {"", "/"}:
                raise ValueError("Acceptance URLs must be service origins without paths")
            loopback = item.hostname in {"127.0.0.1", "::1", "localhost"}
            if item.scheme != "https" and not (
                self.allow_loopback_http and item.scheme == "http" and loopback
            ):
                raise ValueError("Acceptance endpoints require HTTPS")
        host_ports = {(item.hostname, item.port) for item in parsed[1:]}
        if self.requested_evidence_level == "L3-candidate":
            if len(host_ports) != 3:
                raise ValueError("L3-candidate requires three distinct site endpoints")
            if any(site.device_attestation_sha256 is None for site in self.sites):
                raise ValueError("L3-candidate requires a device attestation for every site")
            attestations = [site.device_attestation_sha256 for site in self.sites]
            if len(set(attestations)) != 3:
                raise ValueError("Device attestations must be distinct")
            if self.allow_loopback_http:
                raise ValueError("L3-candidate cannot allow loopback HTTP")
        if self.require_completed_job and self.expected_model_sha256 is None:
            raise ValueError("Completed-job acceptance requires the expected model digest")
        return self


class JSONTransport(Protocol):
    def get_json(self, url: str, *, headers: dict[str, str]) -> Any: ...


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


class StrictJSONTransport:
    """TLS-verifying, no-redirect, bounded JSON transport."""

    def __init__(self, *, timeout_seconds: float = 10) -> None:
        if not 0.1 <= timeout_seconds <= 60:
            raise ValueError("timeout_seconds must be in [0.1, 60]")
        self.timeout_seconds = timeout_seconds
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=ssl.create_default_context()),
            _NoRedirect(),
        )

    def get_json(self, url: str, *, headers: dict[str, str]) -> Any:
        request = urllib.request.Request(
            url,
            headers={
                **headers,
                "Accept": "application/json",
                "User-Agent": "RareLink-Physical-Acceptance/1",
            },
            method="GET",
        )
        try:
            with self.opener.open(request, timeout=self.timeout_seconds) as response:
                content_type = response.headers.get_content_type()
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                status = response.status
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise PhysicalFieldAcceptanceError("A field endpoint is unavailable") from exc
        if status != 200:
            raise PhysicalFieldAcceptanceError("A field endpoint returned a non-success status")
        if content_type != "application/json" or len(raw) > MAX_RESPONSE_BYTES:
            raise PhysicalFieldAcceptanceError("A field endpoint returned an unsafe response")
        try:
            return json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PhysicalFieldAcceptanceError("A field endpoint returned invalid JSON") from exc


@dataclass(frozen=True)
class FieldAcceptanceCredentials:
    coordinator_bearer_token: str
    site_bearer_tokens: dict[str, str]

    def validate(self, expected_sites: set[str]) -> None:
        if len(self.coordinator_bearer_token) < 16:
            raise PhysicalFieldAcceptanceError("Coordinator credential is unavailable")
        if set(self.site_bearer_tokens) != expected_sites or any(
            len(value) < 16 for value in self.site_bearer_tokens.values()
        ):
            raise PhysicalFieldAcceptanceError("A site credential is unavailable")


def _endpoint_hash(url: str) -> str:
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.hostname}:{parsed.port or 443}"
    return hashlib.sha256(origin.encode()).hexdigest()


def _get(
    transport: JSONTransport,
    base_url: str,
    path: str,
    token: str,
) -> Any:
    return transport.get_json(
        urljoin(f"{base_url}/", path.lstrip("/")),
        headers={"Authorization": f"Bearer {token}"},
    )


def _site_receipt(
    target: PhysicalSiteTarget,
    *,
    health: Any,
    tasks: Any,
    job_id: str,
    require_completed: bool,
) -> dict[str, Any]:
    if not isinstance(health, dict) or health.get("ready") is not True:
        raise PhysicalFieldAcceptanceError("A physical site is not ready")
    checks = health.get("checks")
    if not isinstance(checks, dict) or not REQUIRED_SITE_CHECKS.issubset(checks):
        raise PhysicalFieldAcceptanceError("A physical site omitted required health checks")
    for check_name in REQUIRED_SITE_CHECKS:
        check = checks[check_name]
        if not isinstance(check, dict) or check.get("ok") is not True:
            raise PhysicalFieldAcceptanceError("A physical site failed a required health check")
    if not isinstance(tasks, list):
        raise PhysicalFieldAcceptanceError("A physical site task response is invalid")
    matching = [item for item in tasks if isinstance(item, dict) and item.get("task_id") == job_id]
    if len(matching) > 1:
        raise PhysicalFieldAcceptanceError("A physical site reported duplicate job tasks")
    task = matching[0] if matching else None
    if require_completed and (
        task is None or task.get("state") not in {"COMPLETED", "RUNNING"}
    ):
        raise PhysicalFieldAcceptanceError("A completed field job has no site task evidence")
    return {
        "site_id": target.site_id,
        "endpoint_sha256": _endpoint_hash(target.base_url),
        "device_attestation_sha256": target.device_attestation_sha256,
        "ready": True,
        "required_checks_passed": sorted(REQUIRED_SITE_CHECKS),
        "job_task_observed": task is not None,
        "task_state": task.get("state") if task else None,
        "task_round": task.get("round_id") if task else None,
        "task_receipt_sha256": (
            task.get("receipt", {}).get("receipt_sha256")
            if isinstance(task, dict) and isinstance(task.get("receipt"), dict)
            else None
        ),
        "patient_data_exported": False,
        "local_path_exported": False,
    }


def run_physical_field_acceptance(
    plan: PhysicalFieldAcceptancePlan,
    *,
    credentials: FieldAcceptanceCredentials,
    transport: JSONTransport | None = None,
) -> dict[str, Any]:
    """Collect read-only evidence; it never starts, stops, or modifies a live job."""
    expected_sites = {site.site_id for site in plan.sites}
    credentials.validate(expected_sites)
    client = transport or StrictJSONTransport()
    site_receipts: list[dict[str, Any]] = []
    for site in plan.sites:
        token = credentials.site_bearer_tokens[site.site_id]
        health = _get(client, site.base_url, "/v1/site/ready", token)
        tasks = _get(client, site.base_url, "/v1/tasks", token)
        site_receipts.append(
            _site_receipt(
                site,
                health=health,
                tasks=tasks,
                job_id=plan.job_id,
                require_completed=plan.require_completed_job,
            )
        )

    coordinator_headers_token = credentials.coordinator_bearer_token
    sites = _get(
        client,
        plan.coordinator_base_url,
        "/api/physical/sites",
        coordinator_headers_token,
    )
    jobs = _get(
        client,
        plan.coordinator_base_url,
        "/api/physical/jobs",
        coordinator_headers_token,
    )
    audit = _get(
        client,
        plan.coordinator_base_url,
        "/api/physical/audit-summary",
        coordinator_headers_token,
    )
    clients = _get(
        client,
        plan.coordinator_base_url,
        f"/api/physical/jobs/{plan.job_id}/clients",
        coordinator_headers_token,
    )
    if not isinstance(sites, list) or not isinstance(jobs, list):
        raise PhysicalFieldAcceptanceError("Coordinator state response is invalid")
    site_views = {
        item.get("site_id"): item for item in sites if isinstance(item, dict)
    }
    if set(site_views) != expected_sites:
        raise PhysicalFieldAcceptanceError("Coordinator site registry does not match the plan")
    for site_id in expected_sites:
        view = site_views[site_id]
        if (
            view.get("deployment_mode") != "physical"
            or view.get("status") not in {"READY", "TRAINING"}
            or view.get("certificate_status") not in {"VALID", "valid"}
            or any(
                view.get(field) is not True
                for field in ("data_ready", "gpu_ready", "monai_ready", "nvflare_ready")
            )
        ):
            raise PhysicalFieldAcceptanceError("Coordinator reports an unready physical site")
    matching_jobs = [
        item for item in jobs if isinstance(item, dict) and item.get("id") == plan.job_id
    ]
    if len(matching_jobs) != 1:
        raise PhysicalFieldAcceptanceError("Coordinator job registry does not match the plan")
    job = matching_jobs[0]
    if (
        job.get("deployment_mode") != "physical"
        or set(job.get("expected_sites", [])) != expected_sites
        or job.get("contract_sha256") != plan.contract_sha256
        or job.get("total_rounds") != plan.expected_rounds
        or job.get("quorum_required") != 3
        or not job.get("external_job_id")
    ):
        raise PhysicalFieldAcceptanceError("Coordinator job violates the field contract")
    if not isinstance(clients, dict) or set(clients.get("connected_sites", [])) - expected_sites:
        raise PhysicalFieldAcceptanceError("Coordinator client registry is invalid")
    if plan.require_clients_connected and (
        set(clients.get("connected_sites", [])) != expected_sites
        or clients.get("all_expected_connected") is not True
    ):
        raise PhysicalFieldAcceptanceError("Not every expected client is connected")
    if (
        not isinstance(audit, dict)
        or audit.get("verified") is not True
        or audit.get("contains_patient_data") is not False
        or audit.get("contains_secret") is not False
    ):
        raise PhysicalFieldAcceptanceError("Coordinator audit chain did not verify")

    readiness: dict[str, Any] | None = None
    if plan.require_completed_job:
        readiness = _get(
            client,
            plan.coordinator_base_url,
            f"/api/physical/jobs/{plan.job_id}/review-readiness",
            coordinator_headers_token,
        )
        if (
            job.get("status") != "COMPLETED"
            or job.get("current_round") != plan.expected_rounds
            or job.get("received_updates") != 3
            or job.get("global_model_sha256") != plan.expected_model_sha256
            or not job.get("model_release")
            or not isinstance(readiness, dict)
            or readiness.get("ready_for_statistical_review") is not True
        ):
            raise PhysicalFieldAcceptanceError("Completed job is not ready for review")

    return {
        "schema_version": "rarelink-physical-field-acceptance-v1",
        "requested_evidence_level": plan.requested_evidence_level,
        "achieved_evidence_level": (
            "L3-candidate"
            if plan.requested_evidence_level == "L3-candidate"
            else "L2"
        ),
        "passed": True,
        "read_only_collection": True,
        "job_id": plan.job_id,
        "contract_sha256": plan.contract_sha256,
        "expected_sites": [site.site_id for site in plan.sites],
        "quorum_required": 3,
        "site_receipts": site_receipts,
        "coordinator": {
            "endpoint_sha256": _endpoint_hash(plan.coordinator_base_url),
            "deployment_mode": job.get("deployment_mode"),
            "external_job_id": job.get("external_job_id"),
            "job_status": job.get("status"),
            "current_round": job.get("current_round"),
            "received_updates": job.get("received_updates"),
            "connected_sites": clients.get("connected_sites"),
            "audit_head_sha256": audit.get("head_event_hash"),
            "audit_verified": True,
            "review_ready": (
                readiness.get("ready_for_statistical_review")
                if isinstance(readiness, dict)
                else None
            ),
        },
        "credentials_exported": False,
        "endpoint_urls_exported": False,
        "patient_data_exported": False,
        "local_paths_exported": False,
        "claim_boundary": (
            "L3-candidate proves read-only endpoint evidence and distinct device-attestation "
            "digests. A named deployment authority must review and sign the receipt before "
            "RareLink describes the exercise as L3 physical federation evidence."
        ),
    }
