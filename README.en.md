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

Read the [MSD real-imaging Spark report](outputs/RareLink-2026-07-20-MSD真实影像Spark联邦运行报告.md) and [formal Spark migration report](outputs/RareLink-2026-07-17-DGX-Spark系统移植与实机实验正式报告.md) for methods and limitations.

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

### Organizer reference-workshop baseline

Independently from the medical-research workflow, the organizer-provided **OpenClaw + ComfyUI Workshop** was completed on the same DGX Spark: the official notebook completed 26 code cells without errors; local Ollama `qwen3.6:35b`, ComfyUI 0.18.1 with the FLUX + PuLID official sample (51.87 seconds), and OpenClaw 2026.5.19 with the `superhero` Skill were all verified. This is **baseline reference-code completion**, never a clinical or medical-imaging claim. See the [completion receipt and boundaries](docs/progress.md#2026-07-20--组织方-openclaw--comfyui-参考-workshop-基础完赛).

---

## Product walkthrough and system screens

The frontend separates an interactive research-workflow sandbox from persisted hardware evidence. The sandbox demonstrates protocol, contract, Agent, and approval states. The evidence console recomputes hashes and verifies the three sites, global model, metrics, and stated boundaries.

<p align="center">
  <img src="assets/rarelink-overview.svg" alt="RareLink: departmental data, DGX Spark local training, FLARE aggregation, constrained Agent review and evidence cockpit" width="100%" />
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

The three-minute demo should show real interaction—not slides alone: verify hashes, expand a site receipt, then show the Agent workflow and reproducibility package. Use the [demo script](outputs/RareLink-三分钟演示视频脚本.md).

---

## Technical innovations

1. **Federated training becomes an evidence loop.** Protocols, feasibility, contracts, job states, aggregate metrics, model paths, and audit events form a traceable state machine rather than a single score.
2. **Compute and language-model boundaries are separated.** MRI/labels stay at the site; Spark runs image training; FLARE coordinates approved updates; Step 3.7 or local TensorRT-LLM consumes only de-identified text and aggregates.
3. **Privacy–utility is measured, not asserted.** Local, FedAvg, FedProx, strict SVT, and sample-level DP-SGD are compared while preserving both average and weakest-site metrics.
4. **Agents operate inside an auditable safety boundary.** Bidirectional gateways block source fields, identifiers, paths, secrets, and diagnostic instructions; 26 deterministic attack/safe controls run before and after Agent access.
5. **Local-LLM claims require evidence.** Endpoint availability, receipt capture, and independent verification are surfaced separately. No real receipt means `NOT CLAIMED`.

See [architecture](docs/architecture.md) and [authoritative technical/data references](docs/references.md).

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

### One-click reviewer replay (recommended)

No medical images, weights, certificates, or API key are required. The script can create clearly labelled demonstration evidence only when a runtime artifact is missing; it never presents it as a new experiment.

```bash
git clone https://github.com/dingyucanada/RareLink.git
cd RareLink
bash scripts/review_demo.sh
```

Open the local address printed by the terminal, or read [DEMO.md](DEMO.md) for the four expected evidence gates.

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

See [DGX Spark deployment](docs/deployment.md) for ARM64/CUDA checks, data limitations, and full commands.

### Project documents

- [Competition project description](outputs/RareLink-比赛项目说明.md)
- [Technology stack](outputs/RareLink-技术栈说明.md)
- [Final submission checklist](outputs/RareLink-最终提交清单.md)
- [DGX Spark hackathon ten-day log](outputs/RareLink-DGX-Spark黑客松十日谈.md)

## Safety and responsible use

Never commit API keys, passwords, patient images, DICOM identifiers, source manifests, or identifiable clinical fields. Public data must follow source licences, citation and access policies. Any clinical or real multi-hospital deployment requires institutional approval, data-use agreements, security review, and independent validation.

## License

[Apache-2.0](LICENSE)
