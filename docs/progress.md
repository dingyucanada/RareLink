# Development progress

## Physical P0/P1 production-software baseline (2026-07-26)

- [x] Site Agent preflight now covers GPU model/driver/CUDA/memory/temperature,
  CPU load, disk/memory, dependency contract, certificate identity/CA chain/offline
  CRL, local dataset proof, and signed checkpoint recovery.
- [x] Site Agent supports idempotent start/pause/stop/recover, durable replay state,
  outage reconnection, process-restart recovery, and patient-free signed receipts.
- [x] Physical controller has strict NVIDIA FLARE client-registry reconciliation,
  controlled result archive, strict three-site aggregate metrics, review-readiness
  gate, abort/retry/resume, and resumable SSE events.
- [x] The physical web console uses real control APIs and stable idempotency tokens;
  it displays live site/round/update/quorum, model integrity, signature, and review state.
- [x] The hospital-local data layer supports NIfTI + JSON manifest, deterministic
  splits, MONAI persistent cache receipts, PyBIDS indexing, and pydicom header-only
  de-identification gates without exporting paths or case identifiers.
- [x] Exported NVIDIA FLARE jobs include a durable-replay server input filter for
  peer identity, round, sample count, finite values, direction, norm, and L2 clipping.
- [x] ART membership-inference and MIFace engineering probes emit aggregate-only
  receipts and never persist sample decisions or reconstructions.
- [x] P1-S06 secure-aggregation selection and threat model choose NVIDIA FLARE
  `FedAvgHERecipe` + TenSEAL; enablement remains fail-closed until ARM64 runtime,
  hospital key governance, client-side pre-encryption checks, and a three-device
  encrypted-round benchmark exist.
- [x] Current acceptance baseline: 371 Python tests, Ruff, production web build,
  three independent control-plane processes, PostgreSQL compose validation, and
  Alembic migration round trip.

The itemized status and every external blocker are recorded in
[`p0-p1-engineering-log.md`](p0-p1-engineering-log.md). “Implemented” and
“isolated integration” are not presented as physical multi-hospital or clinical evidence.

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
- [x] Step runtime receipts record source, role, latency, usage, policy categories and response hash
  after schema and output-safety validation, without retaining prompt/completion content
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
- [x] Reviewer one-click compose stack, token-free evidence snapshot, and four-gate verifier
- [x] Evidence cockpit reading path with source/boundary and public-NIfTI intake status
- [x] Resumable direct MSD download and aggregate-only public NIfTI geometry-validation receipt
- [x] Spark public MNI152 structural-MRI/label intake validation: 91×109×91, 2 mm isotropic,
  SHA-256 recorded and no pixels/paths/case IDs exported in the receipt
- [x] MSD Task01 archive MD5/SHA-256 validation, 24-case four-modal NIfTI geometry validation and
  deterministic three-site non-IID partition on Spark
- [x] Hospital-local NIfTI v1 validation: four modalities, geometry/affine/orientation,
  label contract, path confinement and direct-identifier rejection
- [x] De-identified dataset receipt and three-site dataset-version binding; stale data
  automatically invalidates a pending/running physical job contract
- [x] Physical-control tamper-evident event chain with canonical SHA-256 history,
  HMAC-SHA256 events, recursive sensitive-field rejection, a public aggregate summary,
  and an operator-protected recent-event API
- [x] Physical mode fails closed when a managed audit HMAC key is absent or shorter than
  the P0 minimum; model verification, site heartbeats, job lifecycle and dataset-version
  invalidation enter the same chained ledger
- [x] Offline OIDC JWT validation against an administrator-supplied in-memory JWKS:
  RS256/ES256 allow-list and issuer/audience/signature/time/subject/role/organization/site checks
- [x] Fail-closed physical RBAC with five roles and ten permissions; physical mode
  rejects legacy operator tokens, while legacy compatibility remains isolated-integration only
- [x] OIDC tokens and raw claims are not persisted or appended to the physical audit chain
- [x] Canonical physical contract v1 SHA-256 binds study, strategy, bundle, sorted three-site
  identities, per-site dataset fingerprints, rounds, local epochs, and fixed 3-of-3 quorum
- [x] Physical mode persists a distinct OIDC second approval with a fixed attestation;
  approval note plaintext is discarded and only its SHA-256 is retained
- [x] Second approval expiry is persisted in the job and approval record, exposed as
  valid/expired state, and rechecked before submit/retry/resume
- [x] Authorized approval revocation creates an immutable reason-digest record and
  audit event; revoked contracts cannot submit/retry/resume
