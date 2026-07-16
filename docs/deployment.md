# RareLink DGX Spark 部署手册

## 1. 部署边界

赛事提供的是一台可 SSH 登录的 DGX Spark 节点，而不是三家真实医院。演示环境在一台 Spark
上创建 `site-a`、`site-b`、`site-c` 三个逻辑院区，以验证联邦协议、模型聚合、隐私策略和
审计链路。真实落地时，每个逻辑站点对应一台部署在医院科室内的 Spark。

本项目不需要在 Spark 上部署 Step 3.7 权重。Step 3.7 使用兼容 OpenAI 协议的远程 API，且
只能接收脱敏协议、聚合指标和报告上下文。医学影像、标签、患者标识和站点级小样本明细不得
发送给 Step API。

## 2. 使用的成熟组件

| 能力 | 组件 | 用法 |
|---|---|---|
| 联邦编排 | NVIDIA FLARE 2.7.2 | `FedAvgRecipe`、`SimEnv`、Client API |
| 联邦优化 | NVIDIA FLARE | 官方 `PTFedProxLoss` |
| 医学影像 | MONAI | NIfTI transforms、SegResNet、DiceCE、DiceMetric |
| 张量训练 | PyTorch | CUDA/CPU 自动选择、AMP、AdamW |
| 影像文件 | nibabel | 合成 NIfTI 数据生成与读取 |
| 控制平面 | FastAPI、SQLModel、Pydantic | API、状态、配置和持久化 |
| Agent 模型 | OpenAI Python SDK | 调用 Step 3.7 兼容接口 |
| 前端 | React、TanStack Query、Recharts | 科研流程控制台和指标图表 |

## 3. 首次只读检查

不要先安装依赖或上传数据。SSH 登录后，在仓库根目录运行：

```bash
bash scripts/inspect_spark.sh | tee spark-inventory.txt
```

必须确认：

- `uname -m` 为 `aarch64`；
- `nvidia-smi` 能识别 Spark GPU 与驱动；
- Python 版本不低于 3.11；
- 根目录及工作盘有足够空间；
- 当前统一内存占用安全，避免接近 90%；
- 如使用容器，Docker 已启用 NVIDIA runtime。

检查结果保存为比赛证据，但不得提交公网 IP、用户名、密码、API Key 或其他赛事凭据。

## 4. 安装

推荐直接在 Spark 上克隆代码。不要通过 SSH/SCP 上传医学影像或大体积模型。

### 4.1 推荐：NVIDIA PyTorch 容器

仓库提供 `deploy/Dockerfile.spark`，默认以 NVIDIA NGC PyTorch 为基础镜像。先构建并确认
CUDA、MONAI 与 NVFLARE：

```bash
sudo docker build \
  -f deploy/Dockerfile.spark \
  -t rarelink-spark:latest \
  .

sudo docker run --rm --gpus all \
  rarelink-spark:latest \
  python3 scripts/smoke_runtime.py
```

如所在网络访问 PyPI 较慢，可在组织安全策略允许的前提下通过构建参数指定可信镜像：

```bash
sudo docker build \
  --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
  -f deploy/Dockerfile.spark \
  -t rarelink-spark:latest \
  .
```

如果 Docker daemon 被配置为本机代理但代理未运行，应由节点管理员修复代理或提供已经批准的
基础镜像。不要擅自修改共享节点的 daemon 配置。

### 4.2 备选：原生 Python 虚拟环境

```bash
bash scripts/bootstrap_spark.sh
cp .env.example .env
```

只在 `.env` 中配置密钥。赛事领取的是 Step Plan 时使用 `step_plan/v1`；普通开放平台账号使用
`v1`。模型名必须以当前账号的 models API 返回值为准：

```dotenv
STEP_API_KEY=replace-with-secret
STEP_API_BASE=https://api.stepfun.com/step_plan/v1
STEP_MODEL=step-3.7-flash
RARELINK_FL_MODE=nvflare
```

`.env` 已被 Git 忽略。演示不需要 Step Key：未配置时系统使用确定性的本地模板 Agent，联邦
训练仍可独立运行。配置完成后执行以下命令验证 endpoint 和模型权限；脚本只打印模型 ID，
不会输出 API Key：

