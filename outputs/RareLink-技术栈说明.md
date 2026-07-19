# RareLink 技术栈说明

## 技术选型原则

RareLink 将重计算、患者影像与联邦训练留在医院/科室侧的 DGX Spark；将 Step 3.7 用作仅处理策略过滤后聚合文本的 Agent 推理服务。与此同时，系统实现了可选的 Spark 本地 TensorRT-LLM 路径：它只接收同一字段策略批准的聚合科研上下文，使用私有 OpenAI 兼容端点，并与远程 Step 或确定性模板形成 `spark_local` / `step_remote` / `hybrid` 三种明确路由。这个边界同时服务于合规、稳定性与硬件利用；本地模型与影像训练可分阶段调度，避免把未采证的模型能力包装成既有临床或性能结论。

## 实际使用的技术栈

| 层级 | 技术 / 版本 | 使用方式 | 部署位置与证据 |
| --- | --- | --- | --- |
| 本地算力 | NVIDIA DGX Spark GB10，ARM64，CUDA 13 | CUDA 张量计算、三维训练、联邦任务及前后端服务 | 已在赛事 Spark 节点实机验证；环境与实验记录见项目说明和部署手册。 |
| NVIDIA 联邦框架 | NVIDIA FLARE 2.7.2 | 三逻辑站点的 FedAvg、FedProx 编排；mTLS 注册、掉线重连及错误身份拒绝演练 | Spark 上的联邦编排层；两物理设备演练为工程安全验证，不等同真实医院生产部署。 |
| 医学影像训练 | MONAI 1.6.0、PyTorch 2.10.0+cu130 | NIfTI 数据变换、3D SegResNet、Dice/HD95 指标、CUDA 自动选择、AMP、AdamW | Spark GPU；公开 NIfTI/MRI 的接入与几何校验已完成，不宣称临床有效性。 |
| 隐私优化 | Opacus 1.6.0 | 样本级 DP-SGD：逐样本裁剪、高斯噪声、Poisson 采样、RDP 隐私会计 | 在本地优化器边界生效；不宣称端到端、用户级或机构级 DP。 |
| Agent 模型 | Stepfun Step 3.7 Flash，OpenAI 兼容 Chat Completions API | 研究协议、实验设计、统计解释、隐私审阅、科研写作的结构化 Agent 协作 | 远程 Step Plan API；只接收经过字段策略与最小分组阈值处理的聚合文本。 |
| 可选本地 Agent 推理 | NVIDIA TensorRT-LLM，默认面向 NVIDIA Nemotron 120B NVFP4 | 私有 Spark 端点、结构化 JSON、模型/延迟/GPU/输出哈希回执；本地优先或混合路由 | 代码、部署脚本、独立核验器和并发基准已交付；**尚未将本地模型实机运行写成既有结果**。 |
| Agent 可靠性 | 确定性模板 Agent、输入脱敏、输出门控、26 项红队 | 无 Key 或 API 不可用时保持演示可运行；阻断原始数据、凭据、诊疗建议与不安全合同修改 | FastAPI 控制面；红队结果 `26/26` 通过。 |
| 应用控制面 | FastAPI、SQLModel / SQLite、Pydantic | 协议状态机、实验合同、审计账本、任务与指标 API | Spark 容器服务。 |
| 证据驾驶舱 | React、TypeScript、Vite | 展示策略对照、DP 边界、mTLS、安全红队和公开 MRI 接入收据 | Spark Web 容器；公网演示页面仅展示聚合证据。 |
| 交付与复现 | Docker、Docker Compose、pytest、Ruff、GitHub `main` 与 Release 基线 | ARM64/NVIDIA runtime 部署；一键校验证据门 | `deploy/compose.spark.yml`、`scripts/review_demo.sh`；最新内容以 GitHub `main` 为准，Release `v0.2.2` 为已发布基线。 |

## 本地部署与模型优化说明

1. Spark 侧运行 Docker NVIDIA runtime、FastAPI、React、MONAI/PyTorch 和 NVIDIA FLARE。每个真实医院未来部署一台独立 Spark Client，协调方只接收模型更新和受控聚合指标。
2. 在单 Spark 原型中，三家科室以逻辑站点模拟，并通过统一内存保护锁串行运行三维训练，避免多任务争抢内存；真实多院时各院独立训练，由 FLARE 聚合更新。
3. 影像模型优化采用 CUDA 自动选择、AMP、AdamW、固定随机种子、数据缓存、小型 SegResNet 合同和 FedProx 异质性正则；以五种子、多策略、多轮结果报告稳定性，而不是挑选单次最好分数。
4. Step 3.7 不在 Spark 本地加载权重；其远程路径仍只处理受控聚合文本。可选的本地路径使用 TensorRT-LLM，在 `127.0.0.1` 私有端点服务公开可获取的 NVIDIA 支持模型。无论本地、远程还是模板路径，均使用最小聚合上下文、JSON 结构化输出、字段策略、人工审批、确定性回退与前后双向安全门控。
5. 本地模型直接由 Spark 下载，禁止经 SSH/SCP 上传大权重。一次本地调用只写入模型名、延迟、用量、GPU 快照、策略类别和输出哈希；不写入提示词、模型回答、影像、标签、标识符或凭据。独立核验要求同时存在真实 GPU 快照、无内容回执和 `26/26` 本地网关红队结果；固定安全负载基准只记录 `1 / 2 / 4` 并发档位的吞吐与延迟。

## 本地推理的准确声明

项目已实现 TensorRT-LLM 适配器、部署脚本、元数据回执、本地网关红队、独立核验器和固定安全负载基准；但在真实 Spark 服务完成一次本地模型调用、红队和基准前，不宣称 Nemotron 120B、200B、吞吐或本地模型医学能力已经实测。页面会显示 `NOT CLAIMED` 或 `PENDING`，而非以种子快照补造本地推理证据。当前可复核的既有实机 NVIDIA 结果仍是 DGX Spark / CUDA、NVIDIA FLARE、MONAI 与 PyTorch CUDA 训练链路。