- [x] Contract approval is idempotent, competing approvals conflict, and submit/retry/resume
  re-verify the frozen contract and approval before reaching NVIDIA FLARE
- [x] OIDC `site_ids` resource scope requires every target site for registration,
  contract create/approve, submit, sync, abort, retry/resume, and model verification;
  denial happens before NVIDIA FLARE and does not enumerate missing sites
- [x] Physical site/job lists require OIDC state-read permission and filter by `site_ids`;
  audit details export only authorized site/job events while verifying the complete chain
- [x] Alembic `0001_initial_schema` covers all control-plane models, with schema
  drift tests, explicit psycopg 3 runtime, and production startup revision verification
- [x] Physical mode rejects SQLite; PostgreSQL deployment example keeps the database
  off host ports, requires OIDC and managed secrets, and persists database/artifacts
  in pre-created external volumes
- [x] PostgreSQL physical audit appends acquire a transaction advisory lock before
  reading the chain head; a unique predecessor index rejects any concurrent fork
- [x] Separate liveness/readiness probes; readiness queries the database and verifies
  Alembic head, while failures expose no database host, URL, credential, or exception
- [x] Physical CORS accepts exact HTTPS origins only; control responses use no-store,
  anti-frame, nosniff, CSP/Permissions Policy, and production HTTPS HSTS headers
- [x] MSD real-image single-site CUDA smoke and one-round three-logical-site NVFLARE FedAvg: 3/3
  updates aggregated, global model persisted, exit code 0

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
- The official MSD Task01 archive completed checksum verification, extraction, selected-case hashes,
  geometry intake and a one-round 24-case engineering run on 2026-07-20. Its low one-epoch Dice is not
  presented as clinical performance, method superiority or a pediatric rare-disease result; the three
  sites remain logical partitions on one Spark.
- A separate, small Project MONAI MNI152 public structural-MRI asset was validated on Spark as an
  external NIfTI I/O check. The Spark release host could not be reached directly, so the 1.4 MiB
  official asset pair was transparently transferred through encrypted SSH after source verification.
  This is not claimed as an MSD benchmark, federated training result, tumour result, or clinical evidence.
- The physical-control audit chain is a tamper-evident P0 pilot, not a WORM or
  non-repudiation system. SQLite does not serialize multi-worker append operations; not every
  rejected request is recorded; historical HMAC key-ring rotation is not implemented. Production
  requires PostgreSQL serialization, managed key rotation, protected external anchoring, and a
  complete low-risk rejection-event taxonomy. See
  [`physical-audit.md`](physical-audit.md).
- Physical operator OIDC currently consumes trusted JWKS supplied as environment JSON.
  Discovery, HTTPS JWKS retrieval, automatic caching/key rotation, MFA, and session revocation
  remain outstanding.
  See [`physical-identity-rbac.md`](physical-identity-rbac.md).
- Contract two-person approval, expiry, and revocation are implemented, but approval replacement,
  two-person authorization of the submit/retry/resume action itself and PostgreSQL concurrency
  remain outstanding. `isolated-integration` retains a legacy
  single-request path and is not approval evidence. See
  [`physical-dual-approval.md`](physical-dual-approval.md).
- Resource scope protects target-specific control operations. Public site/job lists and global
  audit read are not site-filtered; organization/study scope, wildcard-like coordinator
  governance, and cross-organization delegation remain future work. Legacy isolated integration
  bypasses scope and is not scope evidence. See
  [`physical-site-scope.md`](physical-site-scope.md).
# 2026-07-20 · 组织方 OpenClaw + ComfyUI 参考 Workshop 基础完赛

- 在 DGX Spark GB10 上执行组织方预置的 `workshop.ipynb`，输出独立 `workshop-executed.ipynb`；26 个代码单元无错误完成。
- 本地 Ollama `qwen3.6:35b`、ComfyUI 0.18.1（FLUX + PuLID）与 OpenClaw 2026.5.19 全部完成运行核验；官方样例生成耗时 51.87 秒，`superhero` Skill 状态为 `ready`。
- OpenClaw 默认 `main` Agent 已通过本地 Ollama 健康检查。由于 RareLink API 已占用 Spark 9000，Workshop Gateway 保持官方参考的 3030 端口，避免跨项目冲突。
- 聚合收据位于 [`artifacts/spark-openclaw-workshop-20260720/`](../artifacts/spark-openclaw-workshop-20260720/)。本项是赛事参考代码基础完赛证据，与 RareLink 医学科研功能独立，不作临床或医学影像结论。
