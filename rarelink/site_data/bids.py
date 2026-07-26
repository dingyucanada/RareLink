"""Hospital-local BIDS to RareLink NIfTI manifest mapping.

PyBIDS performs dataset indexing. Subject/session entities and source paths
remain local; the returned receipt contains only aggregate mapping evidence.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Protocol

from rarelink.site_data.validator import NIFTI_SUFFIXES, DatasetValidationError

REQUIRED_MODALITIES = ("FLAIR", "T1w", "T1wCE", "T2w")
RESERVED_QUERY_KEYS = frozenset({"subject", "session", "return_type", "extension"})


class BIDSDependencyError(RuntimeError):
    """Raised when the optional, standards-aware BIDS adapter is unavailable."""


class _BIDSLayout(Protocol):
    def get_subjects(self) -> list[str]: ...

    def get_sessions(self, *, subject: str) -> list[str]: ...

    def get(self, **query: Any) -> list[Any]: ...


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _default_layout_factory(root: str) -> _BIDSLayout:
    try:
        from bids import BIDSLayout
    except ImportError as exc:  # pragma: no cover - optional dependency boundary
        raise BIDSDependencyError(
            "Install RareLink's site-data extra to enable the PyBIDS adapter"
        ) from exc
    return BIDSLayout(root, validate=True, derivatives=True)


def _validated_query_map(
    modality_queries: Mapping[str, Mapping[str, Any]],
    label_query: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    if set(modality_queries) != set(REQUIRED_MODALITIES):
        raise DatasetValidationError(
            "BIDS mapping must explicitly define all four MRI modalities"
        )
    combined: dict[str, dict[str, Any]] = {
        modality: dict(modality_queries[modality])
        for modality in REQUIRED_MODALITIES
    }
    combined["label"] = dict(label_query)
    for query in combined.values():
        if (
            not query
            or RESERVED_QUERY_KEYS.intersection(query)
            or any(
                not isinstance(key, str)
                or not key
                or value is None
                or isinstance(value, (dict, list))
                for key, value in query.items()
            )
        ):
            raise DatasetValidationError("A BIDS entity query is invalid or ambiguous")
    return combined


def _local_nifti(root: Path, value: Any) -> tuple[Path, str]:
    if not isinstance(value, (str, Path)):
        raise DatasetValidationError("A BIDS query returned a non-file result")
    candidate = Path(value)
    resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise DatasetValidationError(
            "A BIDS query returned a file outside the approved dataset root"
        ) from exc
    if (
        not resolved.is_file()
        or resolved.is_symlink()
        or not resolved.name.lower().endswith(NIFTI_SUFFIXES)
    ):
        raise DatasetValidationError(
            "Every mapped BIDS result must be a local regular NIfTI file"
        )
    return resolved, relative.as_posix()


def _opaque_case_id(
    *,
    site_id: str,
    subject: str,
    session: str | None,
    case_id_key: bytes,
) -> str:
    digest = hmac.new(
        case_id_key,
        f"rarelink-bids-v1\0{site_id}\0{subject}\0{session or ''}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"rl-{digest[:32]}"


def import_bids_manifest(
    bids_root: Path,
    output_manifest: Path,
    *,
    site_id: str,
    modality_queries: Mapping[str, Mapping[str, Any]],
    label_query: Mapping[str, Any],
    case_id_key: bytes,
    allowed_label_values: tuple[int, ...] = (0, 1, 2),
    layout_factory: Callable[[str], _BIDSLayout] | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Index one local BIDS dataset and write a local-only RareLink manifest."""
    root = bids_root.resolve()
    if (
        not root.is_dir()
        or bids_root.is_symlink()
        or not isinstance(site_id, str)
        or not site_id
        or not isinstance(case_id_key, bytes)
        or len(case_id_key) < 32
    ):
        raise DatasetValidationError("The BIDS intake boundary configuration is invalid")
    if (
        not allowed_label_values
        or any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in allowed_label_values
        )
        or len(allowed_label_values) != len(set(allowed_label_values))
    ):
        raise DatasetValidationError("The BIDS label contract is invalid")
    queries = _validated_query_map(modality_queries, label_query)
    factory = layout_factory or _default_layout_factory
    try:
        layout = factory(str(root))
    except BIDSDependencyError:
        raise
    except Exception:
        raise DatasetValidationError(
            "The standards-aware local BIDS index could not be opened"
        ) from None
    try:
        subjects = sorted(layout.get_subjects())
    except Exception:
        raise DatasetValidationError("The local BIDS index could not be enumerated") from None
    if not subjects or any(not isinstance(subject, str) or not subject for subject in subjects):
        raise DatasetValidationError("The local BIDS index contains no usable subjects")
    if len(subjects) != len(set(subjects)):
        raise DatasetValidationError("The local BIDS index contains duplicate subjects")

    cases: list[dict[str, Any]] = []
    for subject in subjects:
        try:
            sessions = sorted(layout.get_sessions(subject=subject))
        except Exception:
            raise DatasetValidationError(
                "The local BIDS sessions could not be enumerated"
            ) from None
        if len(sessions) != len(set(sessions)):
            raise DatasetValidationError(
                "The local BIDS index contains duplicate sessions"
            )
        local_sessions: list[str | None] = sessions if sessions else [None]
        for session in local_sessions:
            common: dict[str, Any] = {
                "return_type": "file",
                "extension": [".nii", ".nii.gz"],
                "subject": subject,
            }
            if session is not None:
                common["session"] = session
            mapped: dict[str, str] = {}
            for role, query in queries.items():
                try:
                    matches = layout.get(**common, **query)
                except Exception:
                    raise DatasetValidationError(
                        "A local BIDS entity query failed"
                    ) from None
                if not isinstance(matches, list) or len(matches) != 1:
                    raise DatasetValidationError(
                        "Every BIDS case must map exactly one file per required role"
                    )
                _path, relative = _local_nifti(root, matches[0])
                mapped[role] = relative
            cases.append(
                {
                    "case_id": _opaque_case_id(
                        site_id=site_id,
                        subject=subject,
                        session=session,
                        case_id_key=case_id_key,
                    ),
                    "site_id": site_id,
                    "images": [mapped[modality] for modality in REQUIRED_MODALITIES],
                    "label": mapped["label"],
                }
            )

    if len(cases) < 2:
        raise DatasetValidationError(
            "BIDS intake requires at least two complete local cases"
        )
    payload = {
        "schema_version": "rarelink-site-manifest-v1",
        "source_format": "BIDS",
        "modalities": list(REQUIRED_MODALITIES),
        "allowed_label_values": list(allowed_label_values),
        "cases": cases,
    }
    if output_manifest.exists() and not overwrite:
        raise DatasetValidationError("The target local manifest already exists")
    if output_manifest.is_symlink():
        raise DatasetValidationError("The target local manifest must not be a symlink")
    output_manifest.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    output_manifest.write_text(rendered, encoding="utf-8")
    mapping_policy = {
        "schema_version": "rarelink-bids-mapping-policy-v1",
        "modalities": queries,
        "allowed_label_values": list(allowed_label_values),
    }
    return {
        "schema_version": "rarelink-bids-intake-receipt-v1",
        "passed": True,
        "source_format": "BIDS",
        "site_id": site_id,
        "case_count": len(cases),
        "modalities_per_case": 4,
        "mapping_policy_sha256": hashlib.sha256(
            _canonical_json(mapping_policy)
        ).hexdigest(),
        "manifest_sha256": hashlib.sha256(rendered.encode()).hexdigest(),
        "subject_entities_exported": False,
        "session_entities_exported": False,
        "source_paths_exported": False,
        "case_id_key_exported": False,
        "image_or_label_voxels_exported": False,
        "manifest_remains_hospital_local": True,
    }
