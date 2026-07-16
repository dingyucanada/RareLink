# RareLink 技术栈说明

## 技术选型原则

RareLink 将重计算、患者影像与联邦训练留在医院/科室侧的 DGX Spark；将 Step 3.7 用作仅处理策略过滤后聚合文本的 Agent 推理服务。这个边界同时服务于合规、稳定性与硬件利用：Spark 的 GPU 统一内存优先让给三维影像训练与 FLARE Client，而不在同一节点额外部署与医疗影像任务竞争显存的大语言模型权重。

## 实际使用的技术栈

| 层级 | 技术 / 版本 | 使用方式 | 部署位置与证据 |
| --- | --- | --- | --- |
| 本地算力 | NVIDIA DGX Spark GB10，ARM64，CUDA 13 | CUDA 张量计算、三维训练、联邦任务及前后端服务 | 已在赛事 Spark 节点实机验证；环境与实验记录见项目说明和部署手册。 |
| NVIDIA 联邦框架 | NVIDIA FLARE 2.7.2 | 三逻辑站点的 FedAvg、FedProx 编排；mTLS 注册、掉线重连及错误身份拒绝演练 | Spark 上的联邦编排层；两物理设备演练为工程安全验证，不等同真实医院生产部署。 |
| 医学影像训练 | MONAI 1.6.0、PyTorch 2.10.0+cu130 | NIfTI 数据变换、3D SegResNet、Dice/HD95 指标、CUDA 自动选择、AMP、AdamW | Spark GPU；公开 NIfTI/MRI 的接入与几何校验已完成，不宣称临床有效性。 |
| 隐私优化 | Opacus 1.6.0 | 样本级 DP-SGD：逐样本裁剪、高斯噪声、Poisson 采样、RDP 隐私会计 | 在本地优化器边界生效；不宣称端到端、用户级或机构级 DP。 |
| Agent 模型 | Stepfun Step 3.7 Flash，OpenAI 兼容 Chat Completions API | 研究协议、实验设计、统计解释、隐私审阅、科研写作的结构化 Agent 协作 | 远程 Step Plan API；只接收经过字段策略与最小分组阈值处理的聚合文本。 |
| Agent 可靠性 | 确定性模板 Agent、输入脱敏、输出门控、26 项红队 | 无 Key 或 API 不可用时保持演示可运行；阻断原始数据、凭据、诊疗建议与不安全合同修改 | FastAPI 控制面；红队结果 `26/26` 通过。 |
| 应用控制面 | FastAPI、SQLModel / SQLite、Pydantic | 协议状态机、实验合同、审计账本、任务与指标 API | Spark 容器服务。 |
| 证据驾驶舱 | React、TypeScript、Vite | 展示策略对照、DP 边界、mTLS、安全红队和公开 MRI 接入收据 | Spark Web 容器；公网演示页面仅展示聚合证据。 |
| 交付与复现 | Docker、Docker Compose、pytest、Ruff、GitHub Release | ARM64/NVIDIA runtime 部署；一键校验证据门 | `deploy/compose.spark.yml`、`scripts/review_demo.sh`、Release `v0.2.2`。 |

## 本地部署与模型优化说明

1. Spark 侧运行 Docker NVIDIA runtime、FastAPI、React、MONAI/PyTorch 和 NVIDIA FLARE。每个真实医院未来部署一台独立 Spark Client，协调方只接收模型更新和受控聚合指标。
2. 在单 Spark 原型中，三家科室以逻辑站点模拟，并通过统一内存保护锁串行运行三维训练，避免多任务争抢内存；真实多院时各院独立训练，由 FLARE 聚合更新。
3. 影像模型优化采用 CUDA 自动选择、AMP、AdamW、固定随机种子、数据缓存、小型 SegResNet 合同和 FedProx 异质性正则；以五种子、多策略、多轮结果报告稳定性，而不是挑选单次最好分数。
4. Step 3.7 不在 Spark 本地加载权重。优化的是 Agent 输入与工作流：最小化聚合上下文、JSON 结构化输出、字段策略、人工审批闸门、确定性回退与前后双向安全门控。这样既避免患者数据进入外部模型，也避免大模型占用本地影像训练资源。

## 未使用技术的准确声明

项目没有将未实际运行的 NVIDIA NIM、TensorRT-LLM、Nemotron 或 Step 本地权重写成已完成能力。若后续引入，应重新记录版本、硬件占用、基准和安全边界。当前可复核的 NVIDIA 关键使用为 DGX Spark / CUDA、NVIDIA FLARE、MONAI 与 PyTorch CUDA 训练链路。

