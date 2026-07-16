# RareLink 稀联

RareLink 是面向罕见病多中心科研的智能体联邦学习终端。每个医院科室部署一台 DGX Spark，
患者级数据留在院内；NVIDIA FLARE 负责跨院协作，MONAI 负责医学影像训练，Step 3.7 只处理
经过策略检查的研究协议、聚合指标和科研报告。

> 研究用途原型，不提供诊断或治疗建议。比赛训练验证以一台 DGX Spark 上的三个逻辑站点完成；
> 另有 Spark–Mac 两物理设备 mTLS 演练，但这不等同于真实多医院生产部署。

## 评审首页

| 想了解什么 | 直接查看 |
| --- | --- |
| 今天完成了哪些 Spark 移植与实验 | [DGX Spark 系统移植与实机实验正式报告](outputs/RareLink-2026-07-17-DGX-Spark系统移植与实机实验正式报告.md) |
| 25 次五种子、多轮实验的结论 | 同上第 5 节；`5 × 5` 策略—种子组合全部完成 |
| 样本级 DP-SGD、两设备 mTLS、Agent 红队 | 同上第 6–8 节 |
| 架构、数据边界与组件职责 | [系统架构](docs/architecture.md) |
| Spark 复现与部署步骤 | [部署手册](docs/deployment.md) |
| 不下载数据也能启动的评审一键包 | [评审一键复现包](DEMO.md) |
| 三分钟现场演示流程 | [演示视频脚本](outputs/RareLink-三分钟演示视频脚本.md) |
| 从比赛到企业的下一步 | [企业化一页路线图](outputs/RareLink-企业化一页路线图.md) |
| DGX Spark 黑客松开发历程 | [黑客松十日谈](outputs/RareLink-DGX-Spark黑客松十日谈.md) |

### 实机证据摘要

| 维度 | 已验证事实 | 应避免的夸大 |
| --- | --- | --- |
| 本地算力 | DGX Spark GB10 上完成 CUDA kernel、MONAI 3D 训练、FLARE 聚合、前后端服务 | 不宣称临床模型性能 |
| 稳定性 | 5 种子 × 5 策略 × 3 轮，25/25 完成；FedAvg 的最弱站点胜率为 40% | 不用五个合成种子做医学统计推断 |
| 隐私 | Opacus 样本级 DP-SGD，三轮保守会计 `ε=6.076881`、`δ=1e-5` | 不宣称端到端、用户级或医院级 DP 保证 |
| 通信 | Spark–Mac mTLS 首次注册、重连成功，错误身份拒绝 | 不宣称真实医院 WAN/生产身份验证 |
| Agent 安全 | 输入/输出双向网关；26/26 红队与控制用例通过 | 不宣称完整渗透测试或医疗安全认证 |
| 公开影像 I/O | Spark 验证一对官方 MNI152 结构 MRI/NIfTI 标签的几何与哈希回执 | 不把该单对公开模板说成肿瘤基准或联邦效果 |

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
- resumable aligned Local/FedAvg/FedProx/SVT/DP-SGD experiment matrices with Student-t intervals
  and worst-site win rates;
- NVIDIA FLARE mTLS provisioning plus token-free three-client registration evidence;
- a real NVIDIA FLARE `SVTPrivacy` update-filter comparison with explicit accounting limits;
- Opacus sample-level DP-SGD with per-sample clipping, Poisson sampling, RDP composition across
  FLARE rounds, and explicit `(epsilon, delta)` claim boundaries;
- a deterministic 26-case Agent red team enforced before and after Step 3.7;
- two-device mTLS evidence tooling for registration, dropout/reconnect, and wrong-identity rejection;
- local-only four-modal synthetic MRI and segmentation overlays that reject patient-data manifests.

真实训练链路已在本地 CPU 完成工程冒烟验证：三逻辑院区均参与聚合并生成全局模型。控制台
支持 `mock` 与 `nvflare` 两种显式模式；比赛配置已切换到真实任务模式，开源默认仍为 mock，
两者不会混淆或冒充临床结论。

