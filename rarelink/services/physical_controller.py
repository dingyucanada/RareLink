"""Production-oriented control plane primitives for physical NVFLARE jobs.

This module deliberately has no FastAPI, SQLModel, or NVFLARE Python dependency.
The API layer supplies a persistent :class:`PhysicalJobStore` and the coordinator
host supplies the NVFLARE CLI.  Tests inject a command runner, so CI never needs
an admin kit or an NVFLARE installation.

Local filesystem paths, admin-kit locations, idempotency tokens, CLI output, and
patient-level data are internal inputs.  Every public receipt is constructed from
an allow-list and contains none of those values.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import subprocess
import threading
from collections.abc import Callable, Iterable, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from rarelink.privacy.physical_contract import validate_physical_privacy_contract

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
EXTERNAL_JOB_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
JOB_ID_PATTERNS = (
    re.compile(
        r"(?im)\b(?:external[ _-]?)?job[ _-]?id\b\s*(?:is|=|:)\s*"
        r"['\"]?([A-Za-z0-9][A-Za-z0-9._:-]{2,127})"
    ),
    re.compile(
        r"(?im)\bsubmitted\s+(?:job\s+)?['\"]?([A-Za-z0-9][A-Za-z0-9._:-]{2,127})"
    ),
)
SENSITIVE_FILE_SUFFIXES = {
    ".dcm",
    ".dicom",
    ".nii",
    ".nii.gz",
    ".key",
    ".pem",
    ".p12",
    ".pfx",
    ".jks",
    ".keystore",
}
SENSITIVE_FILE_NAMES = {
    "patient",
    "patients",
    "subject",
    "subjects",
    "client.key",
    "rootca.key",
    "admin.key",
}
SENSITIVE_JSON_KEYS = {
    "patient_id",
    "patient_name",
    "patient_birth_date",
    "medical_record_number",
    "mrn",
    "accession_number",
    "dicom_uid",
    "subject_id",
    "secret",
    "password",
    "private_key",
    "api_key",
    "admin_kit",
    "admin_kit_path",
    "submit_token",
}


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class PhysicalControllerError(RuntimeError):
    """Base error whose message is safe for an operator-facing API response."""


class JobValidationError(PhysicalControllerError):
    pass


class JobConflictError(PhysicalControllerError):
    pass


class JobNotFoundError(PhysicalControllerError):
    pass


class NvflareCliError(PhysicalControllerError):
    """NVFLARE failed; raw stdout/stderr intentionally remain undisclosed."""

    def __init__(self, operation: str, returncode: int, output_sha256: str):
        super().__init__(
            f"NVFLARE {operation} failed with exit code {returncode}; "
            f"diagnostic output sha256={output_sha256}"
        )
        self.operation = operation
        self.returncode = returncode
        self.output_sha256 = output_sha256


class PhysicalJobState(StrEnum):
    VALIDATED = "VALIDATED"
    SUBMITTED = "SUBMITTED"
    WAITING_FOR_SITES = "WAITING_FOR_SITES"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ABORTED = "ABORTED"


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


CommandRunner = Callable[[Sequence[str]], CommandResult | subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class NvflareOperationResult:
    operation: str
    returncode: int
    output_sha256: str
    payload: Any = None
    external_job_id: str | None = None
    raw_stdout: str = field(default="", repr=False, compare=False)

    def public_receipt(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "exit_code": self.returncode,
            "output_sha256": self.output_sha256,
            "external_job_id": self.external_job_id,
            "admin_kit_path_exported": False,
            "secret_exported": False,
            "patient_data_exported": False,
        }


def _default_command_runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=False, capture_output=True, text=True)


def _json_from_output(output: str) -> Any:
    stripped = output.strip()
    if not stripped:
        return None
    candidates = [stripped]
    candidates.extend(line.strip() for line in reversed(stripped.splitlines()) if line.strip())
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


def _find_job_id_in_json(value: Any) -> str | None:
    if isinstance(value, dict):
        normalized = {str(key).lower().replace("-", "_"): item for key, item in value.items()}
        for key in ("external_job_id", "job_id", "jobid"):
            candidate = normalized.get(key)
            if isinstance(candidate, (str, int)) and EXTERNAL_JOB_ID_RE.fullmatch(str(candidate)):
                return str(candidate)
        for child in value.values():
            found = _find_job_id_in_json(child)
            if found:
                return found
    if isinstance(value, list):
        for child in value:
            found = _find_job_id_in_json(child)
            if found:
                return found
    return None


def parse_external_job_id(output: str) -> str:
    """Extract a real FLARE job identifier from JSON or normal CLI prose."""
    parsed = _json_from_output(output)
    candidate = _find_job_id_in_json(parsed)
    if candidate:
        return candidate
    for pattern in JOB_ID_PATTERNS:
        match = pattern.search(output)
        if match and EXTERNAL_JOB_ID_RE.fullmatch(match.group(1)):
            return match.group(1)
    raise NvflareCliError("submit", 0, _sha256_text(output))


class NvflareCliAdapter:
    """Small, injectable adapter around the coordinator-side ``nvflare job`` CLI."""

    def __init__(
        self,
        runner: CommandRunner = _default_command_runner,
        executable: str = "nvflare",
    ):
        self._runner = runner
        self._executable = executable

    def _run(self, operation: str, arguments: Sequence[str]) -> NvflareOperationResult:
        completed = self._runner([self._executable, "job", *arguments])
        stdout = str(completed.stdout or "")
        stderr = str(completed.stderr or "")
        output_sha256 = _sha256_text(f"{stdout}\n{stderr}")
        if completed.returncode:
            raise NvflareCliError(operation, completed.returncode, output_sha256)
        payload = _json_from_output(stdout)
        return NvflareOperationResult(
            operation=operation,
            returncode=completed.returncode,
            output_sha256=output_sha256,
            payload=payload,
            raw_stdout=stdout,
        )

    def submit(self, job_directory: Path, admin_kit: Path) -> NvflareOperationResult:
        result = self._run(
            "submit",
            [
                "submit",
                "-j",
                str(job_directory.resolve()),
                "--startup-kit",
                str(admin_kit.resolve()),
            ],
        )
        external_job_id = parse_external_job_id(result.raw_stdout)
        return NvflareOperationResult(
            operation=result.operation,
            returncode=result.returncode,
            output_sha256=result.output_sha256,
            payload=result.payload,
            external_job_id=external_job_id,
        )

    def status(self, external_job_id: str, admin_kit: Path) -> NvflareOperationResult:
        return self._run(
            "status",
            [
                "meta",
                external_job_id,
                "--startup-kit",
                str(admin_kit.resolve()),
            ],
        )

    def list_jobs(self, admin_kit: Path) -> NvflareOperationResult:
        return self._run("list", ["list", "--startup-kit", str(admin_kit.resolve())])

    def abort(self, external_job_id: str, admin_kit: Path) -> NvflareOperationResult:
        return self._run(
            "abort",
            [
                "abort",
                external_job_id,
                "--startup-kit",
                str(admin_kit.resolve()),
            ],
        )


def _walk_json(value: Any) -> Iterable[tuple[str, Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key).lower(), child
            yield from _walk_json(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _walk_json(child)


def _looks_sensitive_file(path: Path) -> bool:
    lower = path.name.lower()
    suffix = "".join(path.suffixes).lower()
    return (
        lower in SENSITIVE_FILE_NAMES
        or any(token in lower for token in ("patient", "subject", "private-key", "private_key"))
        or suffix in SENSITIVE_FILE_SUFFIXES
        or path.suffix.lower() in SENSITIVE_FILE_SUFFIXES
    )


@dataclass(frozen=True)
class ValidatedJobBundle:
    directory: Path = field(repr=False)
    directory_name: str
    bundle_sha256: str
    strategy: str
    expected_sites: tuple[str, str, str]
    total_rounds: int
    local_epochs: int
    privacy_contract: dict[str, Any] = field(default_factory=dict, repr=False)

    def public_receipt(self) -> dict[str, Any]:
        return {
            "schema_version": "rarelink-physical-job-validation-v1",
            "job_directory_name": self.directory_name,
            "bundle_sha256": self.bundle_sha256,
            "strategy": self.strategy,
            "expected_sites": list(self.expected_sites),
            "total_rounds": self.total_rounds,
            "local_epochs": self.local_epochs,
            "privacy": deepcopy(self.privacy_contract),
            "three_site_contract": True,
            "admin_kit_path_exported": False,
            "secret_exported": False,
            "patient_data_packaged": False,
            "certificates_packaged": False,
            "private_keys_packaged": False,
        }


def validate_exported_job(job_directory: Path) -> ValidatedJobBundle:
    """Validate an exported three-site job before it reaches the FLARE admin CLI."""
    root = job_directory.resolve()
    if not root.is_dir():
        raise JobValidationError("Exported job directory does not exist")
    if any(token in root.name.lower() for token in ("patient", "subject")):
        raise JobValidationError("Exported job directory name must not contain patient identifiers")
    meta = root / "meta.json"
    receipt_path = root / "rarelink-job-receipt.json"
    if not meta.is_file():
        raise JobValidationError("Exported NVFLARE job is missing meta.json")
    if not receipt_path.is_file():
        raise JobValidationError("Exported job is missing rarelink-job-receipt.json")

    files = sorted(path for path in root.rglob("*") if path.is_file() or path.is_symlink())
    if not files:
        raise JobValidationError("Exported job contains no files")
    for path in files:
        if path.is_symlink():
            raise JobValidationError("Exported job must not contain symbolic links")
        if _looks_sensitive_file(path):
            raise JobValidationError(f"Sensitive or patient-level file is forbidden: {path.name}")

    try:
        meta_payload = json.loads(meta.read_text(encoding="utf-8"))
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise JobValidationError("Job metadata and receipt must be valid UTF-8 JSON") from exc
    if not isinstance(meta_payload, dict) or not isinstance(receipt, dict):
        raise JobValidationError("Job metadata and receipt must be JSON objects")
    for key, value in _walk_json((meta_payload, receipt)):
        if key in SENSITIVE_JSON_KEYS and value not in (None, False, "", 0):
            raise JobValidationError(f"Sensitive field {key!r} is forbidden in an exported job")

    required_false = (
        "patient_data_packaged",
        "certificates_packaged",
        "private_keys_packaged",
    )
    if any(receipt.get(key) is not False for key in required_false):
        raise JobValidationError(
            "Export receipt must prove data, certificates, and keys are absent"
        )
    if receipt.get("local_only_manifest_required") is not True:
        raise JobValidationError("Physical jobs must require each site's local-only manifest")
    if receipt.get("dataset_receipt_required") is not True:
        raise JobValidationError(
            "Physical jobs must require a validated hospital-local dataset receipt"
        )

    strategy = str(receipt.get("strategy", "")).lower()
    if strategy not in {"fedavg", "fedprox", "fedavg_dpsgd"}:
        raise JobValidationError(
            "Physical job strategy must be fedavg or fedprox, or fedavg_dpsgd"
        )
    expected_sites = receipt.get("expected_sites")
    if (
        not isinstance(expected_sites, list)
        or len(expected_sites) != 3
        or len(set(expected_sites)) != 3
        or any(not isinstance(site, str) or not site.strip() for site in expected_sites)
    ):
        raise JobValidationError("Physical v1 requires exactly three distinct expected sites")
    total_rounds = receipt.get("rounds")
    local_epochs = receipt.get("local_epochs")
    if not isinstance(total_rounds, int) or isinstance(total_rounds, bool) or total_rounds < 1:
        raise JobValidationError("Export receipt rounds must be a positive integer")
    if not isinstance(local_epochs, int) or isinstance(local_epochs, bool) or local_epochs < 1:
        raise JobValidationError("Export receipt local_epochs must be a positive integer")
    try:
        privacy_contract = validate_physical_privacy_contract(
            strategy,
            receipt.get("privacy"),
        )
    except ValueError as exc:
        raise JobValidationError(
            "Export receipt contains an invalid physical privacy contract"
        ) from exc

    digest = hashlib.sha256()
    for path in files:
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(bytes.fromhex(sha256_file(path)))
        digest.update(b"\0")
    sites_tuple = tuple(str(site) for site in expected_sites)
    return ValidatedJobBundle(
        directory=root,
        directory_name=root.name,
        bundle_sha256=digest.hexdigest(),
        strategy=strategy,
        expected_sites=(sites_tuple[0], sites_tuple[1], sites_tuple[2]),
        total_rounds=total_rounds,
        local_epochs=local_epochs,
        privacy_contract=privacy_contract,
    )


@dataclass(frozen=True)
class QuorumStatus:
    expected_sites: tuple[str, str, str]
    reported_sites: tuple[str, ...]
    missing_sites: tuple[str, ...]
    unexpected_sites: tuple[str, ...]
    required: int
    received_updates: int
    satisfied: bool

    def public_receipt(self) -> dict[str, Any]:
        return {
            "expected_sites": list(self.expected_sites),
            "reported_sites": list(self.reported_sites),
            "missing_sites": list(self.missing_sites),
            "unexpected_sites": list(self.unexpected_sites),
            "required": self.required,
            "received_updates": self.received_updates,
            "satisfied": self.satisfied,
        }


def calculate_three_site_quorum(
    expected_sites: Sequence[str],
    reported_sites: Iterable[str],
    received_updates: int | None = None,
) -> QuorumStatus:
    expected = tuple(dict.fromkeys(expected_sites))
    if len(expected) != 3:
        raise JobValidationError(
            "Three-site quorum requires exactly three expected site identities"
        )
    reported_set = {site for site in reported_sites if isinstance(site, str)}
    expected_set = set(expected)
    accepted = tuple(site for site in expected if site in reported_set)
    missing = tuple(site for site in expected if site not in reported_set)
    unexpected = tuple(sorted(reported_set - expected_set))
    count = len(accepted) if received_updates is None else max(0, received_updates)
    # A numeric update count alone is insufficient: all three signed site identities
    # must be present before RareLink declares quorum.
    return QuorumStatus(
        expected_sites=(expected[0], expected[1], expected[2]),
        reported_sites=accepted,
        missing_sites=missing,
        unexpected_sites=unexpected,
        required=3,
        received_updates=count,
        satisfied=not missing and count >= 3,
    )


@dataclass
class PhysicalJobRecord:
    job_id: str
    bundle: ValidatedJobBundle = field(repr=False)
    state: PhysicalJobState = PhysicalJobState.VALIDATED
    external_job_id: str | None = None
    submit_token_sha256: str | None = field(default=None, repr=False)
    submitted_at: datetime | None = None
    updated_at: datetime = field(default_factory=_utc_now)
    current_round: int = 0
    reported_sites: tuple[str, ...] = ()
    received_updates: int = 0
    attempt: int = 0
    previous_external_job_ids: tuple[str, ...] = ()
    global_model_path: Path | None = field(default=None, repr=False)
    global_model_sha256: str | None = None
    error_code: str | None = None

    def public_receipt(self) -> dict[str, Any]:
        quorum = calculate_three_site_quorum(
            self.bundle.expected_sites,
            self.reported_sites,
            self.received_updates,
        )
        return {
            "schema_version": "rarelink-physical-controller-job-v1",
            "job_id": self.job_id,
            "external_job_id": self.external_job_id,
            "state": self.state,
            "strategy": self.bundle.strategy,
            "bundle_sha256": self.bundle.bundle_sha256,
            "job_directory_name": self.bundle.directory_name,
            "current_round": self.current_round,
            "total_rounds": self.bundle.total_rounds,
            "attempt": self.attempt,
            "quorum": quorum.public_receipt(),
            "global_model_sha256": self.global_model_sha256,
            "error_code": self.error_code,
            "admin_kit_path_exported": False,
            "submit_token_exported": False,
            "secret_exported": False,
            "patient_data_exported": False,
        }


class PhysicalJobStore(Protocol):
    def get(self, job_id: str) -> PhysicalJobRecord | None: ...

    def save(self, record: PhysicalJobRecord) -> None: ...

    def list(self) -> list[PhysicalJobRecord]: ...

    def find_by_submit_token_sha256(
        self,
        submit_token_sha256: str,
    ) -> PhysicalJobRecord | None: ...


class InMemoryPhysicalJobStore:
    """Reference store for tests and single-process development."""

    def __init__(self):
        self._records: dict[str, PhysicalJobRecord] = {}
        self._lock = threading.RLock()

    def get(self, job_id: str) -> PhysicalJobRecord | None:
        with self._lock:
            record = self._records.get(job_id)
            return deepcopy(record) if record else None

    def save(self, record: PhysicalJobRecord) -> None:
        with self._lock:
            self._records[record.job_id] = deepcopy(record)

    def list(self) -> list[PhysicalJobRecord]:
        with self._lock:
            return [deepcopy(self._records[key]) for key in sorted(self._records)]

    def find_by_submit_token_sha256(
        self,
        submit_token_sha256: str,
    ) -> PhysicalJobRecord | None:
        with self._lock:
            for record in self._records.values():
                if (
                    record.submit_token_sha256
                    and hmac.compare_digest(
                        record.submit_token_sha256,
                        submit_token_sha256,
                    )
                ):
                    return deepcopy(record)
        return None


def _integer(payload: Any, *keys: str) -> int | None:
    if not isinstance(payload, dict):
        return None
    for key in keys:
        value = payload.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return max(0, value)
    return None


def _normalize_remote_state(payload: Any) -> PhysicalJobState | None:
    if not isinstance(payload, dict):
        return None
    raw = payload.get("status", payload.get("state"))
    if not isinstance(raw, str):
        return None
    normalized = raw.strip().upper().replace(" ", "_").replace("-", "_")
    aliases = {
        "SUBMITTED": PhysicalJobState.SUBMITTED,
        "QUEUED": PhysicalJobState.WAITING_FOR_SITES,
        "WAITING": PhysicalJobState.WAITING_FOR_SITES,
        "WAITING_FOR_CLIENTS": PhysicalJobState.WAITING_FOR_SITES,
        "STARTED": PhysicalJobState.RUNNING,
        "RUNNING": PhysicalJobState.RUNNING,
        "FINISHED": PhysicalJobState.COMPLETED,
        "FINISHED:COMPLETED": PhysicalJobState.COMPLETED,
        "FINISHED_COMPLETED": PhysicalJobState.COMPLETED,
        "COMPLETED": PhysicalJobState.COMPLETED,
        "FAILED": PhysicalJobState.FAILED,
        "ERROR": PhysicalJobState.FAILED,
        "FINISHED:FAILED": PhysicalJobState.FAILED,
        "FINISHED_FAILED": PhysicalJobState.FAILED,
        "ABORTED": PhysicalJobState.ABORTED,
        "ABORTED_BY_USER": PhysicalJobState.ABORTED,
        "FINISHED:ABORTED": PhysicalJobState.ABORTED,
        "FINISHED_ABORTED": PhysicalJobState.ABORTED,
    }
    return aliases.get(normalized)


def _remote_status_mapping(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    if "status" in payload or "state" in payload:
        return payload
    candidates = [
        payload[key]
        for key in ("job", "meta", "result", "data")
        if isinstance(payload.get(key), dict)
        and ("status" in payload[key] or "state" in payload[key])
    ]
    return candidates[0] if len(candidates) == 1 else None


@dataclass(frozen=True)
class ReconciliationDecision:
    outcome: str
    applied: bool
    failed_closed: bool = False
    late_snapshot_ignored: bool = False
    site_dropout: bool = False

    def public_receipt(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "applied": self.applied,
            "failed_closed": self.failed_closed,
            "late_snapshot_ignored": self.late_snapshot_ignored,
            "site_dropout": self.site_dropout,
        }


def _failed_closed(
    record: PhysicalJobRecord,
    error_code: str,
) -> ReconciliationDecision:
    record.state = PhysicalJobState.FAILED
    record.error_code = error_code
    return ReconciliationDecision(
        outcome=error_code,
        applied=True,
        failed_closed=True,
    )


def _strict_remote_sites(payload: dict[str, Any]) -> tuple[str, ...]:
    value: Any = None
    for key in ("received_from", "completed_sites"):
        if key in payload:
            value = payload[key]
            break
    if value is None:
        return ()
    if not isinstance(value, list) or any(not isinstance(site, str) for site in value):
        raise JobValidationError("Remote update identities must be a JSON list of site IDs")
    if len(value) != len(set(value)):
        raise JobValidationError("Remote update identities contain a duplicate site")
    return tuple(value)


def _strict_connected_sites(payload: dict[str, Any]) -> tuple[str, ...] | None:
    if "connected_clients" not in payload:
        return None
    value = payload["connected_clients"]
    if not isinstance(value, list) or any(not isinstance(site, str) for site in value):
        raise JobValidationError("Remote connected clients must be a JSON list of site IDs")
    if len(value) != len(set(value)):
        raise JobValidationError("Remote connected clients contain a duplicate site")
    return tuple(value)


def reconcile_remote_snapshot(
    record: PhysicalJobRecord,
    payload: Any,
) -> ReconciliationDecision:
    """Apply one FLARE metadata snapshot using monotonic, fail-closed rules."""
    remote_payload = _remote_status_mapping(payload)
    if remote_payload is None:
        return _failed_closed(record, "RECONCILIATION_INVALID_REMOTE_PAYLOAD")
    remote_state = _normalize_remote_state(remote_payload)
    if remote_state is None:
        return _failed_closed(record, "RECONCILIATION_UNKNOWN_REMOTE_STATE")

    payload_job_id = _find_job_id_in_json(payload)
    if (
        payload_job_id
        and record.external_job_id
        and payload_job_id != record.external_job_id
    ):
        return _failed_closed(record, "RECONCILIATION_EXTERNAL_JOB_ID_MISMATCH")

    if record.state in {PhysicalJobState.COMPLETED, PhysicalJobState.ABORTED}:
        if remote_state is record.state:
            return ReconciliationDecision("TERMINAL_STATE_CONFIRMED", applied=False)
        return _failed_closed(record, "RECONCILIATION_TERMINAL_STATE_CONFLICT")

    recoverable_reconciliation_failure = bool(
        record.error_code and record.error_code.startswith("RECONCILIATION_")
    )
    if record.state is PhysicalJobState.FAILED and not recoverable_reconciliation_failure:
        if remote_state is PhysicalJobState.FAILED:
            return ReconciliationDecision("FAILED_STATE_CONFIRMED", applied=False)
        return _failed_closed(record, "RECONCILIATION_FAILED_STATE_CONFLICT")

    if remote_state in {PhysicalJobState.FAILED, PhysicalJobState.ABORTED}:
        record.state = remote_state
        record.error_code = None
        return ReconciliationDecision("TERMINAL_STATE_APPLIED", applied=True)

    current_round = _integer(
        remote_payload,
        "current_round",
        "round",
        "round_number",
    )
    if remote_state in {PhysicalJobState.RUNNING, PhysicalJobState.COMPLETED}:
        if current_round is None:
            return _failed_closed(record, "RECONCILIATION_ROUND_MISSING")
        if current_round < 1 or current_round > record.bundle.total_rounds:
            return _failed_closed(record, "RECONCILIATION_ROUND_OUT_OF_RANGE")
    elif current_round is None:
        current_round = record.current_round

    if current_round < record.current_round:
        return ReconciliationDecision(
            "LATE_ROUND_SNAPSHOT_IGNORED",
            applied=False,
            late_snapshot_ignored=True,
        )

    state_rank = {
        PhysicalJobState.SUBMITTED: 0,
        PhysicalJobState.WAITING_FOR_SITES: 1,
        PhysicalJobState.RUNNING: 2,
        PhysicalJobState.COMPLETED: 3,
    }
    if (
        record.state in state_rank
        and remote_state in state_rank
        and state_rank[remote_state] < state_rank[record.state]
        and current_round <= record.current_round
    ):
        return _failed_closed(record, "RECONCILIATION_ILLEGAL_STATE_REGRESSION")

    try:
        remote_sites = _strict_remote_sites(remote_payload)
        connected_sites = _strict_connected_sites(remote_payload)
    except JobValidationError:
        return _failed_closed(record, "RECONCILIATION_INVALID_SITE_IDENTITIES")

    expected = set(record.bundle.expected_sites)
    if set(remote_sites) - expected:
        return _failed_closed(record, "RECONCILIATION_UNEXPECTED_SITE_UPDATE")
    if connected_sites is not None and set(connected_sites) - expected:
        return _failed_closed(record, "RECONCILIATION_UNEXPECTED_CONNECTED_SITE")

    received_updates = _integer(
        remote_payload,
        "received_updates",
        "num_updates",
        "updates_received",
    )
    if received_updates is None:
        received_updates = len(remote_sites)
    if (
        remote_state is PhysicalJobState.COMPLETED
        and set(remote_sites) != expected
    ):
        record.current_round = current_round
        record.reported_sites = remote_sites
        record.received_updates = min(received_updates, 3)
        return _failed_closed(record, "INCOMPLETE_THREE_SITE_QUORUM")
    if received_updates > 3 or received_updates != len(remote_sites):
        return _failed_closed(record, "RECONCILIATION_UPDATE_COUNT_MISMATCH")

    stale_same_round = (
        current_round == record.current_round
        and not set(remote_sites).issuperset(record.reported_sites)
    )
    if current_round > record.current_round:
        record.current_round = current_round
        record.reported_sites = remote_sites
        record.received_updates = received_updates
    else:
        record.reported_sites = tuple(
            site
            for site in record.bundle.expected_sites
            if site in set(record.reported_sites) | set(remote_sites)
        )
        record.received_updates = max(record.received_updates, received_updates)

    quorum = calculate_three_site_quorum(
        record.bundle.expected_sites,
        record.reported_sites,
        record.received_updates,
    )
    if remote_state is PhysicalJobState.COMPLETED:
        if record.current_round != record.bundle.total_rounds:
            return _failed_closed(record, "RECONCILIATION_PREMATURE_COMPLETION")
        if not quorum.satisfied:
            return _failed_closed(record, "INCOMPLETE_THREE_SITE_QUORUM")
        record.state = PhysicalJobState.COMPLETED
        record.error_code = None
        return ReconciliationDecision("COMPLETION_VERIFIED", applied=True)

    if (
        connected_sites is not None
        and remote_state is PhysicalJobState.RUNNING
        and set(connected_sites) != expected
    ):
        record.state = PhysicalJobState.WAITING_FOR_SITES
        record.error_code = "EXPECTED_SITE_OFFLINE"
        return ReconciliationDecision(
            "EXPECTED_SITE_OFFLINE",
            applied=True,
            site_dropout=True,
        )

    record.state = remote_state
    record.error_code = None
    if stale_same_round:
        return ReconciliationDecision(
            "STALE_SAME_ROUND_SNAPSHOT_MERGED",
            applied=True,
            late_snapshot_ignored=True,
        )
    return ReconciliationDecision("REMOTE_STATE_APPLIED", applied=True)


class PhysicalFederationController:
    """Coordinator service for real, independently deployed physical clients."""

    def __init__(self, adapter: NvflareCliAdapter, store: PhysicalJobStore):
        self.adapter = adapter
        self.store = store

    def register(self, job_id: str, job_directory: Path) -> dict[str, Any]:
        if not job_id or len(job_id) > 128:
            raise JobValidationError("job_id must be between 1 and 128 characters")
        existing = self.store.get(job_id)
        bundle = validate_exported_job(job_directory)
        if existing:
            if hmac.compare_digest(existing.bundle.bundle_sha256, bundle.bundle_sha256):
                receipt = existing.public_receipt()
                receipt["idempotent"] = True
                return receipt
            raise JobConflictError("job_id is already bound to a different exported bundle")
        record = PhysicalJobRecord(job_id=job_id, bundle=bundle)
        self.store.save(record)
        receipt = record.public_receipt()
        receipt["idempotent"] = False
        return receipt

    def _require(self, job_id: str) -> PhysicalJobRecord:
        record = self.store.get(job_id)
        if not record:
            raise JobNotFoundError(f"Physical job {job_id!r} was not found")
        return record

    def submit(
        self,
        job_id: str,
        *,
        admin_kit: Path,
        submit_token: str,
    ) -> dict[str, Any]:
        if len(submit_token) < 8:
            raise JobValidationError("submit_token must contain at least 8 characters")
        record = self._require(job_id)
        token_sha256 = _sha256_text(submit_token)
        token_owner = self.store.find_by_submit_token_sha256(token_sha256)
        if token_owner and token_owner.job_id != job_id:
            raise JobConflictError(
                "Idempotency token is already bound to another physical job"
            )
        if record.external_job_id:
            if (
                record.submit_token_sha256
                and hmac.compare_digest(record.submit_token_sha256, token_sha256)
            ):
                receipt = record.public_receipt()
                receipt["idempotent"] = True
                return receipt
            raise JobConflictError("Job was already submitted with a different idempotency token")
        if record.submit_token_sha256:
            if not hmac.compare_digest(record.submit_token_sha256, token_sha256):
                raise JobConflictError(
                    "Submission outcome is unresolved for a different idempotency token"
                )
            receipt = record.public_receipt()
            receipt["idempotent"] = True
            receipt["requires_reconciliation"] = True
            return receipt
        if record.state is not PhysicalJobState.VALIDATED:
            raise JobConflictError(f"Cannot submit a job in state {record.state}")

        # Persist intent before making the external call. If this process stops after
        # FLARE accepts the job, a restarted controller will reconcile instead of
        # creating a second external job.
        record.submit_token_sha256 = token_sha256
        record.state = PhysicalJobState.SUBMITTED
        record.error_code = "SUBMIT_OUTCOME_UNKNOWN"
        record.attempt += 1
        record.updated_at = _utc_now()
        self.store.save(record)
        try:
            result = self.adapter.submit(record.bundle.directory, admin_kit)
        except NvflareCliError as exc:
            record = self._require(job_id)
            if exc.returncode:
                record.state = PhysicalJobState.FAILED
                record.error_code = "SUBMIT_REJECTED_BY_EXTERNAL_SYSTEM"
                record.updated_at = _utc_now()
                self.store.save(record)
            # A zero exit code without a parseable ID remains unknown and must be
            # reconciled from the remote job list.
            raise
        if not result.external_job_id:
            raise PhysicalControllerError("NVFLARE accepted submit without returning a job ID")
        record.external_job_id = result.external_job_id
        record.state = PhysicalJobState.SUBMITTED
        record.submitted_at = _utc_now()
        record.updated_at = record.submitted_at
        record.error_code = None
        self.store.save(record)
        receipt = record.public_receipt()
        receipt["idempotent"] = False
        receipt["operation"] = result.public_receipt()
        return receipt

    def status(self, job_id: str, *, admin_kit: Path) -> dict[str, Any]:
        record = self._require(job_id)
        if record.error_code and record.error_code.startswith("DATASET_VERSION_CHANGED"):
            receipt = record.public_receipt()
            receipt["remote_query_skipped"] = True
            receipt["requires_new_contract"] = True
            return receipt
        if not record.external_job_id:
            return record.public_receipt()
        result = self.adapter.status(record.external_job_id, admin_kit)
        decision = reconcile_remote_snapshot(record, result.payload)
        record.updated_at = _utc_now()
        self.store.save(record)
        receipt = record.public_receipt()
        receipt["operation"] = result.public_receipt()
        receipt["reconciliation"] = decision.public_receipt()
        return receipt

    def reconcile_submission(
        self,
        job_id: str,
        *,
        admin_kit: Path,
    ) -> dict[str, Any]:
        """Resolve a persisted submit intent without issuing another submit."""
        record = self._require(job_id)
        if record.external_job_id:
            receipt = record.public_receipt()
            receipt["reconciliation"] = {
                "outcome": "EXTERNAL_JOB_ID_ALREADY_PERSISTED",
                "resolved": True,
            }
            return receipt
        if not record.submit_token_sha256:
            raise JobConflictError("Physical job has no persisted submission intent")

        result = self.adapter.list_jobs(admin_kit)
        payload = result.payload
        if isinstance(payload, list):
            jobs = payload
        elif isinstance(payload, dict):
            candidates = [
                payload[key]
                for key in ("jobs", "job_list", "results", "data")
                if isinstance(payload.get(key), list)
            ]
            jobs = candidates[0] if len(candidates) == 1 else None
        else:
            jobs = None
        if jobs is None:
            record.state = PhysicalJobState.FAILED
            record.error_code = "RECONCILIATION_INVALID_REMOTE_JOB_LIST"
            record.updated_at = _utc_now()
            self.store.save(record)
            receipt = record.public_receipt()
            receipt["reconciliation"] = {
                "outcome": record.error_code,
                "resolved": False,
                "failed_closed": True,
            }
            receipt["operation"] = result.public_receipt()
            return receipt

        matches: list[dict[str, Any]] = []
        for item in jobs:
            if not isinstance(item, dict):
                continue
            bundle_sha256 = item.get("bundle_sha256")
            if bundle_sha256 is None:
                for metadata_key in ("metadata", "meta", "custom_props"):
                    metadata = item.get(metadata_key)
                    if isinstance(metadata, dict) and isinstance(
                        metadata.get("bundle_sha256"),
                        str,
                    ):
                        bundle_sha256 = metadata["bundle_sha256"]
                        break
            if (
                isinstance(bundle_sha256, str)
                and hmac.compare_digest(
                    bundle_sha256,
                    record.bundle.bundle_sha256,
                )
            ):
                matches.append(item)

        if len(matches) > 1:
            record.state = PhysicalJobState.FAILED
            record.error_code = "RECONCILIATION_AMBIGUOUS_EXTERNAL_SUBMISSION"
            resolved = False
        elif len(matches) == 1:
            external_job_id = _find_job_id_in_json(matches[0])
            if not external_job_id:
                record.state = PhysicalJobState.FAILED
                record.error_code = "RECONCILIATION_EXTERNAL_JOB_ID_MISSING"
                resolved = False
            else:
                record.external_job_id = external_job_id
                record.state = PhysicalJobState.SUBMITTED
                record.error_code = None
                resolved = True
        else:
            # A list response can be paginated or eventually consistent. Absence is
            # not proof that FLARE did not create the job, so never auto-resubmit.
            record.state = PhysicalJobState.SUBMITTED
            record.error_code = "SUBMIT_OUTCOME_UNKNOWN"
            resolved = False
        record.updated_at = _utc_now()
        self.store.save(record)
        receipt = record.public_receipt()
        receipt["reconciliation"] = {
            "outcome": (
                "SUBMISSION_RECONCILED"
                if resolved
                else record.error_code
            ),
            "resolved": resolved,
            "external_match_count": len(matches),
        }
        receipt["operation"] = result.public_receipt()
        return receipt

    def recover_after_restart(self, *, admin_kit: Path) -> dict[str, Any]:
        """Reconcile all persisted non-terminal jobs after controller restart."""
        results: list[dict[str, Any]] = []
        for record in self.store.list():
            if record.state in {PhysicalJobState.COMPLETED, PhysicalJobState.ABORTED}:
                continue
            try:
                if record.external_job_id:
                    receipt = self.status(record.job_id, admin_kit=admin_kit)
                elif record.submit_token_sha256:
                    receipt = self.reconcile_submission(
                        record.job_id,
                        admin_kit=admin_kit,
                    )
                else:
                    continue
                results.append(
                    {
                        "job_id": record.job_id,
                        "state": receipt["state"],
                        "error_code": receipt["error_code"],
                    }
                )
            except PhysicalControllerError:
                failed = self._require(record.job_id)
                failed.state = PhysicalJobState.FAILED
                failed.error_code = "RECONCILIATION_EXTERNAL_QUERY_FAILED"
                failed.updated_at = _utc_now()
                self.store.save(failed)
                results.append(
                    {
                        "job_id": record.job_id,
                        "state": PhysicalJobState.FAILED,
                        "error_code": failed.error_code,
                    }
                )
        return {
            "schema_version": "rarelink-physical-recovery-v1",
            "checked_jobs": len(results),
            "jobs": results,
            "external_submit_performed": False,
            "admin_kit_path_exported": False,
            "secret_exported": False,
            "patient_data_exported": False,
            "evidence_scope": "control-protocol-only",
        }

    def list(self) -> list[dict[str, Any]]:
        """List local controller records; no admin-kit access is necessary."""
        return [record.public_receipt() for record in self.store.list()]

    def list_remote(self, *, admin_kit: Path) -> dict[str, Any]:
        """Prove remote list access without relaying untrusted CLI output."""
        result = self.adapter.list_jobs(admin_kit)
        remote_count = len(result.payload) if isinstance(result.payload, list) else None
        return {
            "schema_version": "rarelink-physical-controller-list-v1",
            "remote_query_succeeded": True,
            "remote_job_count": remote_count,
            "managed_jobs": self.list(),
            "operation": result.public_receipt(),
            "admin_kit_path_exported": False,
            "secret_exported": False,
            "patient_data_exported": False,
        }

    def abort(self, job_id: str, *, admin_kit: Path) -> dict[str, Any]:
        record = self._require(job_id)
        if not record.external_job_id:
            raise JobConflictError("A job without an external job ID cannot be aborted")
        if record.state in {PhysicalJobState.COMPLETED, PhysicalJobState.ABORTED}:
            receipt = record.public_receipt()
            receipt["idempotent"] = True
            return receipt
        result = self.adapter.abort(record.external_job_id, admin_kit)
        record.state = PhysicalJobState.ABORTED
        record.updated_at = _utc_now()
        self.store.save(record)
        receipt = record.public_receipt()
        receipt["idempotent"] = False
        receipt["operation"] = result.public_receipt()
        return receipt

    def retry(
        self,
        job_id: str,
        *,
        admin_kit: Path,
        submit_token: str,
    ) -> dict[str, Any]:
        record = self._require(job_id)
        if record.state not in {PhysicalJobState.FAILED, PhysicalJobState.ABORTED}:
            raise JobConflictError("Only failed or aborted jobs can be retried")
        if record.external_job_id:
            record.previous_external_job_ids = (
                *record.previous_external_job_ids,
                record.external_job_id,
            )
        record.external_job_id = None
        record.submit_token_sha256 = None
        record.state = PhysicalJobState.VALIDATED
        record.current_round = 0
        record.reported_sites = ()
        record.received_updates = 0
        record.error_code = None
        record.updated_at = _utc_now()
        self.store.save(record)
        receipt = self.submit(job_id, admin_kit=admin_kit, submit_token=submit_token)
        receipt["retry"] = True
        return receipt

    def resume(
        self,
        job_id: str,
        *,
        admin_kit: Path,
        submit_token: str,
    ) -> dict[str, Any]:
        """Resume control after interruption, or safely retry a terminal failure.

        NVFLARE continues an active external job independently of this API process.
        Therefore active jobs are resumed by re-attaching through ``status``. A
        failed/aborted job is re-submitted as a new attempt with an explicit token.
        """
        record = self._require(job_id)
        if record.state in {
            PhysicalJobState.SUBMITTED,
            PhysicalJobState.WAITING_FOR_SITES,
            PhysicalJobState.RUNNING,
        }:
            receipt = self.status(job_id, admin_kit=admin_kit)
            receipt["reattached"] = True
            return receipt
        if record.state in {PhysicalJobState.FAILED, PhysicalJobState.ABORTED}:
            receipt = self.retry(
                job_id,
                admin_kit=admin_kit,
                submit_token=submit_token,
            )
            receipt["resumed_as_new_attempt"] = True
            return receipt
        raise JobConflictError(f"Cannot resume a job in state {record.state}")

    def verify_global_model(
        self,
        job_id: str,
        model_path: Path,
        *,
        expected_sha256: str,
    ) -> dict[str, Any]:
        record = self._require(job_id)
        if record.state is not PhysicalJobState.COMPLETED:
            raise JobConflictError("Global model verification requires a completed job")
        quorum = calculate_three_site_quorum(
            record.bundle.expected_sites,
            record.reported_sites,
            record.received_updates,
        )
        if not quorum.satisfied:
            raise JobConflictError("Global model verification requires verified three-site quorum")
        if not SHA256_RE.fullmatch(expected_sha256):
            raise JobValidationError("expected_sha256 must be 64 lower-case hexadecimal characters")
        resolved = model_path.resolve()
        if not resolved.is_file() or model_path.is_symlink():
            raise JobValidationError("Global model must be a regular file")
        actual = sha256_file(resolved)
        if not hmac.compare_digest(actual, expected_sha256):
            raise JobValidationError(
                "Global model sha256 does not match the trusted expected value"
            )
        record.global_model_path = resolved
        record.global_model_sha256 = actual
        record.updated_at = _utc_now()
        self.store.save(record)
        return {
            "schema_version": "rarelink-global-model-verification-v1",
            "job_id": record.job_id,
            "external_job_id": record.external_job_id,
            "model_file_name": resolved.name,
            "global_model_sha256": actual,
            "verified": True,
            "model_path_exported": False,
            "admin_kit_path_exported": False,
            "secret_exported": False,
            "patient_data_exported": False,
        }
