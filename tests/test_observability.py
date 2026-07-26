from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from rarelink.config import Settings
from rarelink.observability import configure_observability

TOKEN = "m" * 48


def test_prometheus_endpoint_is_authenticated_and_uses_route_templates() -> None:
    app = FastAPI()

    @app.get("/jobs/{job_id}")
    def job(job_id: str) -> dict[str, str]:
        return {"job_id": job_id}

    configure_observability(
        app,
        Settings(
            _env_file=None,
            rarelink_observability_enabled=True,
            rarelink_metrics_bearer_token=TOKEN,
        ),
    )
    client = TestClient(app)
    assert client.get("/internal/metrics").status_code == 401

    hidden_identifier = "physical-job-private-123"
    assert client.get(f"/jobs/{hidden_identifier}").status_code == 200
    response = client.get(
        "/internal/metrics",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert response.status_code == 200
    assert "rarelink_http_requests_total" in response.text
    assert 'route="/jobs/{job_id}"' in response.text
    assert hidden_identifier not in response.text
    assert response.headers["cache-control"] == "no-store"
