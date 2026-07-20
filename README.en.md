# RareLink

<p align="center">
  <a href="README.md">中文</a> · <strong>English</strong>
</p>

<p align="center">
  <strong>Turn scarce cases into collaborative, verifiable research evidence.</strong><br/>
  DGX Spark × NVIDIA FLARE × MONAI × Step 3.7
</p>

<p align="center">
  <img src="https://img.shields.io/badge/NVIDIA-DGX%20Spark-76b900?style=flat-square" alt="NVIDIA DGX Spark" />
  <img src="https://img.shields.io/badge/NVIDIA%20FLARE-2.7.2-2563eb?style=flat-square" alt="NVIDIA FLARE" />
  <img src="https://img.shields.io/badge/MONAI-1.6.0-7c3aed?style=flat-square" alt="MONAI" />
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-0f766e?style=flat-square" alt="Apache-2.0" /></a>
</p>

> Research-use engineering prototype; not diagnostic or therapeutic advice. The competition medical-research validation uses three **logical sites** on one real DGX Spark, plus a Spark–Mac mTLS exercise. It is not a production multi-hospital deployment or clinical validation.

---

## Project overview

Rare-disease and small-cohort imaging research needs more than a model: it needs a way for multiple institutions to develop evidence when source data cannot be centralized. RareLink turns protocol design, site feasibility, experiment contracts, federated training, privacy review, and reporting into a controlled workflow: **data stays with the department, models train locally, only approved updates and aggregate metrics cross sites, and the process is recorded in an audit ledger.**

| Research challenge | RareLink implementation |
| --- | --- |
| MRI, labels and patient fields cannot be pooled | Local NIfTI/label processing; an input gateway rejects source images, identifiers, DICOM UIDs, secrets and small-cell fields from outbound paths |
| Mean performance can hide weak sites | Shows mean Dice, weakest-site Dice, site spread, and HD95 together |
| Agents can exceed scope or leave no trace | Five roles consume only de-identified protocols and aggregates; experiment contracts, I/O gates and human approval constrain them |
| Experiments are hard to replay | Fixed seeds, strategy matrix, result/model hashes, mTLS receipts, DP accounting, and one-click evidence verification |

### Verified engineering evidence

| Evidence | Result | Boundary |
| --- | --- | --- |
| Public imaging run | 24 MSD Task01 four-modality MRIs: geometry/hash checks, CUDA single-site training, one round of three-logical-site FedAvg, 3/3 updates and a persisted global model | Engineering smoke test; not paediatric, clinical, or real cross-hospital validation |
| Stability comparison | 5 seeds × 5 strategies × 3 rounds; 25/25 combinations completed | Synthetic/logical-site comparison, not medical statistical inference |
| Privacy and security | Opacus sample-level DP-SGD: conservative 3-round `ε=6.076881`, `δ=1e-5`; 26/26 Agent gateway cases passed | Not end-to-end, user-level, or hospital-level DP; not a penetration test |
| Secure federation exercise | Spark–Mac mTLS registration, reconnect, and invalid-identity rejection | Not a production hospital WAN or identity system |

The key configuration, methods, numeric results, data provenance, and limits are reproduced below so the evidence boundary is assessable without navigating through internal documents.

---

## NVIDIA platform and tools

DGX Spark is not used as a web server alone: it defines the local CUDA/3D-training boundary, runs NVIDIA FLARE workloads and the evidence API/web service, and provides an optional local-LLM route.

