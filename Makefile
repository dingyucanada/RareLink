PYTHON ?= python3

.PHONY: install install-web dev-api dev-web test lint smoke step-models step-smoke step-team-smoke synthetic-data monai-smoke nvflare-smoke nvflare-fedprox training-job-smoke

install:
	$(PYTHON) -m pip install -e ".[dev]"

install-web:
	npm --prefix apps/web install

dev-api:
	$(PYTHON) -m uvicorn rarelink.api.main:app --reload --host 0.0.0.0 --port 8000

dev-web:
	npm --prefix apps/web run dev -- --host 0.0.0.0

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check rarelink tests scripts

smoke:
	$(PYTHON) scripts/smoke_runtime.py

step-models:
	$(PYTHON) scripts/verify_step_api.py

step-smoke:
	$(PYTHON) scripts/smoke_step_protocol.py

step-team-smoke:
	$(PYTHON) scripts/smoke_step_agent_team.py

synthetic-data:
	$(PYTHON) scripts/prepare_demo_data.py --output data/runtime/synthetic-demo-v1

monai-smoke:
	$(PYTHON) scripts/train_monai_smoke.py --manifest data/runtime/synthetic-demo-v1/manifest.json --site site-a --epochs 1

nvflare-smoke:
	$(PYTHON) scripts/run_nvflare_simulation.py --manifest data/runtime/synthetic-demo-v1/manifest.json --strategy fedavg --rounds 2 --local-epochs 1

nvflare-fedprox:
	$(PYTHON) scripts/run_nvflare_simulation.py --manifest data/runtime/synthetic-demo-v1/manifest.json --strategy fedprox --rounds 2 --local-epochs 1

training-job-smoke:
	$(PYTHON) scripts/smoke_training_job.py