2026-07-16 至 2026-07-17，项目已在真实 NVIDIA DGX Spark GB10 上完成 CUDA MONAI 训练、
三逻辑站点 NVFLARE 聚合、API 后台任务和公网前后端映射，并完成五种子多轮矩阵、样本级
DP-SGD、Spark–Mac 两设备 mTLS 与 Agent 红队。完整的环境、过程、结果、推理和限制见
[DGX Spark 系统移植与实机实验正式报告](outputs/RareLink-2026-07-17-DGX-Spark系统移植与实机实验正式报告.md)。
所有结果仍属于单机逻辑站点与合成数据的工程验证，不代表真实多院部署或临床有效性。

Step Plan 的 `step-3.7-flash` Models API 权限与真实 JSON-mode 协议生成也已完成冒烟验证；
实验设计、统计评审、隐私评审和科研写作四角色串行协作也已通过真实 API 验证。测试输入为
完全合成的研究题目和聚合指标，不包含患者数据。

See [the implementation specification](outputs/RareLink-项目开发规格书.md) for the complete roadmap.
The latest Spark evidence is recorded in
[the four-upgrade validation report](outputs/RareLink-四项获奖升级实机报告.md).

## Reviewer quick start

The review package starts the console without downloading medical images, model weights, certificates,
or API keys. It seeds a clearly labelled, token-free evidence snapshot only when the local runtime
does not already have Spark artifacts, then verifies the four competition evidence gates.

```bash
sudo docker compose -f deploy/compose.spark.yml up --build -d
sudo docker compose -f deploy/compose.spark.yml exec api python3 scripts/verify_demo_evidence.py --artifact-root artifacts --write
```

For local development without containers, run `bash scripts/review_demo.sh`. Read [DEMO.md](DEMO.md) for
the exact proof boundary, the expected four checks, and optional commands that consume GPU time. The
snapshot is for review rendering, never overwrites fresh runtime evidence, and is not presented as a
newly executed experiment.

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
.venv/bin/python scripts/run_nvflare_simulation.py --manifest data/runtime/synthetic-demo-v1/manifest.json --strategy fedavg_dpsgd --rounds 3 --local-epochs 1 --dp-noise-multiplier 1.2 --dp-max-grad-norm 1.0 --dp-delta 0.00001 --workspace artifacts/nvflare-dpsgd
```

`fedavg_dpsgd` uses Opacus expanded-weights gradients because MONAI SegResNet contains residual
operations that are incompatible with hook-mode per-sample gradients. Empty Poisson draws perform no
optimizer update but are conservatively counted in server-side RDP composition. The resulting budget
covers sample-level local training only; it is not a user-level, institution-level, transport, or
clinical privacy guarantee.

Run the formal aligned matrix with interruption-safe resume:

```bash
python3 scripts/run_repeated_benchmark.py \
  --manifest data/runtime/synthetic-demo-v1/manifest.json \
  --seeds 2026 2027 2028 2029 2030 \
  --strategies local fedavg fedprox fedavg_svt fedavg_dpsgd \
  --rounds 3 --local-epochs 1 \
  --dp-noise-multiplier 1.2 --dp-max-grad-norm 1.0 --dp-delta 0.00001 \
  --resume --workspace artifacts/repeated-benchmark
```

The Local baseline automatically trains for `rounds × local_epochs` so every strategy receives the
same number of local epoch opportunities. If an older workspace contains under-trained Local records,
replace only those records with `--resume --rerun-strategies local`.

## Agent safety evidence

The deterministic gateway redacts patient identifiers, raw-image fields, DICOM UIDs, medical file
paths, contact data, credentials, and small groups before Step 3.7. Structured output is blocked if it
contains diagnosis/treatment directives, requests patient data, makes clinical-validation claims, or
tries to escalate the locked data-egress contract.

```bash
python3 scripts/run_agent_redteam.py
```

The checked-in suite contains 26 attack and safe-control cases. Its result is a bounded engineering
evaluation, not a complete penetration test or medical-safety certification.

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
