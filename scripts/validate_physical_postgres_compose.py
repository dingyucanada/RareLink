"""Read-only policy checks for the physical coordinator PostgreSQL example."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

SENSITIVE_ENV_NAMES = {
    "RARELINK_COORDINATOR_IMAGE",
    "RARELINK_POSTGRES_PASSWORD",
    "RARELINK_DATABASE_URL",
    "RARELINK_MODEL_SIGNING_PRIVATE_KEY_HOST_PATH",
    "RARELINK_NVFLARE_ADMIN_KIT_HOST_PATH",
    "RARELINK_PHYSICAL_SITE_SECRETS",
    "RARELINK_AUDIT_HMAC_KEY",
    "RARELINK_METRICS_BEARER_TOKEN",
    "RARELINK_OIDC_JWKS_JSON",
}
FORBIDDEN_SECRET_VALUES = {
    "password",
    "postgres",
    "changeme",
    "change-me",
    "secret",
    "admin",
    "rarelink",
}


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a YAML mapping")
    return value


def parse_env_template(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        name, separator, value = stripped.partition("=")
        if not separator or not name:
            raise ValueError("Environment template contains an invalid assignment")
        if name in values:
            raise ValueError(f"Environment template repeats {name}")
        values[name] = value
    return values


def validate(compose_path: Path, env_path: Path) -> dict[str, object]:
    compose = _mapping(
        yaml.safe_load(compose_path.read_text(encoding="utf-8")),
        "Compose document",
    )
    services = _mapping(compose.get("services"), "services")
    if set(services) != {"postgres", "coordinator"}:
        raise ValueError("Compose must contain exactly postgres and coordinator services")
    postgres = _mapping(services["postgres"], "postgres")
    coordinator = _mapping(services["coordinator"], "coordinator")

    if postgres.get("ports"):
        raise ValueError("PostgreSQL must not publish a host port")
    if not postgres.get("healthcheck"):
        raise ValueError("PostgreSQL requires a healthcheck")
    if not coordinator.get("healthcheck"):
        raise ValueError("Coordinator requires a healthcheck")
    coordinator_healthcheck = json.dumps(coordinator["healthcheck"], sort_keys=True)
    if "/api/health/ready" not in coordinator_healthcheck:
        raise ValueError("Coordinator healthcheck must use the database readiness endpoint")
    dependency = _mapping(coordinator.get("depends_on"), "coordinator.depends_on")
    postgres_dependency = _mapping(dependency.get("postgres"), "depends_on.postgres")
    if postgres_dependency.get("condition") != "service_healthy":
        raise ValueError("Coordinator must wait for a healthy PostgreSQL service")

    postgres_environment = _mapping(postgres.get("environment"), "postgres.environment")
    coordinator_environment = _mapping(
        coordinator.get("environment"), "coordinator.environment"
    )
    if ":?" not in str(postgres_environment.get("POSTGRES_PASSWORD", "")):
        raise ValueError("PostgreSQL password interpolation must reject empty values")
    if ":?" not in str(coordinator_environment.get("DATABASE_URL", "")):
        raise ValueError("Coordinator DATABASE_URL must reject empty values")
    if coordinator_environment.get("RARELINK_PHYSICAL_MODE") != "physical":
        raise ValueError("Coordinator must explicitly enable physical mode")
    if coordinator_environment.get("RARELINK_PHYSICAL_AUTH_MODE") != "oidc":
        raise ValueError("Coordinator must explicitly select OIDC")
    if ":?" not in str(
        coordinator_environment.get("RARELINK_PHYSICAL_APPROVAL_TTL_SECONDS", "")
    ):
        raise ValueError("Coordinator must require an explicit second-approval lifetime")
    if coordinator_environment.get("RARELINK_OBSERVABILITY_ENABLED") != "true":
        raise ValueError("Coordinator must enable the reviewed observability boundary")
    if ":?" not in str(
        coordinator_environment.get("RARELINK_METRICS_BEARER_TOKEN", "")
    ):
        raise ValueError("Coordinator must require a protected metrics token")
    if ":?" not in str(coordinator_environment.get("RARELINK_OTEL_ENDPOINT", "")):
        raise ValueError("Coordinator must require an approved OTLP endpoint")

    volumes = _mapping(compose.get("volumes"), "volumes")
    for name in ("postgres-data", "coordinator-artifacts"):
        volume = _mapping(volumes.get(name), f"volume {name}")
        if volume.get("external") is not True:
            raise ValueError(f"{name} must be an external persistent volume")

    env = parse_env_template(env_path)
    missing = sorted(SENSITIVE_ENV_NAMES - set(env))
    if missing:
        raise ValueError("Environment template is missing required sensitive variables")
    unsafe = {
        name: value
        for name, value in env.items()
        if name in SENSITIVE_ENV_NAMES
        and value
        and value.strip().lower() in FORBIDDEN_SECRET_VALUES
    }
    if unsafe:
        raise ValueError("Environment template contains a forbidden default secret")
    populated_secrets = sorted(
        name
        for name in SENSITIVE_ENV_NAMES
        if name != "RARELINK_COORDINATOR_IMAGE" and env.get(name)
    )
    if populated_secrets:
        raise ValueError("Sensitive values must remain blank in the committed env example")

    return {
        "schema_version": "rarelink-postgres-compose-validation-v1",
        "services": sorted(services),
        "postgres_host_port_published": False,
        "healthchecks_present": True,
        "external_persistent_volumes": True,
        "physical_mode": "physical",
        "authentication_mode": "oidc",
        "prometheus_metrics_protected": True,
        "opentelemetry_endpoint_required": True,
        "committed_secrets_present": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--compose",
        type=Path,
        default=Path("deploy/physical/compose.coordinator-postgres.yml"),
    )
    parser.add_argument(
        "--env-example",
        type=Path,
        default=Path("deploy/physical/coordinator-postgres.env.example"),
    )
    args = parser.parse_args()
    print(json.dumps(validate(args.compose, args.env_example), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
