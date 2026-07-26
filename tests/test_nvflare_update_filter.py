from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from nvflare.apis.dxo import DXO, DataKind
from nvflare.apis.filter import ContentBlockedException
from nvflare.apis.shareable import Shareable
from nvflare.app_common.app_constant import AppConstants

from rarelink.security.nvflare_update_filter import RareLinkUpdateGuardFilter


class FakePeerContext:
    def __init__(self, site_id: str) -> None:
        self.site_id = site_id

    def get_identity_name(self, default: str = "") -> str:
        return self.site_id or default


class FakeFLContext:
    def __init__(self, site_id: str, round_number: int = 1) -> None:
        self.peer = FakePeerContext(site_id)
        self.round_number = round_number

    def get_peer_context(self) -> FakePeerContext:
        return self.peer

    def get_job_id(self) -> str:
        return "nvflare-job-001"

    def get_prop(self, key: str, default: object = None) -> object:
        if key == AppConstants.CURRENT_ROUND:
            return self.round_number
        return default


def update_filter(path: Path) -> RareLinkUpdateGuardFilter:
    return RareLinkUpdateGuardFilter(
        expected_sites=["hospital-a", "hospital-b", "hospital-c"],
        max_l2_norm=5.0,
        replay_db_path=str(path),
        minimum_sample_count=2,
        minimum_cosine_similarity=0.0,
    )


def update(site_id: str = "hospital-a") -> tuple[DXO, Shareable, FakeFLContext]:
    dxo = DXO(
        DataKind.WEIGHT_DIFF,
        {"encoder.weight": np.array([[6.0, 8.0]], dtype=np.float32)},
        meta={"site_id": site_id, "sample_count": 8},
    )
    shareable = Shareable()
    shareable.add_cookie(AppConstants.CONTRIBUTION_ROUND, 1)
    return dxo, shareable, FakeFLContext(site_id)


def test_nvflare_filter_clips_before_aggregation_and_adds_safe_receipt(
    tmp_path: Path,
) -> None:
    guard = update_filter(tmp_path / "replay.sqlite")
    dxo, shareable, context = update()

    result = guard.process_dxo(dxo, shareable, context)

    assert np.allclose(result.data["encoder.weight"], [[3.0, 4.0]])
    receipt = result.get_meta_prop("rarelink_update_guard")
    assert receipt["accepted"] is True
    assert receipt["clipped"] is True
    assert receipt["raw_tensors_exported"] is False


def test_nvflare_filter_rejects_duplicate_site_round_after_restart(tmp_path: Path) -> None:
    path = tmp_path / "replay.sqlite"
    first = update_filter(path)
    dxo, shareable, context = update()
    first.process_dxo(dxo, shareable, context)

    reconstructed_filter = update_filter(path)
    duplicate, duplicate_shareable, duplicate_context = update()
    with pytest.raises(ContentBlockedException, match="Duplicate model update"):
        reconstructed_filter.process_dxo(
            duplicate,
            duplicate_shareable,
            duplicate_context,
        )


def test_nvflare_filter_rejects_claimed_site_mismatch(tmp_path: Path) -> None:
    guard = update_filter(tmp_path / "replay.sqlite")
    dxo, shareable, _context = update(site_id="hospital-b")

    with pytest.raises(ContentBlockedException, match="mTLS peer identity"):
        guard.process_dxo(dxo, shareable, FakeFLContext("hospital-a"))
