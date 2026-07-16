# Development progress

## DGX Spark hardware milestone (2026-07-16 to 2026-07-17)

- [x] Deployed on a real NVIDIA DGX Spark GB10 with ARM64 and CUDA 13.0
- [x] Ran MONAI 3D SegResNet on CUDA and persisted a model checkpoint
- [x] Completed three-logical-site NVIDIA FLARE 2.7.2 FedAvg and FedProx aggregation
- [x] Completed the API training-job path from queue to global-model evidence
- [x] Published the React and FastAPI services through the allocated 8888/9000 mappings
- [x] Recorded initial node evidence in `outputs/DGX-Spark-实机验证报告.md`
- [x] Published the formal migration, experiment, reasoning, and limitation record in
  `outputs/RareLink-2026-07-17-DGX-Spark系统移植与实机实验正式报告.md`

## Completed vertical slice

- [x] Repository, Python, and web workspace scaffolding
- [x] Persistent study, experiment, and audit models
- [x] Research workflow transition guard
- [x] Step 3.7 client with safe template fallback
- [x] Aggregate egress policy and small-group suppression
- [x] Deterministic mock local/FedAvg/FedProx runner
- [x] Research workflow API
- [x] React research console
- [x] Backend policy, workflow, and end-to-end API tests
- [x] Frontend workflow test
- [x] Synthetic three-site, four-modal NIfTI generator with SHA-256 manifest
- [x] MONAI single-site SegResNet smoke runner
- [x] NVIDIA FLARE 2.7.2 Recipe/Client API integration for FedAvg and FedProx
- [x] Exportable research bundle and GFM report tables
- [x] Local CPU MONAI single-site training produced a SegResNet checkpoint
- [x] Local CPU three-site NVFLARE FedAvg produced an aggregated global model
- [x] Local CPU three-site NVFLARE FedProx used NVIDIA `PTFedProxLoss` and produced a global model
- [x] Step Plan endpoint and `step-3.7-flash` account access verified through the Models API
- [x] Live Step 3.7 JSON-mode protocol generation passed with a fully synthetic research request
- [x] Persistent Agent artifact registry and export bundle integration
- [x] Step 3.7 Experiment Designer, Statistical Reviewer, Privacy Reviewer, and Research Writer
- [x] Live four-role Step 3.7 Agent Team smoke run on synthetic aggregate evidence
- [x] Human approval remains mandatory between Agent proposal and locked experiment contract
- [x] Persistent FastAPI background training jobs with retryable failure state
- [x] Unified-memory guard serializes real workloads on a single Spark
- [x] Real three-site Local baseline metrics persisted through the API job path
- [x] Real three-site NVFLARE FedAvg metrics and global model persisted through the API job path
- [x] React live job cards for queue, progress, errors, logs, and global-model evidence
- [x] MONAI Dice and official HD95 metric integration through SciPy
- [x] Public MSD Task01 direct-download script, archive/file hashes and deterministic non-IID split
- [x] Optional public-demo access gate and injected pre-training failure/retry demo
- [x] Five-seed, five-strategy, three-round benchmark with aligned Local compute budget
- [x] FLARE mTLS startup-kit provisioning and three-client secure registration on Spark
- [x] SVTPrivacy model-update filter and privacy-utility comparison with claim boundaries
- [x] Four-modal synthetic MRI Canvas preview with local segmentation overlays
- [x] Evidence cockpit cards for robustness, mTLS runtime and privacy configuration
- [x] Opacus DP-SGD with sample clipping and three-round RDP accounting
- [x] Spark–Mac mTLS registration, dropout/reconnect, and wrong-identity negative control
- [x] Deterministic 26-case Agent input/output red team enforced around Step 3.7

## Next Spark milestone

- [x] Inspect the allocated DGX Spark runtime without changing it
- [x] Pin an ARM64-compatible PyTorch/MONAI environment after a GPU smoke test
- [x] Add synthetic NIfTI generation with MONAI transforms
- [x] Implement the single-site SegResNet training runner
- [x] Implement a three-site NVFLARE Recipe/Client simulation entry point
- [x] Run the MONAI and NVFLARE jobs on the allocated Spark GPU
- [x] Capture real Spark runtime and memory evidence in the evidence endpoint and reports

## Known boundaries

- `.env.example` defaults to deterministic mock mode for safe reproduction. Setting
  `RARELINK_FL_MODE=nvflare` switches the same control plane to persisted real jobs; the active local
  competition configuration now uses this mode.
- The command-line MONAI/NVFLARE runners perform real training, but the checked-in synthetic cohort is
  only an engineering fixture, not a clinical benchmark.
- Spark measurements are engineering observations only; no throughput superiority or clinical
  performance claim is made from the tiny synthetic cohort.
- NVFLARE `SimEnv` can emit a harmless Python multiprocessing semaphore warning during interpreter
  shutdown; success is determined by the persisted global-model postcondition, not process text alone.
- The allocated node's direct connection to the official MSD archive was measured at roughly 20–30 KiB/s
  on 2026-07-16. The public benchmark tooling is complete, but a full 7.1 GiB download should be resumed
  only when the competition network window permits it; no data are transferred through SSH.