| Platform / tool | Role in RareLink | Evidence / use |
| --- | --- | --- |
| [NVIDIA DGX Spark](https://www.nvidia.com/en-us/products/workstations/dgx-spark/) | Local compute and runtime boundary | GB10 / ARM64 / CUDA 13 ran CUDA, MONAI 3D, FLARE and API/web services; the MSD one-round three-site aggregation completed in about 69 seconds |
| [CUDA](https://developer.nvidia.com/cuda) + PyTorch | Local tensor compute, AMP and training runtime | Runs MONAI training and federated client work on Spark |
| [NVIDIA FLARE](https://nvidia.github.io/NVFlare/) | FedAvg/FedProx, Client API, mTLS and orchestration | Three logical-site aggregation plus two-physical-device mTLS evidence |
| [Project MONAI](https://project-monai.github.io/) | NIfTI, 3D SegResNet, transforms, Dice/HD95 | Used for synthetic-imaging engineering controls and MSD Task01 verification |
| [TensorRT-LLM](https://github.com/NVIDIA/TensorRT-LLM) (optional) | Spark-local OpenAI-compatible Research Agent route | Metadata receipts, independent checks, 26 gateway red-team cases and `1/2/4` concurrency tools are implemented; the UI says `NOT CLAIMED` until a real local-model receipt exists |
| Step 3.7 | Policy-constrained experiment design, statistics/privacy review, research writing | Receives only de-identified text and aggregate metrics; falls back to deterministic template agents without a key |

## Product walkthrough and system screens

The frontend separates an interactive research-workflow sandbox from persisted hardware evidence. The sandbox demonstrates protocol, contract, Agent, and approval states. The evidence console recomputes hashes and verifies the three sites, global model, metrics, and stated boundaries.

<p align="center">
  <img src="assets/rarelink-overview.svg" alt="RareLink: departmental data, DGX Spark local training, FLARE aggregation, constrained Agent review and evidence cockpit" width="100%" />
</p>

### Real product screenshot

This is a capture from a locally running RareLink frontend—not a design mockup. The `DGX SPARK · VERIFIED RUN RECEIPT` panel reads a persisted public-MSD engineering receipt; reviewers can verify hashes and expand the site details. The imaging preview uses bundled synthetic de-identified demonstration slices and contains no patient image.

<p align="center">
  <img src="assets/screenshots/rarelink-live-evidence-console.png" alt="RareLink live evidence cockpit with DGX Spark receipt, three-site aggregation and local-model boundary" width="100%" />
</p>

### Reviewer path

1. Run the one-click reviewer package; it does not download images, model weights, certificates, or API keys.
2. Click **Verify local evidence hashes** in the evidence cockpit.
3. Expand the site receipt to view Dice, HD95, training time, aggregate metrics, and non-clinical boundary.
4. Create a demonstration study in the workflow sandbox to inspect protocol, site-statistics, contract, policy, and Agent evidence states.
5. Use `review_demo.sh` to reproduce the same evidence gates.

<p align="center">
  <img src="assets/rarelink-evidence-scorecard.svg" alt="RareLink evidence scorecard: 25/25 repeated experiments, 26/26 Agent gateway cases, sample-level DP-SGD, Spark-Mac mTLS and five-strategy comparison" width="100%" />
</p>

---

## Technical innovations

1. **Federated training becomes an evidence loop.** Protocols, feasibility, contracts, job states, aggregate metrics, model paths, and audit events form a traceable state machine rather than a single score.
2. **Compute and language-model boundaries are separated.** MRI/labels stay at the site; Spark runs image training; FLARE coordinates approved updates; Step 3.7 or local TensorRT-LLM consumes only de-identified text and aggregates.
3. **Privacy–utility is measured, not asserted.** Local, FedAvg, FedProx, strict SVT, and sample-level DP-SGD are compared while preserving both average and weakest-site metrics.
4. **Agents operate inside an auditable safety boundary.** Bidirectional gateways block source fields, identifiers, paths, secrets, and diagnostic instructions; 26 deterministic attack/safe controls run before and after Agent access.
5. **Local-LLM claims require evidence.** Endpoint availability, receipt capture, and independent verification are surfaced separately. No real receipt means `NOT CLAIMED`.

---

## System architecture and safety boundary

RareLink uses established open-source components for commodity capabilities. Its project-specific layer concentrates on the research state machine, experiment contracts, data-egress policy, evidence linkage, and the Spark/FLARE adapter. The control plane determines who can do what, when it can happen, and what evidence remains; it never bypasses the hospital data boundary.

```text
React evidence cockpit
        │  protocol / approval / verification / aggregate metrics
        ▼
FastAPI + Pydantic + SQLModel audit ledger
        ├── workflow state machine and experiment contract (PI lock)
        ├── input/output policy gateways and Agent artifact registry
        ├── FederationRunner
        │     ├── local development: deterministic Mock Runner (always labelled mock)
        │     └── Spark: MONAI + NVIDIA FLARE Recipe / Client API
        └── five-role Agent Team (de-identified text and aggregates only)
              Research Director → Experiment Designer → Statistical Reviewer
              → Privacy Reviewer → Research Writer

Department boundary: NIfTI, labels, patient fields and DICOM UIDs stay on site
Cross-site boundary: only contract-approved model updates and aggregate metrics
Agent boundary: no images, labels, case paths, credentials or small-cell detail
```

Every Agent output is validated against a Pydantic schema, persisted independently, and linked through the audit ledger. The Experiment Designer may propose a contract only; a principal investigator must approve and lock it. The Privacy Reviewer can block report release, but cannot loosen deterministic egress policy. The input gateway rejects source images, identifiers, DICOM UIDs, secrets, paths, and small-cell fields; the output gateway blocks diagnostic advice, unapproved contract changes, and unsafe reporting content.

### Spark execution design

In the prototype, `site-a`, `site-b`, and `site-c` are **logical sites** on one real DGX Spark. They validate federation tasks, aggregation, policy, and auditability; they do not represent three hospitals. NVIDIA FLARE 2.7.2 `FedAvgRecipe`, `SimEnv`, and Client APIs orchestrate the work directly, while MONAI SegResNet processes four-modality 3D NIfTI on CUDA. To avoid competing for unified memory, logical-site training is intentionally serialized on the single Spark. In a real deployment, each hospital runs an independent Spark Client and the coordinator aggregates approved updates only.

The local-LLM route follows the same boundary. TensorRT-LLM can serve an NVIDIA-supported model through a private `127.0.0.1` OpenAI-compatible endpoint, consuming only de-identified aggregate research context. The UI distinguishes “endpoint online,” “runtime receipt captured,” and “independently verified.” Without a real receipt it shows `NOT CLAIMED`; simulated data is never substituted for measurement.

---

## Experimental design, measured results, and interpretation

### Public real-imaging engineering verification

RareLink ran an engineering-compatibility verification on public MSD `Task01_BrainTumour` data using an NVIDIA DGX Spark GB10 (ARM64, CUDA 13, PyTorch `2.10.0+cu130`, MONAI `1.6.0`, NVIDIA FLARE `2.7.2`). The archive was downloaded directly by Spark and checked against its published MD5 and a local SHA-256. The repository contains no images, labels, case IDs, case-level paths, or weights. After geometry checks, 24 four-modality 3D MRIs were deterministically split by tumour-voxel quantiles into three logical sites of eight cases. The MSD `0/1/2/3` labels were mapped to the project’s `0/1/2` contract; depth 155 was padded to 156 with `DivisiblePadd(k=4)` to satisfy the network downsampling requirement.

| Run | Training configuration | Verifiable result |
| --- | --- | --- |
| Single-site CUDA smoke test | `site-a`: 7 train / 1 validation case, 1 epoch | Loss `1.818046`; mean foreground Dice `0.008702`; HD95 `117.379684`; `6.7476 s`; peak GPU memory `5240.349 MiB` |
| Three-logical-site FedAvg | 8 cases/site, 1 local epoch, 1 federation round | `3/3` client updates aggregated with global model persisted; `69.0084 s` end-to-end; peak GPU memory `5240.349 MiB` |

| Site | Dice | HD95 | Training loss | Local duration |
| --- | ---: | ---: | ---: | ---: |
| `site-a` | `0.012345` | `119.771957` | `1.657893` | `6.6302 s` |
| `site-b` | `0.040765` | `107.582993` | `1.653218` | `6.3943 s` |
| `site-c` | `0.071763` | `79.886047` | `1.649940` | `6.7046 s` |
| Aggregate observation | **`0.041624`** | **`102.413666`** | — | **`69.0084 s`** |

The weakest-site Dice was `0.012345`, with a site Dice standard deviation of `0.024265`. This supports the product choice to surface both average and weakest-site metrics. It **only** demonstrates successful real four-modality NIfTI intake, CUDA training, FLARE aggregation across three sites, and global-model persistence. It does not establish clinical efficacy, strategy superiority, real hospital-WAN communication, or paediatric rare-disease performance.

### Stability, privacy, and safety checks

| Check | Method | Result and boundary |
| --- | --- | --- |
| Stability | 5 random seeds × Local / FedAvg / FedProx / strict SVT / DP-SGD, 3 rounds | `25/25` combinations completed; synthetic data and logical sites only, for engineering-stability comparison |
| Sample-level DP-SGD | Opacus per-sample clipping, Gaussian noise, Poisson sampling, and RDP accounting | Conservative three-round `ε=6.076881`, `δ=1e-5`; covers local training steps only, not end-to-end, user-level, or hospital-level DP |
| Secure federation | Spark–Mac mTLS registration, reconnect, and invalid-identity rejection | Certificate-based communication exercise; not a hospital production network, identity system, or penetration test |
| Agent safety | 12 input + 14 output deterministic gateway cases | `26/26` passed; evaluates policy gateways, not general model-safety certification |

---

## Authoritative technology and data sources

| Topic | Authoritative source | Specific use / boundary in RareLink |
| --- | --- | --- |
| NVIDIA DGX Spark | [Product page](https://www.nvidia.com/en-us/products/workstations/dgx-spark/) · [User Guide](https://docs.nvidia.com/dgx/dgx-spark/index.html) | GB10 / ARM64 local 3D training, FLARE Client, and service deployment; not a bandwidth-centric centralized-data approach |
| CUDA | [NVIDIA CUDA](https://developer.nvidia.com/cuda) | PyTorch CUDA tensors and AMP training runtime |
| NVIDIA FLARE | [Docs](https://nvidia.github.io/NVFlare/) · [GitHub](https://github.com/NVIDIA/NVFlare) · [Healthcare catalog](https://nvidia.github.io/NVFlare/catalog/) | FedAvg/FedProx, Client API, mTLS; federated learning alone is not a compliance or privacy guarantee |
| MONAI | [Project MONAI](https://project-monai.github.io/) · [Docs](https://docs.monai.io/) | NIfTI transforms, 3D SegResNet, Dice / HD95 evaluation |
| PyTorch | [Documentation](https://pytorch.org/docs/stable/index.html) | Models, optimizers, AMP, and CUDA tensors |
| Opacus | [Website](https://opacus.ai/) · [PrivacyEngine API](https://opacus.ai/api/privacy_engine.html) | DP-SGD and privacy accounting; no end-to-end or institution-level DP claim |
| Federated learning definition and risks | [NIST glossary](https://csrc.nist.gov/glossary/term/federated_learning) · [NIST privacy-attack overview](https://www.nist.gov/blogs/cybersecurity-insights/privacy-attacks-federated-learning) | Data not being centralized does not mean updates and metrics cannot leak; policy, identity, audit, and DP remain necessary |
| Rare-disease research context | [NIH GARD FAQ](https://rarediseases.info.nih.gov/diseases/pages/31/faqs-about-rare-diseases) | “Rare disease” describes the research setting, not a diagnostic or epidemiological assertion |
| MSD Task01 | [Data page](https://medicaldecathlon.com/dataaws/) · [Official archive](https://msd-for-monai.s3-us-west-2.amazonaws.com/Task01_BrainTumour.tar) · [Paper](https://doi.org/10.1038/s41467-022-30695-9) | Current real public-imaging engineering verification; not a paediatric cohort or clinical-performance validation |
| BraTS-PEDs (future) | [TCIA collection](https://www.cancerimagingarchive.net/collection/brats-peds/) · [TCIA policy](https://www.cancerimagingarchive.net/tcia-data-usage-policy/) | Candidate for future paediatric public-data engineering verification, subject to data-use and citation requirements |
| Step 3.7 | [Stepfun Platform](https://platform.stepfun.com/) | Processes policy-approved de-identified protocols and aggregate context only; Step weights are not deployed on Spark |

---

## Future outlook

RareLink does not aim to replace clinicians. It aims to become a multi-center research operating system where **data does not leave the hospital and evidence remains traceable**.

| Stage | Goal | Prerequisites |
| --- | --- | --- |
| External engineering validation | Repeat the workflow with properly authorized public paediatric data such as BraTS-PEDs | Data-use policy, preprocessing, transparent reporting limits |
| Real multi-hospital pilot | Independent Spark client, certificate-based FLARE communication, and local audit at each hospital | IRB/data-use agreement/security review/network and identity readiness |
| Clinical research collaboration | PACS/FHIR integration, clinical governance, cross-site feasibility and evidence packages | Institutional partners, independent clinical validation, regulatory route |
| Local-Agent upgrade | Capture real TensorRT-LLM receipts, concurrency data and security red-team evidence on Spark | Available local model and compliant inference resources |

See the [one-page enterprise roadmap](outputs/RareLink-企业化一页路线图.md).

---

## Quick start

### One-click replay (recommended)

No medical images, weights, certificates, or API key are required. The script can create clearly labelled demonstration evidence only when a runtime artifact is missing; it never presents it as a new experiment.

```bash
git clone https://github.com/dingyucanada/RareLink.git
cd RareLink
bash scripts/review_demo.sh
```

Open the local address printed by the terminal. The package verifies four recorded engineering gates by default: `25/25` repeated experiments, sample-level DP-SGD accounting, Spark–Mac mTLS negative controls, and `26/26` Agent gateway cases. It does not download images, weights, certificates, or API keys. If a local runtime artifact is missing, it only writes a clearly labelled de-identified demonstration snapshot; it never represents it as a new experiment.

### Local development

```bash
cp .env.example .env
python3 -m venv .venv
. .venv/bin/activate
make install
make install-web
make dev-api
```

In a second terminal:

```bash
make dev-web
```

Open `http://localhost:5173`; API docs are at `http://localhost:8000/docs`. Without `STEP_API_KEY`, deterministic template agents still run the controlled workflow. Keep secrets in `.env` only.

### Optional real public-imaging engineering run

Download public MSD Task01 directly on Spark—do not upload large files through SSH/SCP. The scripts verify the public archive MD5, record hashes, and form three non-IID sites by tumour-volume quantiles:

```bash
python scripts/prepare_msd_brain_tumour.py \
  --data-root data/raw/msd-task01 \
  --output data/runtime/msd-brain-tumour-v1 \
  --cases-per-site 8

python scripts/run_nvflare_simulation.py \
  --manifest data/runtime/msd-brain-tumour-v1/manifest.json \
  --strategy fedavg --rounds 1 --local-epochs 1 \
  --workspace artifacts/msd-fedavg
```

Before deployment, verify `aarch64`, `nvidia-smi`, Python 3.11+, free disk, and a safe unified-memory margin; use the NVIDIA PyTorch container or the repository Spark bootstrap script. Source engineering records remain only as auditable indexes: [MSD run report](outputs/RareLink-2026-07-20-MSD真实影像Spark联邦运行报告.md), [Spark deployment guide](docs/deployment.md), and [formal system report](outputs/RareLink-2026-07-17-DGX-Spark系统移植与实机实验正式报告.md).

## Safety and responsible use

Never commit API keys, passwords, patient images, DICOM identifiers, source manifests, or identifiable clinical fields. Public data must follow source licences, citation and access policies. Any clinical or real multi-hospital deployment requires institutional approval, data-use agreements, security review, and independent validation.

## License

[Apache-2.0](LICENSE)
