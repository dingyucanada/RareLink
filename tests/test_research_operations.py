from __future__ import annotations

from fastapi.testclient import TestClient


def sha(character: str) -> str:
    return character * 64


def create_study(
    client: TestClient,
    *,
    organization_id: str = "hospital-network",
) -> dict:
    response = client.post(
        "/api/studies",
        json={
            "title": "Pediatric glioma federated study",
            "research_question": "Can federated learning improve the locked segmentation endpoint?",
            "disease_area": "pediatric high-grade glioma",
            "organization_id": organization_id,
            "created_by": "principal-investigator",
            "participating_sites": ["hospital-a", "hospital-b", "hospital-c"],
        },
    )
    assert response.status_code == 201
    return response.json()


def evidence_payload(*, actor: str = "package-builder", model_sha256: str | None = None) -> dict:
    return {
        "package_sha256": sha("a"),
        "manifest_sha256": sha("b"),
        "model_sha256": model_sha256 or sha("c"),
        "signature": "signed-evidence-package-ed25519-proof",
        "signing_key_fingerprint_sha256": sha("d"),
        "validation_tier": "L3_PHYSICAL",
        "site_count": 3,
        "required_quorum": 3,
        "privacy_gate_passed": True,
        "security_gate_passed": True,
        "dual_approval_distinct": True,
        "contains_sensitive_data": False,
        "verifier_version": "rarelink-evidence-v2",
        "actor": actor,
    }


def model_payload(*, actor: str = "model-builder") -> dict:
    return {
        "name": "pediatric-glioma-segresnet",
        "semantic_version": "1.0.0-rc1",
        "model_family": "MONAI SegResNet",
        "artifact_sha256": sha("c"),
        "source_job_id": "nvflare-job-physical-001",
        "validation_tier": "L3_PHYSICAL",
        "metrics": {
            "mean_dice": 0.82,
            "worst_site_dice": 0.76,
            "repeated_trials": 5,
        },
        "signature": "signed-global-model-ed25519-proof",
        "signing_key_fingerprint_sha256": sha("e"),
        "actor": actor,
    }


