import argparse
import json
import os

os.environ["APP_ENV"] = "training-job-smoke"
os.environ["DATABASE_URL"] = "sqlite:///./artifacts/training-job-smoke.db"
os.environ["RARELINK_ALLOW_LLM"] = "false"
os.environ["RARELINK_FL_MODE"] = "nvflare"

from fastapi.testclient import TestClient  # noqa: E402

from rarelink.api.main import app  # noqa: E402


def expect_ok(response):  # type: ignore[no-untyped-def]
    if not response.is_success:
        raise RuntimeError(f"{response.request.method} {response.url}: {response.text}")
    return response.json()


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke-test the persisted real training job path")
    parser.add_argument("--strategy", choices=["local", "fedavg", "fedprox"], default="local")
    args = parser.parse_args()
    with TestClient(app) as client:
        study = expect_ok(
            client.post(
                "/api/studies",
                json={
                    "title": "Real local training job smoke",
                    "research_question": (
                        "Can the persisted job runner execute three isolated synthetic sites?"
                    ),
                    "disease_area": "synthetic rare-disease imaging benchmark",
                },
            )
        )
        study_id = study["id"]
        expect_ok(client.post(f"/api/studies/{study_id}/protocol:generate"))
        expect_ok(
            client.post(
                f"/api/studies/{study_id}/approve",
                json={"approved_by": "Smoke PI", "note": "synthetic data only"},
            )
        )
        expect_ok(client.post(f"/api/studies/{study_id}/feasibility:run"))
        proposal = expect_ok(client.post(f"/api/studies/{study_id}/contract:propose"))["content"]
        contract = {
            **proposal,
            "contract_id": f"contract-{study_id}",
            "strategies": [args.strategy],
            "rounds": 1,
            "local_epochs": 1,
            "approved_by": "Smoke PI",
        }
        expect_ok(client.post(f"/api/studies/{study_id}/contract:lock", json=contract))
        experiment = expect_ok(
            client.post(
                f"/api/studies/{study_id}/experiments",
                json={
                    "strategy": args.strategy,
                    "hypothesis": f"Execute the real {args.strategy} engineering baseline",
                    "parameters": {"mu": 0.01} if args.strategy == "fedprox" else {},
                },
            )
        )
        expect_ok(client.post(f"/api/experiments/{experiment['id']}:run"))
        jobs = expect_ok(client.get(f"/api/studies/{study_id}/training-jobs"))
        experiments = expect_ok(client.get(f"/api/studies/{study_id}/experiments"))
        final_study = expect_ok(client.get(f"/api/studies/{study_id}"))
        if jobs[-1]["status"] != "COMPLETED":
            raise RuntimeError(json.dumps(jobs[-1], ensure_ascii=False, indent=2))
        print(
            json.dumps(
                {
                    "study_id": study_id,
                    "study_status": final_study["status"],
                    "job_status": jobs[-1]["status"],
                    "job_progress": jobs[-1]["progress"],
                    "backend": jobs[-1]["backend"],
                    "metrics": experiments[-1]["metrics"],
                    "workspace": jobs[-1]["workspace"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
