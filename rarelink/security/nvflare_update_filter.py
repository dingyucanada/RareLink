"""NVIDIA FLARE server-input filter for RareLink's update guard."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from nvflare.apis.dxo import DXO, DataKind, MetaKey
from nvflare.apis.dxo_filter import DXOFilter
from nvflare.apis.filter import ContentBlockedException
from nvflare.apis.fl_context import FLContext
from nvflare.apis.shareable import Shareable
from nvflare.app_common.app_constant import AppConstants

from rarelink.security.update_guard import (
    ModelUpdateEnvelope,
    SQLiteReplayRegistry,
    UpdateGuardError,
    UpdateGuardPolicy,
    guard_model_update,
)


class RareLinkUpdateGuardFilter(DXOFilter):
    """Validate and clip every client update before NVIDIA FLARE aggregation.

    The filter trusts the mTLS peer identity from ``FLContext`` rather than a
    caller-provided site name. Replay claims are persisted before an accepted
    update can reach the aggregator.
    """

    def __init__(
        self,
        *,
        expected_sites: list[str],
        max_l2_norm: float,
        replay_db_path: str,
        minimum_sample_count: int = 1,
        minimum_cosine_similarity: float = -0.25,
        max_parameters: int = 50_000_000,
    ) -> None:
        super().__init__(
            supported_data_kinds=[DataKind.WEIGHTS, DataKind.WEIGHT_DIFF],
            data_kinds_to_filter=[DataKind.WEIGHTS, DataKind.WEIGHT_DIFF],
        )
        self.policy = UpdateGuardPolicy(
            expected_sites=frozenset(expected_sites),
            max_l2_norm=max_l2_norm,
            max_parameters=max_parameters,
            minimum_sample_count=minimum_sample_count,
            minimum_cosine_similarity=minimum_cosine_similarity,
        )
        self.policy.validate()
        self.replay_db_path = replay_db_path
        self.replay_registry: SQLiteReplayRegistry | None = None
        self._round_references: dict[int, list[float]] = {}
        self._round_reference_counts: dict[int, int] = {}

    @staticmethod
    def _site_id(dxo: DXO, fl_ctx: FLContext) -> str:
        peer_context = fl_ctx.get_peer_context()
        if peer_context is None:
            raise UpdateGuardError("Authenticated FLARE peer context is missing")
        site_id = str(peer_context.get_identity_name(default=""))
        claimed_site = dxo.get_meta_prop("site_id")
        if claimed_site is not None and claimed_site != site_id:
            raise UpdateGuardError("Client metadata does not match mTLS peer identity")
        return site_id

    @staticmethod
    def _round_number(dxo: DXO, shareable: Shareable, fl_ctx: FLContext) -> int:
        raw_round = shareable.get_cookie(AppConstants.CONTRIBUTION_ROUND)
        if raw_round is None:
            raw_round = dxo.get_meta_prop(MetaKey.CURRENT_ROUND)
        if raw_round is None:
            raw_round = fl_ctx.get_prop(AppConstants.CURRENT_ROUND)
        if isinstance(raw_round, bool):
            raise UpdateGuardError("Federation round is invalid")
        try:
            round_number = int(raw_round)
        except (TypeError, ValueError) as exc:
            raise UpdateGuardError("Federation round is missing or invalid") from exc
        if round_number < 0:
            raise UpdateGuardError("Federation round cannot be negative")
        return round_number

    @staticmethod
    def _tensor_payload(data: dict[str, Any]) -> tuple[dict[str, list[float]], dict[str, Any]]:
        flattened: dict[str, list[float]] = {}
        shapes: dict[str, tuple[int, ...]] = {}
        dtypes: dict[str, Any] = {}
        for name, raw_value in data.items():
            value = np.asarray(raw_value)
            if value.size == 0:
                raise UpdateGuardError("Model update contains an empty tensor")
            flattened[name] = value.reshape(-1).astype(np.float64).tolist()
            shapes[name] = value.shape
            dtypes[name] = value.dtype
        return flattened, {"shapes": shapes, "dtypes": dtypes}

    def _update_reference(self, round_number: int, flattened: list[float]) -> None:
        previous = self._round_references.get(round_number)
        count = self._round_reference_counts.get(round_number, 0)
        if previous is None:
            self._round_references[round_number] = flattened
            self._round_reference_counts[round_number] = 1
            return
        if len(previous) != len(flattened):
            raise UpdateGuardError("Accepted update shape changed within a round")
        next_count = count + 1
        self._round_references[round_number] = [
            (old * count + new) / next_count
            for old, new in zip(previous, flattened, strict=True)
        ]
        self._round_reference_counts[round_number] = next_count
        for stale_round in tuple(self._round_references):
            if stale_round < round_number - 1:
                self._round_references.pop(stale_round, None)
                self._round_reference_counts.pop(stale_round, None)

    def process_dxo(
        self,
        dxo: DXO,
        shareable: Shareable,
        fl_ctx: FLContext,
    ) -> DXO:
        try:
            site_id = self._site_id(dxo, fl_ctx)
            round_number = self._round_number(dxo, shareable, fl_ctx)
            if not isinstance(dxo.data, dict):
                raise UpdateGuardError("Model update must be a tensor mapping")
            tensors, metadata = self._tensor_payload(dxo.data)
            sample_count = dxo.get_meta_prop("sample_count")
            if isinstance(sample_count, bool):
                raise UpdateGuardError("Model update sample count is invalid")
            try:
                sample_count = int(sample_count)
            except (TypeError, ValueError) as exc:
                raise UpdateGuardError("Model update sample count is missing or invalid") from exc
            reference = self._round_references.get(round_number)
            if self.replay_registry is None:
                self.replay_registry = SQLiteReplayRegistry(Path(self.replay_db_path))
            guarded = guard_model_update(
                ModelUpdateEnvelope(
                    job_id=fl_ctx.get_job_id(),
                    site_id=site_id,
                    round_number=round_number,
                    nonce=f"round-{round_number}",
                    sample_count=sample_count,
                    tensors=tensors,
                ),
                expected_round=round_number,
                policy=self.policy,
                replay_registry=self.replay_registry,
                reference_update=reference,
            )
            clipped_data: dict[str, np.ndarray] = {}
            accepted_flattened: list[float] = []
            for name in sorted(guarded.tensors):
                flat = np.asarray(guarded.tensors[name], dtype=metadata["dtypes"][name])
                clipped_data[name] = flat.reshape(metadata["shapes"][name])
                accepted_flattened.extend(float(item) for item in flat)
            self._update_reference(round_number, accepted_flattened)
            dxo.data = clipped_data
            dxo.set_meta_prop("rarelink_update_guard", guarded.receipt)
            return dxo
        except (TypeError, ValueError, UpdateGuardError) as exc:
            raise ContentBlockedException(f"RareLink update guard blocked content: {exc}") from exc
