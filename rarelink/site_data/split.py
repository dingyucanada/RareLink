"""Deterministic hospital-local train/validation partitioning.

The returned case objects remain inside the hospital process.  The public
receipt contains only aggregate counts and one binding digest; it never
contains case identifiers or per-case hashes.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any

OPAQUE_CASE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")


class DatasetSplitError(ValueError):
    """Safe split failure that does not echo a case identifier."""


@dataclass(frozen=True, slots=True)
class DeterministicDatasetSplit:
    train_cases: tuple[dict[str, Any], ...]
    validation_cases: tuple[dict[str, Any], ...]
    receipt: dict[str, Any]


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def deterministic_dataset_split(
    cases: list[dict[str, Any]],
    *,
    seed: int,
    validation_fraction: float = 0.2,
) -> DeterministicDatasetSplit:
    """Rank opaque local case IDs by a seeded SHA-256 score.

    This is stable across input ordering and Python processes. It is not a
    cryptographic anonymisation function; consequently no per-case score or
    identifier is included in the public receipt.
    """
    if (
        isinstance(seed, bool)
        or not isinstance(seed, int)
        or not 0 <= seed < 2**63
    ):
        raise DatasetSplitError("Split seed must be an integer between 0 and 2^63-1")
    if (
        isinstance(validation_fraction, bool)
        or not isinstance(validation_fraction, (int, float))
        or not math.isfinite(float(validation_fraction))
        or not 0 < float(validation_fraction) < 1
    ):
        raise DatasetSplitError("Validation fraction must be strictly between 0 and 1")
    if not isinstance(cases, list) or len(cases) < 2:
        raise DatasetSplitError("At least two local cases are required for a split")

    case_ids: list[str] = []
    for case in cases:
        case_id = case.get("case_id") if isinstance(case, dict) else None
        if not isinstance(case_id, str) or OPAQUE_CASE_ID.fullmatch(case_id) is None:
            raise DatasetSplitError("Every case must use a valid opaque local case ID")
        case_ids.append(case_id)
    if len(case_ids) != len(set(case_ids)):
        raise DatasetSplitError("Opaque local case IDs must be unique")

    def rank(index: int) -> tuple[bytes, str]:
        material = f"rarelink-split-v1\0{seed}\0{case_ids[index]}".encode()
        return hashlib.sha256(material).digest(), case_ids[index]

    ranked_indices = sorted(range(len(cases)), key=rank)
    validation_count = min(
        len(cases) - 1,
        max(1, math.ceil(len(cases) * float(validation_fraction))),
    )
    validation_indices = frozenset(ranked_indices[:validation_count])
    train_cases = tuple(
        case for index, case in enumerate(cases) if index not in validation_indices
    )
    validation_cases = tuple(
        case for index, case in enumerate(cases) if index in validation_indices
    )
    assignment = sorted(
        (
            case_ids[index],
            "validation" if index in validation_indices else "train",
        )
        for index in range(len(cases))
    )
    receipt = {
        "schema_version": "rarelink-dataset-split-receipt-v1",
        "algorithm": "seeded-sha256-rank-v1",
        "seed": seed,
        "validation_fraction": float(validation_fraction),
        "case_count": len(cases),
        "train_case_count": len(train_cases),
        "validation_case_count": len(validation_cases),
        "assignment_sha256": hashlib.sha256(_canonical_json(assignment)).hexdigest(),
        "case_identifiers_exported": False,
        "per_case_scores_exported": False,
        "case_assignments_exported": False,
    }
    return DeterministicDatasetSplit(
        train_cases=train_cases,
        validation_cases=validation_cases,
        receipt=receipt,
    )
