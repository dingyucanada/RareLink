import re
from collections.abc import Mapping
from typing import Any

from rarelink.domain import PolicyDecision

DEFAULT_ALLOWED_FIELDS = {
    "site_id",
    "sample_count",
    "usable_count",
    "missing_modality_rate",
    "label_completeness",
    "spacing_summary",
    "age_buckets",
    "quality_flags",
}

BLOCKED_KEY_FRAGMENTS = {
    "patient",
    "name",
    "id_number",
    "phone",
    "email",
    "address",
    "file_path",
    "dicom_uid",
    "pixel",
    "voxel",
    "nifti",
    "raw_image",
    "api_key",
    "secret",
}

SENSITIVE_VALUE_PATTERNS = {
    "api_credential_value": re.compile(r"\b(?:sk|key)-[A-Za-z0-9_-]{16,}\b"),
    "email_value": re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
    "phone_value": re.compile(r"(?<!\d)(?:\+?\d[\d -]{8,}\d)(?!\d)"),
    "medical_file_path": re.compile(r"(?:/|[A-Z]:\\)[^\s]+\.(?:nii(?:\.gz)?|dcm)\b", re.I),
    "dicom_uid_value": re.compile(r"\b\d+(?:\.\d+){4,}\b"),
}


def _contains_identifier(field: str) -> bool:
    normalized = field.lower()
    return any(fragment in normalized for fragment in BLOCKED_KEY_FRAGMENTS)


def sanitize_site_aggregate(
    aggregate: Mapping[str, Any],
    min_group_size: int,
    allowed_fields: set[str] | None = None,
) -> PolicyDecision:
    allowed = allowed_fields or DEFAULT_ALLOWED_FIELDS
    blocked: list[str] = []
    clean: dict[str, Any] = {}

    for key, value in aggregate.items():
        if key not in allowed or _contains_identifier(key):
            blocked.append(key)
            continue

        if key == "age_buckets" and isinstance(value, Mapping):
            clean[key] = {
                str(bucket): (
                    count
                    if not isinstance(count, int) or count >= min_group_size
                    else f"<{min_group_size}"
                )
                for bucket, count in value.items()
            }
            blocked.extend(
                f"age_buckets.{bucket}"
                for bucket, count in value.items()
                if isinstance(count, int) and count < min_group_size
            )
            continue

        clean[key] = value

    return PolicyDecision(
        result="released_with_suppression" if blocked else "released",
        rule="aggregate_egress_policy",
        blocked_fields=blocked,
        payload=clean,
    )


def sanitize_llm_payload(payload: Mapping[str, Any], min_group_size: int = 5) -> PolicyDecision:
    blocked: list[str] = []

    def walk(value: Any, path: str = "") -> Any:
        if isinstance(value, Mapping):
            result: dict[str, Any] = {}
            for key, child in value.items():
                child_path = f"{path}.{key}" if path else str(key)
                if _contains_identifier(str(key)):
                    blocked.append(child_path)
                elif (
                    str(key) in {"sample_count", "usable_count"}
                    and isinstance(child, int)
                    and child < min_group_size
                ):
                    blocked.append(child_path)
                    result[str(key)] = f"<{min_group_size}"
                else:
                    result[str(key)] = walk(child, child_path)
            return result
        if isinstance(value, list):
            return [walk(item, f"{path}[]") for item in value]
        if isinstance(value, str):
            for category, pattern in SENSITIVE_VALUE_PATTERNS.items():
                if pattern.search(value):
                    blocked.append(f"{path}:{category}")
                    return "[REDACTED]"
        return value

    clean = walk(payload)
    return PolicyDecision(
        result="released_with_redaction" if blocked else "released",
        rule="llm_payload_allowlist",
        blocked_fields=blocked,
        payload=clean,
    )
