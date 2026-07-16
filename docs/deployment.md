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
