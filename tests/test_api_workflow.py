import io
import json
import zipfile

from fastapi.testclient import TestClient


def test_complete_mock_research_workflow(client: TestClient) -> None:
    created = client.post(
        "/api/studies",
        json={
            "title": "Pediatric HGG federated study",
            "research_question": (
                "Can federated learning improve worst-site segmentation performance?"
            ),
            "disease_area": "pediatric high-grade glioma",
        },
    )
    assert created.status_code == 201
    study = created.json()
    study_id = study["id"]
    assert study["status"] == "DRAFT"

    protocol = client.post(f"/api/studies/{study_id}/protocol:generate")
    assert protocol.status_code == 200
    assert protocol.json()["protocol"]["source"] == "template"

    approval = client.post(
        f"/api/studies/{study_id}/approve",
        json={"approved_by": "Test PI", "note": "approved"},
    )
    assert approval.json()["status"] == "FEASIBILITY_RUNNING"

    feasibility = client.post(f"/api/studies/{study_id}/feasibility:run")
    assert feasibility.status_code == 200
    feasibility_payload = feasibility.json()["feasibility"]
    assert feasibility_payload["sites"][0]["age_buckets"]["0-5"] == "<5"
    assert "patient_id_list" not in feasibility_payload["sites"][0]

    proposal_response = client.post(f"/api/studies/{study_id}/contract:propose")
    assert proposal_response.status_code == 200
    proposal = proposal_response.json()["content"]
    assert proposal_response.json()["role"] == "experiment-designer-agent"
    assert proposal["strategies"] == ["local", "fedavg", "fedprox"]

    contract = client.post(
        f"/api/studies/{study_id}/contract:lock",
        json={
            **proposal,
            "contract_id": "test-contract",
            "approved_by": "Test PI",
        },
    )
    assert contract.status_code == 200
    assert contract.json()["status"] == "CONTRACT_LOCKED"

    for strategy in ["local", "fedavg", "fedprox"]:
        experiment = client.post(
            f"/api/studies/{study_id}/experiments",
            json={
                "strategy": strategy,
                "hypothesis": f"Evaluate {strategy} under the locked benchmark",
                "parameters": {"mu": 0.01} if strategy == "fedprox" else {},
            },
        )
        assert experiment.status_code == 201
        result = client.post(f"/api/experiments/{experiment.json()['id']}:run")
        assert result.status_code == 200
        assert result.json()["metrics"]["worst_site_dice"] > 0

    after_training = client.get(f"/api/studies/{study_id}").json()
    assert after_training["status"] == "RESULTS_REVIEW"

    review = client.post(f"/api/studies/{study_id}/review:generate")
    assert review.status_code == 200
    assert "not clinical evidence" in review.json()["review_markdown"]

    result_approval = client.post(
        f"/api/studies/{study_id}/approve",
        json={"approved_by": "Test PI", "note": "limitations reviewed"},
    )
    assert result_approval.json()["status"] == "PRIVACY_REVIEW"

    report = client.post(f"/api/studies/{study_id}/report:generate")
    assert report.status_code == 200
    assert report.json()["status"] == "REPORT_READY"
    assert "Experiment ledger" in report.json()["report_markdown"]

    export = client.get(f"/api/studies/{study_id}/export")
    assert export.status_code == 200
    assert export.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(export.content)) as archive:
        assert {
            "manifest.json",
            "protocol.json",
            "agent_artifacts.json",
            "training_jobs.json",
            "experiment_ledger.jsonl",
            "research_report.md",
            "reproduce.yaml",
        }.issubset(archive.namelist())
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["contains_patient_level_data"] is False
        assert manifest["simulated_sites"] is True

    artifacts = client.get(f"/api/studies/{study_id}/agent-artifacts").json()
    assert {item["artifact_type"] for item in artifacts} == {
        "research_protocol",
        "experiment_proposal",
        "evidence_review",
        "privacy_assessment",
        "research_narrative",
    }

    events = client.get(f"/api/studies/{study_id}/events").json()
    assert len(events) >= 12
    assert events[-1]["event_type"] == "report.generated"


def test_contract_rejects_raw_data_egress(client: TestClient) -> None:
    study = client.post(
        "/api/studies",
        json={
            "title": "Privacy boundary study",
            "research_question": "Can privacy policy prevent raw patient data from leaving a site?",
        },
    ).json()
    study_id = study["id"]
    client.post(f"/api/studies/{study_id}/protocol:generate")
    client.post(
        f"/api/studies/{study_id}/approve",
        json={"approved_by": "Test PI", "note": "approved"},
    )
    client.post(f"/api/studies/{study_id}/feasibility:run")

    response = client.post(
        f"/api/studies/{study_id}/contract:lock",
        json={
            "contract_id": "unsafe-contract",
            "approved_by": "Test PI",
            "raw_data_egress": True,
        },
    )
    assert response.status_code == 422
