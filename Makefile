PYTHON ?= python3
PROJECT_PYTHON = $(if $(wildcard .venv/bin/python),.venv/bin/python,$(PYTHON))

.PHONY: install install-web dev-api dev-web test lint smoke step-models step-smoke step-team-smoke synthetic-data monai-smoke nvflare-smoke nvflare-fedprox training-job-smoke demo-seed demo-evidence spark-local-verify spark-local-benchmark privacy-redteam-smoke secure-aggregation-assessment physical-render physical-preflight physical-job physical-site-agent physical-control-smoke physical-postgres-validate p0-p1-acceptance site-data-validate db-upgrade db-current db-check

install:
	$(PROJECT_PYTHON) -m pip install -e ".[dev]"

install-web:
	npm --prefix apps/web install

dev-api:
	$(PROJECT_PYTHON) -m uvicorn rarelink.api.main:app --reload --host 0.0.0.0 --port 8000

dev-web:
	npm --prefix apps/web run dev -- --host 0.0.0.0

test:
	$(PROJECT_PYTHON) -m pytest

lint:
	$(PROJECT_PYTHON) -m ruff check rarelink tests scripts

smoke:
	$(PROJECT_PYTHON) scripts/smoke_runtime.py

step-models:
	$(PROJECT_PYTHON) scripts/verify_step_api.py

step-smoke:
	$(PROJECT_PYTHON) scripts/smoke_step_protocol.py

step-team-smoke:
	$(PROJECT_PYTHON) scripts/smoke_step_agent_team.py

synthetic-data:
	$(PROJECT_PYTHON) scripts/prepare_demo_data.py --output data/runtime/synthetic-demo-v1

monai-smoke:
	$(PROJECT_PYTHON) scripts/train_monai_smoke.py --manifest data/runtime/synthetic-demo-v1/manifest.json --site site-a --epochs 1

nvflare-smoke:
	$(PROJECT_PYTHON) scripts/run_nvflare_simulation.py --manifest data/runtime/synthetic-demo-v1/manifest.json --strategy fedavg --rounds 2 --local-epochs 1

nvflare-fedprox:
	$(PROJECT_PYTHON) scripts/run_nvflare_simulation.py --manifest data/runtime/synthetic-demo-v1/manifest.json --strategy fedprox --rounds 2 --local-epochs 1

training-job-smoke:
	$(PROJECT_PYTHON) scripts/smoke_training_job.py

demo-seed:
	$(PROJECT_PYTHON) scripts/seed_competition_evidence.py --target artifacts

demo-evidence: demo-seed
	$(PROJECT_PYTHON) scripts/verify_demo_evidence.py --artifact-root artifacts --write

spark-local-verify:
	$(PROJECT_PYTHON) scripts/verify_spark_local_inference_evidence.py --artifact-root artifacts --write

spark-local-benchmark:
	$(PROJECT_PYTHON) scripts/benchmark_spark_local_llm.py

privacy-redteam-smoke:
	$(PROJECT_PYTHON) scripts/run_art_privacy_smoke.py

secure-aggregation-assessment:
	$(PROJECT_PYTHON) scripts/evaluate_secure_aggregation.py

# Physical deployment commands intentionally require explicit topology/runtime paths.
# They never upload medical data, startup kits, certificates, or private keys.
physical-render:
	@echo "Usage: $(PROJECT_PYTHON) scripts/render_physical_federation.py --topology deploy/physical/topology.yml"

physical-preflight:
	@echo "Usage: $(PROJECT_PYTHON) scripts/validate_physical_site.py --topology ... --site-runtime ..."

physical-job:
	@echo "Usage: $(PROJECT_PYTHON) scripts/export_physical_nvflare_job.py --topology ... --output-dir ..."

physical-site-agent:
	@echo "Requires /etc/rarelink/site-agent.env or .env.site-agent with local-only paths and secrets"
	$(PROJECT_PYTHON) scripts/run_site_agent.py

physical-control-smoke:
	$(PROJECT_PYTHON) scripts/smoke_three_site_control_plane.py

physical-postgres-validate:
	$(PROJECT_PYTHON) scripts/validate_physical_postgres_compose.py

p0-p1-acceptance:
	$(PROJECT_PYTHON) scripts/accept_p0_p1.py --output artifacts/acceptance/p0-p1-receipt.json

site-data-validate:
	@echo "Usage: $(PROJECT_PYTHON) scripts/validate_site_dataset.py --manifest ... --site-id ... --data-root ... --output ..."

# Production schema changes are explicit operations. The API never upgrades a
# PostgreSQL database during startup.
db-upgrade:
	$(PROJECT_PYTHON) -m alembic upgrade head

db-current:
	$(PROJECT_PYTHON) -m alembic current

db-check:
	$(PROJECT_PYTHON) scripts/check_database_schema.py
