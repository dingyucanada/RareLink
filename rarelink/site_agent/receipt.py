"""Canonical HMAC receipts for safe task and heartbeat metadata."""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import datetime
from typing import Any

from rarelink.site_agent.schemas import SignedReceipt, TaskState, utc_now


def canonical_json(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


class ReceiptSigner:
    def __init__(self, site_id: str, secret: str) -> None:
        self.site_id = site_id
        self._secret = secret.encode("utf-8")
        self.key_id = hashlib.sha256(self._secret).hexdigest()[:16]

    def digest_and_signature(self, payload: dict[str, Any]) -> tuple[str, str]:
        encoded = canonical_json(payload)
        digest = hashlib.sha256(encoded).hexdigest()
        signature = hmac.new(self._secret, encoded, hashlib.sha256).hexdigest()
        return digest, signature

    def sign_task(
        self,
        *,
        event: str,
        task_id: str,
        round_id: int,
        total_rounds: int,
        contract_sha256: str,
        state: TaskState,
        revision: int,
        checkpoint_sha256: str | None = None,
        issued_at: datetime | None = None,
    ) -> SignedReceipt:
        observed_at = issued_at or utc_now()
        receipt_id = f"receipt-{uuid.uuid4().hex}"
        payload = {
            "schema_version": "rarelink-site-receipt-v1",
            "receipt_id": receipt_id,
            "event": event,
            "site_id": self.site_id,
            "task_id": task_id,
            "round_id": round_id,
            "total_rounds": total_rounds,
            "contract_sha256": contract_sha256,
            "state": state.value,
            "revision": revision,
            "issued_at": observed_at.isoformat(),
            "algorithm": "HMAC-SHA256",
            "key_id": self.key_id,
            "checkpoint_sha256": checkpoint_sha256,
            "contains_patient_data": False,
            "contains_local_paths": False,
            "contains_secret": False,
        }
        digest, signature = self.digest_and_signature(payload)
        return SignedReceipt(
            receipt_id=receipt_id,
            event=event,
            site_id=self.site_id,
            task_id=task_id,
            round_id=round_id,
            total_rounds=total_rounds,
            contract_sha256=contract_sha256,
            state=state,
            revision=revision,
            issued_at=observed_at,
            payload_sha256=digest,
            key_id=self.key_id,
            signature=signature,
            checkpoint_sha256=checkpoint_sha256,
        )

    def verify_task(self, receipt: SignedReceipt) -> bool:
        payload = {
            "schema_version": receipt.schema_version,
            "receipt_id": receipt.receipt_id,
            "event": receipt.event,
            "site_id": receipt.site_id,
            "task_id": receipt.task_id,
            "round_id": receipt.round_id,
            "total_rounds": receipt.total_rounds,
            "contract_sha256": receipt.contract_sha256,
            "state": receipt.state.value,
            "revision": receipt.revision,
            "issued_at": receipt.issued_at.isoformat(),
            "algorithm": receipt.algorithm,
            "key_id": receipt.key_id,
            "checkpoint_sha256": receipt.checkpoint_sha256,
            "contains_patient_data": receipt.contains_patient_data,
            "contains_local_paths": receipt.contains_local_paths,
            "contains_secret": receipt.contains_secret,
        }
        digest, signature = self.digest_and_signature(payload)
        return hmac.compare_digest(digest, receipt.payload_sha256) and hmac.compare_digest(
            signature, receipt.signature
        )

    def sign_heartbeat(
        self,
        *,
        timestamp: int,
        heartbeat_id: str,
        payload: dict[str, Any],
    ) -> tuple[str, str]:
        """Match the central API's replay-protected heartbeat signature contract."""
        digest = hashlib.sha256(canonical_json(payload)).hexdigest()
        message = f"{self.site_id}\n{timestamp}\n{heartbeat_id}\n{digest}".encode()
        signature = hmac.new(self._secret, message, hashlib.sha256).hexdigest()
        return digest, signature
