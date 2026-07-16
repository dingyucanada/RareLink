import json
from pathlib import Path

from scripts.capture_mtls_runtime_evidence import capture_runtime_evidence


def test_capture_mtls_runtime_evidence_redacts_runtime_tokens(tmp_path: Path) -> None:
    production = tmp_path / "project" / "prod_00"
    server = production / "localhost"
    (server / "startup").mkdir(parents=True)
    (server / "startup" / "fed_server.json").write_text(
        json.dumps(
            {
                "servers": [
                    {
                        "service": {"target": "localhost:8002"},
                        "connection_security": "mtls",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (server / "log.txt").write_text("2026-07-16 10:00:00 - root - INFO - Server started\n")
    for site in ("site-a", "site-b", "site-c"):
        root = production / site
        (root / "startup").mkdir(parents=True)
        (root / "startup" / "fed_client.json").write_text(
            json.dumps({"client": {"connection_security": "mtls"}}), encoding="utf-8"
        )
        (root / "log.txt").write_text(
            f"2026-07-16 10:00:01,001 - FederatedClient - INFO - "
            f"Successfully registered client:{site} for project demo. "
            "Token:secret-token SSID:secret-session\n",
            encoding="utf-8",
        )

    evidence = capture_runtime_evidence(tmp_path)

    serialized = json.dumps(evidence)
    assert evidence["registered_client_count"] == 3
    assert "secret-token" not in serialized
    assert "secret-session" not in serialized