```bash
.venv/bin/python scripts/verify_step_api.py
.venv/bin/python scripts/smoke_step_protocol.py
```

若赛事 Key 的模型列表未返回 `step-3.7-flash`，应选择列表中的准确 ID，不要修改代码硬猜。

## 5. 生成非临床演示数据

```bash
.venv/bin/python scripts/prepare_demo_data.py \
  --output data/runtime/synthetic-demo-v1 \
  --cases-per-site 4 \
  --shape 32 32 32
```

产物包含三个逻辑站点、四模态 NIfTI、分割标签和 SHA-256 清单。所有内容均为合成数据。

## 6. Spark GPU 冒烟验证

先运行单站点 MONAI，验证 CUDA、数据管道和模型：

```bash
.venv/bin/python scripts/train_monai_smoke.py \
  --manifest data/runtime/synthetic-demo-v1/manifest.json \
  --site site-a \
  --epochs 1 \
  --output artifacts/monai-spark-smoke
```

再运行三站点真实聚合：

```bash
.venv/bin/python scripts/run_nvflare_simulation.py \
  --manifest data/runtime/synthetic-demo-v1/manifest.json \
  --strategy fedavg \
  --rounds 2 \
  --local-epochs 1 \
  --workspace artifacts/nvflare-spark-fedavg
```

```bash
.venv/bin/python scripts/run_nvflare_simulation.py \
  --manifest data/runtime/synthetic-demo-v1/manifest.json \
  --strategy fedprox \
  --fedprox-mu 0.01 \
  --rounds 2 \
  --local-epochs 1 \
  --workspace artifacts/nvflare-spark-fedprox
```

`num_threads=1` 是有意设计：同一台 Spark 上的三个模拟院区顺序执行，防止三个 3D 模型同时
争抢统一内存。真实三院部署时，每院独立训练，服务器只聚合模型更新，因此 Spark 的优势是
大统一内存、本地隐私计算和多 Agent/训练任务协同，而不是网络带宽。

成功标准不是终端中出现 “finished”，而是工作目录中存在聚合后的全局 `.pt` 模型。运行脚本
已内置这一后置条件，缺失模型会直接报错并附带服务端日志尾部。

## 7. 公开脑肿瘤基准：直连下载与可复现实验

合成数据只证明系统链路可运行，不足以证明方案能处理真实的公开影像格式。比赛演示应增加
Medical Segmentation Decathlon（MSD）Task01_BrainTumour 的工程基准。它是公开研究数据，
仍然属于患者影像数据：仅作研究工程验证，不上传到仓库、不传给 Step API、不作诊断结论。

**严禁通过 SSH/SCP 上传这个数据集或任何大模型。** 在 Spark 节点的仓库目录直接执行：

```bash
sudo docker exec -it rarelink-api python3 scripts/prepare_msd_brain_tumour.py \
  --data-root data/raw/msd-task01 \
  --output data/runtime/msd-brain-tumour-v1 \
  --cases-per-site 8
```

脚本会在节点直接下载公开归档，校验发布的 MD5，再记录归档 SHA-256 和每个入选文件的 SHA-256。
它按肿瘤体素量的低、中、高三分位创建 `site-a`、`site-b`、`site-c`，每站抽取固定数量病例；
这是可重复的非 IID **模拟**，不代表真实医院人群分布。MSD 原始标签的 `4` 会映射为 `2`，形成
背景、病灶区域、肿瘤核心三个工程类别；映射会写入 manifest。

先做本地/集中式上界，再做两种联邦策略。下列每一条都会输出 Dice、HD95、运行时长、峰值显存；
联邦汇总额外输出平均 Dice、最弱站点 Dice 和站点方差。