def transition(
    client: TestClient,
    path: str,
    *,
    target: str,
    actor: str,
    evidence_package_id: str | None = None,
) -> dict:
    payload = {
        "target": target,
        "actor": actor,
        "reason": f"Governance transition to {target}",
    }
    if evidence_package_id:
        payload["evidence_package_id"] = evidence_package_id
    response = client.post(path, json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def test_study_registry_tracks_site_membership_and_activation_gates(
    client: TestClient,
) -> None:
    study = create_study(client)
    assert study["organization_id"] == "hospital-network"
    assert study["created_by"] == "principal-investigator"
    assert study["participating_sites"] == [
        "hospital-a",
        "hospital-b",
        "hospital-c",
    ]

    memberships = client.get(f"/api/studies/{study['id']}/sites").json()
    assert len(memberships) == 3
    blocked = client.post(
        f"/api/studies/{study['id']}/sites/{memberships[0]['id']}:transition",
        json={
            "target": "ACTIVE",
            "actor": "site-administrator",
            "reason": "Attempt activation without governance proofs",
        },
    )
    assert blocked.status_code == 422
    assert "data-use approval" in blocked.text

    added = client.post(
        f"/api/studies/{study['id']}/sites",
        json={
            "site_id": "hospital-d",
            "display_name": "Hospital D",
            "organization": "hospital_d",
            "data_use_approved": True,
            "certificate_bound": True,
            "dataset_fingerprint": sha("f"),
            "actor": "research-lead",
        },
    )
    assert added.status_code == 201
    active = transition(
        client,
        f"/api/studies/{study['id']}/sites/{added.json()['id']}:transition",
        target="ACTIVE",
        actor="site-administrator",
    )
    assert active["status"] == "ACTIVE"
    assert active["contains_patient_data"] is False
    assert active["local_path_exported"] is False


def test_model_and_evidence_lifecycle_is_fail_closed_and_revocable(
    client: TestClient,
) -> None:
    study = create_study(client)
    model_response = client.post(
        f"/api/studies/{study['id']}/models",
        json=model_payload(),
    )
    assert model_response.status_code == 201
    model = model_response.json()

    model = transition(
        client,
        f"/api/studies/{study['id']}/models/{model['id']}:transition",
        target="STATISTICAL_REVIEW",
        actor="statistical-reviewer",
    )
    model = transition(
        client,
        f"/api/studies/{study['id']}/models/{model['id']}:transition",
        target="SECURITY_REVIEW",
        actor="security-reviewer",
    )
    blocked = client.post(
        f"/api/studies/{study['id']}/models/{model['id']}:transition",
        json={
            "target": "APPROVED",
            "actor": "model-reviewer",
            "reason": "Approval without evidence must fail",
        },
    )
    assert blocked.status_code == 422
    assert "verified evidence package" in blocked.text

    evidence_response = client.post(
        f"/api/studies/{study['id']}/evidence-packages",
        json=evidence_payload(),
    )
    assert evidence_response.status_code == 201
    evidence = evidence_response.json()
    same_actor = client.post(
        f"/api/studies/{study['id']}/evidence-packages/{evidence['id']}:transition",
        json={
            "target": "VERIFIED",
            "actor": "package-builder",
            "reason": "Self verification must fail",
        },
    )
    assert same_actor.status_code == 422
    assert "distinct" in same_actor.text

    evidence = transition(
        client,
        f"/api/studies/{study['id']}/evidence-packages/{evidence['id']}:transition",
        target="VERIFIED",
        actor="evidence-verifier",
    )
    same_verifier = client.post(
        f"/api/studies/{study['id']}/evidence-packages/{evidence['id']}:transition",
        json={
            "target": "RELEASED",
            "actor": "evidence-verifier",
            "reason": "Verifier cannot release the same package",
        },
    )
    assert same_verifier.status_code == 422
    evidence = transition(
        client,
        f"/api/studies/{study['id']}/evidence-packages/{evidence['id']}:transition",
        target="RELEASED",
        actor="principal-investigator",
    )

    model = transition(
        client,
        f"/api/studies/{study['id']}/models/{model['id']}:transition",
        target="APPROVED",
        actor="model-reviewer",
        evidence_package_id=evidence["id"],
    )
    model = transition(
        client,
        f"/api/studies/{study['id']}/models/{model['id']}:transition",
        target="RELEASED",
        actor="release-manager",
    )
    assert model["status"] == "RELEASED"
    assert model["signature_present"] is True
    assert model["model_binary_exported"] is False

    revoked = transition(
        client,
        f"/api/studies/{study['id']}/evidence-packages/{evidence['id']}:transition",
        target="REVOKED",
        actor="security-administrator",
    )
    assert revoked["status"] == "REVOKED"
    models = client.get(f"/api/studies/{study['id']}/models").json()
    assert models[0]["status"] == "REVOKED"
    assert models[0]["revoked_by"] == "security-administrator"


def test_registry_rejects_l2_evidence_and_cross_study_binding(
    client: TestClient,
) -> None:
    first = create_study(client, organization_id="network-one")
    second = create_study(client, organization_id="network-two")
    weak_payload = evidence_payload()
    weak_payload["validation_tier"] = "L2_ISOLATED"
    weak = client.post(
        f"/api/studies/{first['id']}/evidence-packages",
        json=weak_payload,
    ).json()
    blocked = client.post(
        f"/api/studies/{first['id']}/evidence-packages/{weak['id']}:transition",
        json={
            "target": "VERIFIED",
            "actor": "independent-reviewer",
            "reason": "L2 cannot become formal research evidence",
        },
    )
    assert blocked.status_code == 422
    assert "L3 physical or L4 hospital" in blocked.text

    second_evidence_payload = evidence_payload()
    second_evidence_payload["package_sha256"] = sha("1")
    second_evidence_payload["manifest_sha256"] = sha("2")
    second_evidence = client.post(
        f"/api/studies/{second['id']}/evidence-packages",
        json=second_evidence_payload,
    ).json()
    second_evidence = transition(
        client,
        f"/api/studies/{second['id']}/evidence-packages/{second_evidence['id']}:transition",
        target="VERIFIED",
        actor="second-network-reviewer",
    )

    model_response = client.post(
        f"/api/studies/{first['id']}/models",
        json=model_payload(),
    )
    model = model_response.json()
    model = transition(
        client,
        f"/api/studies/{first['id']}/models/{model['id']}:transition",
        target="STATISTICAL_REVIEW",
        actor="statistical-reviewer",
    )
    model = transition(
        client,
        f"/api/studies/{first['id']}/models/{model['id']}:transition",
        target="SECURITY_REVIEW",
        actor="security-reviewer",
    )
    cross_study = client.post(
        f"/api/studies/{first['id']}/models/{model['id']}:transition",
        json={
            "target": "APPROVED",
            "actor": "model-reviewer",
            "evidence_package_id": second_evidence["id"],
            "reason": "Cross study binding must fail",
        },
    )
    assert cross_study.status_code == 422
    assert "same study" in cross_study.text


def test_operations_summary_is_organization_scoped_and_deidentified(
    client: TestClient,
) -> None:
    first = create_study(client, organization_id="network-one")
    create_study(client, organization_id="network-two")
    response = client.get("/api/operations/summary?organization_id=network-one")
    assert response.status_code == 200
    summary = response.json()
    assert summary["studies"]["total"] == 1
    assert summary["sites"]["total"] == 3
    assert summary["organization_id"] == "network-one"
    assert summary["contains_patient_data"] is False
    assert summary["contains_secret"] is False
    assert first["research_question"] not in response.text
