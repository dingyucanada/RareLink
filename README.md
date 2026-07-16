# RareLink 稀联

RareLink 是面向罕见病多中心科研的智能体联邦学习终端。每个医院科室部署一台 DGX Spark，
患者级数据留在院内；NVIDIA FLARE 负责跨院协作，MONAI 负责医学影像训练，Step 3.7 只处理
经过策略检查的研究协议、聚合指标和科研报告。

> Research use only. This project does not provide diagnosis or treatment advice. The competition demo
> runs three logical sites on one remote DGX Spark and is not a real multi-hospital deployment.

## Current milestone

当前端到端里程碑包括：

- FastAPI + SQLModel study API;
- a persistent research state machine and audit ledger;
- Step 3.7 client with a deterministic template fallback;
- a five-role Step 3.7 Agent Team with structured, separately audited artifacts;
- aggregate-data egress policy with small-group suppression;
- React research console and exportable research evidence bundle;
- synthetic three-site, four-modal NIfTI cohort generation;
- MSD Task01 public brain-tumour benchmark downloader with archive/file hashes and deterministic
  three-site non-IID partitioning;
- real MONAI 3D SegResNet single-site training;
- real NVIDIA FLARE 2.7.2 three-site FedAvg and FedProx simulation.
- persisted real training jobs with live progress, logs, Dice/HD95, and global-model evidence.

真实训练链路已在本地 CPU 完成工程冒烟验证：三逻辑院区均参与聚合并生成全局模型。控制台
支持 `mock` 与 `nvflare` 两种显式模式；比赛配置已切换到真实任务模式，开源默认仍为 mock，
两者不会混淆或冒充临床结论。

2026-07-16，项目已在真实 NVIDIA DGX Spark GB10 上完成 CUDA MONAI 训练、三逻辑站点
NVFLARE FedAvg/FedProx 聚合、API 后台任务和公网前后端映射。实测环境、指标、节点问题与
限制见 [DGX Spark 实机验证报告](outputs/DGX-Spark-实机验证报告.md)。该结果仍是单机模拟
三站点的合成数据工程验证，不代表真实多院部署或临床有效性。

Step Plan 的 `step-3.7-flash` Models API 权限与真实 JSON-mode 协议生成也已完成冒烟验证；
实验设计、统计评审、隐私评审和科研写作四角色串行协作也已通过真实 API 验证。测试输入为
完全合成的研究题目和聚合指标，不包含患者数据。

See [the implementation specification](outputs/RareLink-项目开发规格书.md) for the complete roadmap.

## Local development

```bash
cp .env.example .env
python3 -m venv .venv
. .venv/bin/activate
make install
make install-web
make dev-api
```

In another terminal:

```bash
make dev-web
```

Open `http://localhost:5173`. API docs are at `http://localhost:8000/docs`.

The app uses a safe template agent when `STEP_API_KEY` is empty. Set the key only in `.env`; never
commit it.

## Tests

```bash
make test
make lint
npm run test:web
npm run build
```

## Real federated-learning smoke run

安装医学影像与联邦学习依赖：

```bash
.venv/bin/python -m pip install -e '.[dev,spark]'
```

生成非临床合成数据，并分别运行单站点 MONAI、三站点 FedAvg 与 FedProx：

```bash
.venv/bin/python scripts/prepare_demo_data.py --output data/runtime/synthetic-demo-v1
.venv/bin/python scripts/train_monai_smoke.py --manifest data/runtime/synthetic-demo-v1/manifest.json --site site-a --epochs 1
.venv/bin/python scripts/run_nvflare_simulation.py --manifest data/runtime/synthetic-demo-v1/manifest.json --strategy fedavg --rounds 1 --local-epochs 1 --workspace artifacts/nvflare-fedavg
.venv/bin/python scripts/run_nvflare_simulation.py --manifest data/runtime/synthetic-demo-v1/manifest.json --strategy fedprox --rounds 1 --local-epochs 1 --workspace artifacts/nvflare-fedprox
```

## Public benchmark evidence

To create stronger competition evidence, download the public MSD Task01_BrainTumour archive directly
on the Spark node — never through SSH/SCP. The preparation script verifies the published archive MD5,
writes archive and selected-file hashes, and simulates three non-IID sites by tumour-volume quantile.
This is a public research benchmark, not rare-disease data or a clinical validation set.

```bash
python scripts/prepare_msd_brain_tumour.py \
  --data-root data/raw/msd-task01 \
  --output data/runtime/msd-brain-tumour-v1 \
  --cases-per-site 8

# Local baselines: site-a, site-b, site-c; centralized is a research-only upper bound.
python scripts/train_monai_smoke.py --manifest data/runtime/msd-brain-tumour-v1/manifest.json --site centralized --epochs 2 --output artifacts/msd-centralized
python scripts/run_nvflare_simulation.py --manifest data/runtime/msd-brain-tumour-v1/manifest.json --strategy fedavg --rounds 3 --workspace artifacts/msd-fedavg
python scripts/run_nvflare_simulation.py --manifest data/runtime/msd-brain-tumour-v1/manifest.json --strategy fedprox --fedprox-mu 0.01 --rounds 3 --workspace artifacts/msd-fedprox
```

The MSD label value `4` is explicitly remapped to value `2` so the shared three-class segmentation
contract remains stable. Read the operational and data-handling constraints in
[the deployment guide](docs/deployment.md#7-公开脑肿瘤基准直连下载与可复现实验).

## Spark deployment

不要通过 SSH 上传大数据。应在节点上克隆仓库，先只读检查 ARM64、CUDA、Docker、统一内存和
磁盘环境，再运行 GPU 冒烟验证。完整步骤见 [DGX Spark 部署手册](docs/deployment.md)。

推荐使用可复现的 Spark 容器配置：

```bash
docker build -f deploy/Dockerfile.spark -t rarelink-spark:latest .
docker run --rm --gpus all rarelink-spark:latest python3 scripts/smoke_runtime.py
```
