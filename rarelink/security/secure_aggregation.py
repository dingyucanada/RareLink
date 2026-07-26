"""Fail-closed readiness assessment for encrypted federated aggregation."""

from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import json
from typing import Any


def _package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ModuleNotFoundError, ValueError):
        return False


def assess_secure_aggregation_readiness(
    *,
    expected_sites: tuple[str, ...],
    required_quorum: int,
) -> dict[str, Any]:
    """Assess whether RareLink may enable NVIDIA FLARE homomorphic encryption.

    This function does not import the HE recipe because its import correctly
    fails when the optional TenSEAL runtime is absent. The resulting receipt is
    an environment and design decision, not evidence that encrypted aggregation
    ran on physical devices.
    """

    if len(set(expected_sites)) != len(expected_sites) or not expected_sites:
        raise ValueError("expected_sites must contain unique non-empty site identities")
    if required_quorum != len(expected_sites):
        raise ValueError("RareLink production policy requires all expected sites")

    nvflare_version = _package_version("nvflare")
    tenseal_version = _package_version("tenseal")
    recipe_available = _module_available("nvflare.app_opt.pt.recipes.fedavg_he")
    runtime_ready = bool(nvflare_version and recipe_available and tenseal_version)
    decision = "eligible-for-physical-benchmark" if runtime_ready else "deferred-fail-closed"

    receipt: dict[str, Any] = {
        "schema_version": "rarelink-secure-aggregation-assessment-v1",
        "decision": decision,
        "enabled": False,
        "expected_sites": list(expected_sites),
        "required_quorum": required_quorum,
        "candidate": {
            "framework": "NVIDIA FLARE",
            "recipe": "FedAvgHERecipe",
            "mechanism": "homomorphic encryption via TenSEAL",
            "nvflare_version": nvflare_version,
            "recipe_available": recipe_available,
            "tenseal_version": tenseal_version,
        },
        "threats_addressed": [
            "honest-but-curious coordinator inspecting an individual plaintext update",
            "plaintext model-update disclosure in coordinator aggregation memory",
        ],
        "threats_not_addressed": [
            "malicious client model poisoning",
            "membership inference or model inversion from the released global model",
            "compromised hospital endpoint before encryption",
            "availability failure or collusion outside the selected HE threat model",
        ],
        "design_constraints": [
            "mTLS remains mandatory for authenticated transport; it is not secure aggregation",
            "three-of-three quorum may not silently downgrade when one site is unavailable",
            "DP-SGD and update clipping must execute locally before encryption",
            "server-side plaintext tensor inspection is incompatible with HE-protected updates",
            "key ownership, rotation, recovery and deletion require an approved hospital policy",
        ],
        "required_before_enablement": [
            "install and pin a compatible TenSEAL build on ARM64 DGX Spark",
            "move clipping and finite-value checks into the signed client execution boundary",
            "provision HE context and keys outside the repository",
            "benchmark accuracy, memory, round latency, ciphertext size and dropout behavior",
            "record a three-device encrypted-round receipt and an explicit no-downgrade test",
            "complete security review of key custody and client-collusion assumptions",
        ],
        "claim_boundary": (
            "This receipt closes P1-S06 design selection and runtime-gap assessment only. "
            "It is not evidence that secure aggregation has executed."
        ),
    }
    canonical = json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    receipt["receipt_sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
    return receipt
