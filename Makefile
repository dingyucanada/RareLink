PYTHON ?= python3
PROJECT_PYTHON = $(if $(wildcard .venv/bin/python),.venv/bin/python,$(PYTHON))

.PHONY: install install-web dev-api dev-web test lint smoke step-models step-smoke step-team-smoke synthetic-data monai-smoke nvflare-smoke nvflare-fedprox training-job-smoke demo-seed demo-evidence

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
