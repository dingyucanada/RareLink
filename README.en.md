# RareLink

<p align="center">
  <a href="README.md">中文</a> · <strong>English</strong>
</p>

<p align="center">
  <strong>Turn scarce cases into collaborative, reviewable research evidence.</strong><br/>
  DGX Spark × NVIDIA FLARE × MONAI × Step 3.7
</p>

<p align="center">
  <img src="assets/rarelink-overview.svg" alt="RareLink architecture and evidence overview" width="100%" />
</p>

<p align="center">
  <a href="https://github.com/dingyucanada/RareLink/releases"><img src="https://img.shields.io/github/v/release/dingyucanada/RareLink?style=flat-square&label=release" alt="Release" /></a>
  <a href="https://github.com/dingyucanada/RareLink/blob/main/LICENSE"><img src="https://img.shields.io/github/license/dingyucanada/RareLink?style=flat-square" alt="License" /></a>
  <img src="https://img.shields.io/badge/NVIDIA-DGX%20Spark-76b900?style=flat-square" alt="NVIDIA DGX Spark" />
  <img src="https://img.shields.io/badge/FLARE-2.7.2-2563eb?style=flat-square" alt="NVIDIA FLARE" />
  <img src="https://img.shields.io/badge/MONAI-1.6.0-7c3aed?style=flat-square" alt="MONAI" />
</p>

RareLink is a data-local, evidence-traceable federated research platform for rare-disease and multi-center medical-imaging studies. Each participating department can keep patient-level MRI data locally while DGX Spark runs the local imaging workload, NVIDIA FLARE coordinates federated training, and a Step 3.7 Agent Team works only with policy-filtered protocols and aggregate evidence.

> Research-use engineering prototype. It is not a diagnostic or treatment system. The competition validation uses three logical sites on one physical DGX Spark; a separate Spark–Mac mTLS rehearsal does not represent production multi-hospital deployment.

## The 30-second proof: an evidence loop, not a one-off demo

<p align="center">
  <img src="assets/rarelink-evidence-scorecard.svg" alt="RareLink engineering evidence scorecard: 25 of 25 repeated runs, 26 of 26 Agent safety cases, sample-level DP-SGD, Spark–Mac mTLS and worst-site Dice across five strategies" width="100%" />
</p>

This scorecard brings the pitch-deck evidence into the repository itself. It states both what the prototype can prove and what it cannot: in the current synthetic experiment, FedAvg is the engineering demo candidate because it has the highest mean worst-site Dice (`0.072276`). FedProx, strict SVT, and DP-SGD outcomes are retained rather than hiding negative or costly results. These are **synthetic-data, three-logical-site, three-round engineering comparisons** — not clinical performance or claims of method superiority.

| Pitch-deck question | Verifiable answer in this repository |
| --- | --- |
| Can patient data leave a department? | Raw MRI, labels and patient-level fields stay local; only policy-approved model updates and aggregate statistics may leave. |
| Does Spark do real local work? | CUDA, MONAI 3D training, FLARE aggregation, and API/Web services ran on a GB10 / ARM64 / CUDA 13 node. |
| Are Agents merely a chat wrapper? | Five roles receive only redacted protocols and aggregate metrics, bounded by an experiment contract, input/output gates, and human approval. |
| Can results be audited? | 25/25 repeated combinations, 26/26 red-team cases, DP accounting, mTLS receipts, and a one-command verifier each have an evidence path. |

## What the system does

RareLink treats federated learning as a research workflow, not only as a model-training primitive. A study moves through a controlled state machine: research question → protocol → site feasibility → locked experiment contract → local training → federated aggregation → statistical review → evidence report. Decisions, retries, model paths, metrics and policy checks are recorded in an audit ledger.

| Research problem | RareLink response |
| --- | --- |
| Patient MRI cannot simply be pooled | Local NIfTI/label processing; only approved model updates and aggregate statistics leave a site. |
| Average metrics can hide site failure | Reports include mean Dice, worst-site Dice, site variation and HD95. |
| Agents can overreach | Input redaction, output gates, human approval and a locked experiment contract. |
| Experiments are difficult to reproduce | Five seeds × five strategies × three rounds, mTLS receipts, DP accounting and a review script. |

## Architecture

The local compute boundary and the language-model boundary are intentionally separate:

1. **Hospital / department site** — MRI, labels and patient-level fields remain local.
2. **DGX Spark** — CUDA, PyTorch, MONAI and the local FLARE Client run the imaging workload.
3. **NVIDIA FLARE** — coordinates FedAvg/FedProx jobs, client identity and secure communication.
4. **Spark-local TensorRT-LLM (optional)** — serves approved aggregate research context through a private OpenAI-compatible endpoint; it never receives MRI, labels, identifiers or credentials.
5. **Step 3.7 Agent Team** — receives only policy-approved text when the selected routing mode permits remote collaboration.
6. **Evidence cockpit** — exposes provenance, boundaries, metrics, failures and reproducibility receipts.

## Verified engineering evidence

| Area | Verified result | Claim boundary |
| --- | --- | --- |
| Local hardware | NVIDIA DGX Spark GB10, ARM64, CUDA 13; CUDA kernels, MONAI 3D training, FLARE aggregation and services ran on the node. | Not a clinical performance claim. |
| Stability | 25/25 combinations completed across five seeds, five strategies and three rounds. | Synthetic/logical-site engineering evidence, not medical statistics. |
| Privacy | Opacus sample-level DP-SGD; conservative three-round accounting `ε=6.076881`, `δ=1e-5`. | Not end-to-end, user-level, institution-level or clinical privacy assurance. |
| Secure federation | Spark–Mac mTLS registration, reconnect and wrong-identity rejection. | Not production hospital-WAN certification. |
| Agent safety | 26/26 deterministic red-team and safe-control cases passed. | Not a complete penetration test or medical-safety certification. |
| Public MRI intake | One public MNI152 image/structural-label pair passed local NIfTI geometry and hash checks. | Not MSD Task01, tumor performance or clinical validation. |

## Technology and data provenance

The authoritative references for NVIDIA DGX Spark, CUDA, NVIDIA FLARE, MONAI, Opacus, federated-learning terminology, rare-disease terminology, MSD and BraTS-PEDs are maintained in [Technical & Data References](docs/references.md).

Current data status is intentionally explicit:

- Synthetic four-modal MRI is generated locally for engineering tests.
- The public MNI152 pair is used only for external NIfTI intake and geometry validation.
- The repository contains a resumable MSD Task01 downloader and manifest validator, but the slow competition-node download is not presented as a completed benchmark result.
- BraTS-PEDs is a planned, policy-controlled external validation source, not a dataset already used for the current reported experiments.

## Documentation

- [Chinese project page](README.md)
- [Architecture](docs/architecture.md)
- [Deployment guide](docs/deployment.md)
- [Review and reproducibility package](DEMO.md)
- [Technical and data references](docs/references.md)
- [Technical stack](outputs/RareLink-技术栈说明.md)
- [Formal DGX Spark report](outputs/RareLink-2026-07-17-DGX-Spark系统移植与实机实验正式报告.md)
- [Enterprise roadmap](outputs/RareLink-企业化一页路线图.md)

## Quick start

The review package does not download medical images, model weights, certificates or API keys:

```bash
bash scripts/review_demo.sh
```

For the full local stack, see [DEMO.md](DEMO.md) and [the deployment guide](docs/deployment.md). If `STEP_API_KEY` is absent, RareLink uses a deterministic local template agent so the workflow remains runnable without external inference.

### Optional Spark-local LLM path

RareLink can route its structured Research Agent calls through a TensorRT-LLM endpoint on Spark using `spark_local`, `step_remote`, or `hybrid` routing. The default deployment target is NVIDIA Nemotron 120B NVFP4, downloaded directly by the Spark node. The local path includes a metadata-only receipt, an independent verifier, a 26-case local gateway red-team runner, and a fixed safe `1 / 2 / 4` concurrency profiler. The UI distinguishes a running endpoint from captured and verified evidence; until a real local run is captured it explicitly says **NOT CLAIMED**. See [the deployment guide](docs/deployment.md#43-spark-本地大模型推理tensorrt-llm).

## Safety and responsible use

RareLink does not provide diagnosis or treatment advice. Do not commit API keys, passwords, patient images, DICOM identifiers, raw manifests or identifiable clinical fields. Public data must be used under the source dataset's license, attribution and access policy. Any future clinical or multi-hospital deployment requires institutional approvals, security review, data-use agreements and independent validation.

## License

Apache-2.0. See [LICENSE](LICENSE).