```bash
# 单站点基线（分别执行 site-a、site-b、site-c）
sudo docker exec -it rarelink-api python3 scripts/train_monai_smoke.py \
  --manifest data/runtime/msd-brain-tumour-v1/manifest.json --site site-a --epochs 2 \
  --output artifacts/msd-local-site-a

# 仅用于科研对照的集中式上界；不是实际跨院部署路径
sudo docker exec -it rarelink-api python3 scripts/train_monai_smoke.py \
  --manifest data/runtime/msd-brain-tumour-v1/manifest.json --site centralized --epochs 2 \
  --output artifacts/msd-centralized

sudo docker exec -it rarelink-api python3 scripts/run_nvflare_simulation.py \
  --manifest data/runtime/msd-brain-tumour-v1/manifest.json --strategy fedavg --rounds 3 \
  --local-epochs 1 --workspace artifacts/msd-fedavg

sudo docker exec -it rarelink-api python3 scripts/run_nvflare_simulation.py \
  --manifest data/runtime/msd-brain-tumour-v1/manifest.json --strategy fedprox --rounds 3 \
  --local-epochs 1 --fedprox-mu 0.01 --workspace artifacts/msd-fedprox
```

录屏时展示 manifest 中的来源、许可证、分区规则和哈希即可；不要展示切片、患者影像内容、原始
数据目录或任何可识别信息。MSD 的授权与引用要求应在最终提交材料中保留。

## 8. 启动控制台

### 8.0 评审一键启动（推荐录屏/现场展示）

仓库提供 `deploy/compose.spark.yml`。它同时启动 API 与前端，并且只在缺少运行证据时加载一份
明确标记为 `evidence_snapshot=true` 的脱敏证据快照；快照不含患者数据、模型、证书、token 或 API Key，
不会覆盖 Spark 上已有的实测产物。

```bash
sudo docker compose -f deploy/compose.spark.yml up --build -d
sudo docker compose -f deploy/compose.spark.yml exec api python3 scripts/verify_demo_evidence.py --artifact-root artifacts --write
```

该命令会核验 25 项稳定性试验、样本级 DP-SGD、两物理设备 mTLS 负面对照和 26 条 Agent 红队
用例。若已在本地虚拟环境开发，也可运行 `bash scripts/review_demo.sh`。完整评审说明见
[`DEMO.md`](../DEMO.md)。停止时执行：

```bash
sudo docker compose -f deploy/compose.spark.yml down
```

该包用于审阅已有工程证据，不会自动下载公开影像数据或重新启动耗时训练。

容器模式下启动后端：

```bash
sudo docker run -d \
  --name rarelink-api \
  --network host \
  --gpus all \
  -e RARELINK_FL_MODE=nvflare \
  -v "$PWD:/workspace" \
  -w /workspace \
  rarelink-spark:latest
```

前端可使用宿主机 Node.js，也可使用 Node 容器。容器方式：

```bash
sudo docker run --rm \
  --user "$(id -u):$(id -g)" \
  -e HOME=/tmp \
  -v "$PWD/apps/web:/app" \
  -w /app \
  node:20-alpine \
  npm install

sudo docker run -d \
  --name rarelink-web \
  --network host \
  --user "$(id -u):$(id -g)" \
  -e HOME=/tmp \
  -e RARELINK_API_PROXY=http://localhost:9000 \
  -v "$PWD/apps/web:/app" \
  -w /app \
  node:20-alpine \
  npm run dev -- --host 0.0.0.0 --port 8888
```

原生虚拟环境方式如下。

终端一：

```bash
.venv/bin/python -m uvicorn rarelink.api.main:app --host 0.0.0.0 --port 9000
```

终端二：

```bash
RARELINK_API_PROXY=http://localhost:9000 \
  npm --prefix apps/web run dev -- --host 0.0.0.0 --port 8888
```

使用赛事分配的公网映射访问对应端口。不要额外开放数据库端口；SQLite 文件、原始数据目录和
训练产物只保留在节点内。演示结束后移除 `.env` 中的密钥。

如果前端运行在独立容器内，可使用 host network，或将 `RARELINK_API_PROXY` 指向容器可访问
的后端地址。代理目标只用于 Vite 开发服务器，不会写入浏览器端 JavaScript。

### 8.1 演示访问门与失败恢复

公网端口用于比赛演示时，建议配置一次性演示访问码，避免陌生访问者直接调用研究 API。它是
轻量访问门，不是生产级身份认证；真实医院应接入院内 SSO、VPN、审计和最小权限控制。

