# Architecture

RareLink uses existing frameworks at every commodity layer:

- FastAPI and Pydantic for validated HTTP contracts;
- SQLModel/SQLAlchemy and SQLite for the persistent study and audit ledger;
- the OpenAI Python client for Step 3.7's compatible API;
- React Query for server state, Recharts for metric comparison, and React Markdown for reports;
- MONAI and NVIDIA FLARE behind a federation adapter on DGX Spark.

The project-specific code is intentionally limited to the research workflow, experiment contract,
patient-data egress policy, evidence linkage, and the Spark/FLARE adapter.

```text
React console → FastAPI → workflow + policy + ledger + agent artifact registry
                         ↘ Step 3.7 Agent Team (aggregate inputs only)
                            ├── Research Director → protocol
                            ├── Experiment Designer → fixed comparison proposal
                            ├── Statistical Reviewer → evidence and fairness review
                            ├── Privacy Reviewer → report release decision
                            └── Research Writer → evidence-grounded narrative
                         ↘ FederationRunner
                            ├── MockFederationRunner (local development)
                            └── MonaiNvflareRunner (local CPU or DGX Spark GPU)
```

Each Agent output is validated against a Pydantic schema, persisted independently, linked from the
audit ledger, and exported in `agent_artifacts.json`. The Experiment Designer can only propose a
contract; a human principal investigator must approve and lock it. The Privacy Reviewer can block
report generation but cannot relax the deterministic egress policy.

The mock runner is deterministic and is always labelled `mock mode`. It exists to develop and test the
control plane; it is not evidence of GPU or federated training.

The Spark path uses NVIDIA FLARE 2.7.2's maintained Recipe and Client APIs directly:

- `nvflare.app_opt.pt.recipes.FedAvgRecipe` defines FedAvg/FedProx jobs;
- `nvflare.recipe.SimEnv` runs the three named logical sites with one worker thread to limit unified-memory pressure;
- `nvflare.client` receives and returns MONAI SegResNet weights;
- NVIDIA's `PTFedProxLoss` supplies the proximal regularization term.

The same recipe can be exported for POC/production environments without rewriting the MONAI training
script. Auto-FL remains an optional feature flag after the stable FedAvg/FedProx path is proven.

In `nvflare` mode, FastAPI creates a persisted `TrainingJob` and returns immediately. A process-local
unified-memory guard serializes Local, FedAvg, and FedProx workloads on one Spark. Progress, logs,
aggregate Dice/HD95, workspace, failure details, and global-model paths are written back to SQLModel;
the React console polls these records every 1.5 seconds. A failed job is retryable without creating a
duplicate experiment.
