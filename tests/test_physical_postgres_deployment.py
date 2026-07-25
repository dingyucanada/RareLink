from pathlib import Path

import pytest

from scripts.validate_physical_postgres_compose import validate

PROJECT_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_PATH = PROJECT_ROOT / "deploy/physical/compose.coordinator-postgres.yml"
ENV_PATH = PROJECT_ROOT / "deploy/physical/coordinator-postgres.env.example"


def test_physical_postgres_deployment_policy() -> None:
    receipt = validate(COMPOSE_PATH, ENV_PATH)
    assert receipt == {
        "authentication_mode": "oidc",
        "committed_secrets_present": False,
        "external_persistent_volumes": True,
        "healthchecks_present": True,
        "physical_mode": "physical",
        "postgres_host_port_published": False,
        "schema_version": "rarelink-postgres-compose-validation-v1",
        "services": ["coordinator", "postgres"],
    }
    compose = COMPOSE_PATH.read_text(encoding="utf-8")
    assert "/api/health/ready" in compose
    assert "urlopen('http://127.0.0.1:9000/api/health'," not in compose


def test_spark_image_contains_migration_runtime() -> None:
    dockerfile = (PROJECT_ROOT / "deploy/Dockerfile.spark").read_text(encoding="utf-8")
    assert "COPY alembic.ini ./" in dockerfile
    assert "COPY alembic ./alembic" in dockerfile
    assert "alembic==" in dockerfile
    assert "psycopg[binary]==" in dockerfile


def test_physical_postgres_deployment_rejects_committed_secret(tmp_path: Path) -> None:
    unsafe_env = tmp_path / "unsafe.env"
    unsafe_env.write_text(
        ENV_PATH.read_text(encoding="utf-8").replace(
            "RARELINK_POSTGRES_PASSWORD=",
            "RARELINK_POSTGRES_PASSWORD=change-me",
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="forbidden default secret"):
        validate(COMPOSE_PATH, unsafe_env)