```bash
# 仅放入节点 .env，不提交仓库，不使用 Step API Key 作为访问码
RARELINK_DEMO_ACCESS_TOKEN=replace-with-a-random-demo-code
```

前端启动时以同一个临时值设置 `VITE_RARELINK_DEMO_TOKEN`。该值会随比赛前端构建被使用，因此
只应作为演示防护，不得视为高强度密钥；演示结束后立即撤销。`/api/health`、`/docs` 和
`/openapi.json` 保持可访问，其他 API 需要请求头 `X-RareLink-Demo-Token`。

故障演示时，可临时设置下列开关并重启 API。系统会在**模型和数据处理之前**写入一个安全的
模拟失败、将研究置为 `FAILED_RETRYABLE`，并保留任务、错误和审计事件。控制台的“重试失败的
真实训练任务”会创建一个新的可追溯任务；演示完成后必须删除该开关再重试。

```bash
RARELINK_SIMULATE_TRAINING_FAILURE=true
```

### 8.2 样本级 DP-SGD 与断点续跑

Spark 镜像固定安装 Opacus 1.6.0。三轮 DP-SGD 工程验证：

```bash
sudo docker exec -it rarelink-api python3 scripts/run_nvflare_simulation.py \
  --manifest data/runtime/synthetic-demo-v1/manifest.json \
  --strategy fedavg_dpsgd --rounds 3 --local-epochs 1 \
  --dp-noise-multiplier 1.2 --dp-max-grad-norm 1.0 --dp-delta 0.00001 \
  --workspace artifacts/nvflare-dpsgd
```

正式矩阵意外中断后，使用同一参数和 `--resume`。脚本只复用已经写入
`trial-records.json` 的完整种子—策略组合；没有记录的失败项会重跑：

```bash
sudo docker exec -it rarelink-api python3 scripts/run_repeated_benchmark.py \
  --manifest data/runtime/synthetic-demo-v1/manifest.json \
  --seeds 2026 2027 2028 2029 2030 \
  --strategies local fedavg fedprox fedavg_svt fedavg_dpsgd \
  --rounds 3 --local-epochs 1 --resume \
  --workspace artifacts/repeated-benchmark
```

Local 基线会自动使用 `rounds × local_epochs`，与联邦客户端获得相同的本地 epoch 机会。若旧工作区
已经保存了预算未对齐的 Local 记录，追加 `--rerun-strategies local`，只替换 Local，不重跑联邦策略。

## 9. 演示证据

录屏时应同时展示：

1. 三个逻辑院区的数据均为本地路径，未上传原始影像；
2. Agent 自动生成协议、可行性分析、训练契约和报告；
3. egress policy 拦截患者标识和小样本明细；
4. NVFLARE 服务端日志显示三个站点均返回更新并完成聚合；
5. FedAvg 与 FedProx 生成各自全局模型；
6. 导出的研究包包含协议、契约、实验、审计日志和复现配置。

合成数据上的低 Dice 只代表极短工程冒烟，不得包装成医学效果。正式展示应强调“链路真实、
数据不出院、证据可审计”，而不是宣称临床准确率。

### 9.1 公开 MSD Task01 的脱敏 intake 验证回执

MSD 数据完成**节点直连下载、MD5/SHA-256 校验与 manifest 分区**后，运行下列命令只输出聚合的
格式/几何验证回执：病例数、站点数、四模态结构、几何一致性与来源哈希是否存在。回执刻意不含
病例 ID、路径、影像、标签、像素或文件哈希明细。

```bash
sudo docker compose -f deploy/compose.spark.yml exec api python3 scripts/validate_public_msd_benchmark.py \
  --manifest data/runtime/msd-brain-tumour-v1/manifest.json \
  --evidence-path artifacts/public-benchmark/msd-task01-validation.json
```

控制台会在“Public NIfTI Intake”卡片显示该回执。该动作只证明公开 NIfTI 的本地 intake 与几何检查，
不等于公开数据上的联邦训练结果、儿童罕见病验证或临床效果。
