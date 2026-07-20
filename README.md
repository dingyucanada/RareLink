# RareLink 稀联

<p align="center">
  <strong>中文</strong> · <a href="README.en.md">English</a>
</p>

<p align="center">
  <strong>把稀缺病例，变成可协作、可复核的研究证据。</strong><br/>
  DGX Spark × NVIDIA FLARE × MONAI × Step 3.7
</p>

<p align="center">
  <img src="https://img.shields.io/badge/NVIDIA-DGX%20Spark-76b900?style=flat-square" alt="NVIDIA DGX Spark" />
  <img src="https://img.shields.io/badge/NVIDIA%20FLARE-2.7.2-2563eb?style=flat-square" alt="NVIDIA FLARE" />
  <img src="https://img.shields.io/badge/MONAI-1.6.0-7c3aed?style=flat-square" alt="MONAI" />
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-0f766e?style=flat-square" alt="Apache-2.0" /></a>
</p>

> 研究用途工程原型，不提供诊断或治疗建议。比赛版医学科研验证在一台真实 DGX Spark 上完成三个**逻辑站点**；另有 Spark–Mac mTLS 演练，但不等同于真实多医院生产部署或临床验证。

---

## 项目概述

罕见病与小样本医学影像研究的难点，不只是训练一个模型，而是让多家医院在原始数据不能集中时，仍能形成可复核、可解释、能继续迭代的科研证据。RareLink 将研究协议、站点可行性、实验合同、联邦训练、隐私审阅和科研报告组织为一个受控工作流：**数据留在科室，模型本地训练，跨站点只交换获准更新与聚合指标，研究过程写入审计账本。**

| 研究痛点 | RareLink 的实现 |
| --- | --- |
| 原始 MRI、标签与患者字段不能汇集 | 站点本地 NIfTI / 标签处理；输入网关拒绝原始影像、标识符、DICOM UID、密钥与小样本字段外发 |
| 平均指标掩盖弱站点风险 | 同时呈现平均 Dice、最弱站点 Dice、站点差异与 HD95 |
| Agent 容易越权或产生不可追溯结论 | 五角色 Agent 仅接触脱敏协议与聚合统计；实验合同、输入/输出门控和人工审批共同约束 |
| 实验难以复跑和解释 | 固定种子、策略矩阵、模型/结果哈希、mTLS 收据、DP 会计和一键证据核验 |

### 已核验的工程事实

| 证据 | 当前结果 | 结论边界 |
| --- | --- | --- |
| 真实公开影像 | MSD Task01 的 24 例四模态 MRI：几何/哈希校验、单站 CUDA 训练、三逻辑站点一轮 FedAvg；3/3 更新聚合并持久化全局模型 | 工程冒烟；非儿童队列、非临床性能、非真实跨院验证 |
| 稳定性对照 | 5 种子 × 5 策略 × 3 轮，25/25 组合完成 | 合成数据与逻辑站点工程比较，不能作医学统计推断 |
| 隐私与安全 | Opacus 样本级 DP-SGD：三轮保守会计 `ε=6.076881`、`δ=1e-5`；26/26 Agent 网关用例通过 | 非端到端、用户级或医院级 DP 保证；非完整渗透测试 |
| 安全联邦演练 | Spark–Mac mTLS 注册、重连、错误身份拒绝 | 非真实医院 WAN 或生产身份体系认证 |

上述结论均来自已版本化的运行收据；主页下方同时给出关键配置、实验设计、数值结果与数据来源，避免必须跳转阅读才能判断证据边界。

---

## NVIDIA 工具平台

RareLink 不是把 DGX Spark 当作网页服务器；它承担本地 CUDA、MONAI 三维训练、NVIDIA FLARE 联邦任务、证据 API/Web 服务，以及可选的本地大模型推理边界。

| 平台 / 工具 | 在作品中的作用 | 已有证据 / 使用方式 |
| --- | --- | --- |
| [NVIDIA DGX Spark](https://www.nvidia.com/en-us/products/workstations/dgx-spark/) | 本地算力与运行边界 | GB10 / ARM64 / CUDA 13 实机运行 CUDA、MONAI 3D、FLARE、API/Web；MSD 一轮三站点聚合端到端约 69 秒 |
| [CUDA](https://developer.nvidia.com/cuda) + PyTorch | 本地张量计算、AMP 与训练运行时 | 在 Spark 上执行 MONAI 训练与联邦客户端任务 |
| [NVIDIA FLARE](https://nvidia.github.io/NVFlare/) | FedAvg/FedProx、Client API、mTLS 与联邦编排 | 真实三逻辑站点聚合；另有两物理设备 mTLS 证据 |
| [Project MONAI](https://project-monai.github.io/) | NIfTI、三维 SegResNet、影像变换与 Dice/HD95 评估 | 用于合成影像工程对照与 MSD Task01 公开数据工程验证 |
| [TensorRT-LLM](https://github.com/NVIDIA/TensorRT-LLM)（可选） | Spark 本地、OpenAI 兼容的研究 Agent 路由 | 元数据回执、独立核验、26 条网关红队与 `1/2/4` 并发工具已实现；没有真实本地模型回执时 UI 明确显示 `NOT CLAIMED` |
| Step 3.7 | 受策略约束的实验设计、统计评审、隐私评审、科研写作 | 仅接收脱敏文本和聚合指标；缺少密钥时自动回退为确定性模板 Agent |

## 作品介绍（含系统界面）

RareLink 的前端不是“模拟医院游戏”。它将可点击的研究流程沙盘与已落盘的实机收据明确分开：沙盘用来演示协议、合同、Agent 和审批流程；实机收据用于重新计算哈希、核验 3/3 站点、全局模型、指标和边界。评委可在控制台点击“核验本地证据哈希”，再展开三个站点的 Dice、HD95 与训练耗时。

<p align="center">
  <img src="assets/rarelink-overview.svg" alt="RareLink 数据留在科室、DGX Spark 本地训练、FLARE 聚合、Agent 受控审阅与证据驾驶舱的系统界面概览" width="100%" />
</p>

<p align="center"><sub>系统界面与运行边界概览：原始影像不进入 Agent；对外输出受实验合同和策略门控。</sub></p>

### 真实产品运行截图

下图来自本地启动的 RareLink 前端，不是设计稿：顶部的 `DGX SPARK · VERIFIED RUN RECEIPT` 区域读取并展示已落盘的公开 MSD 工程收据；可点击核验哈希并展开站点明细。画面中的影像预览为项目内置的合成脱敏演示切片，不含真实患者影像。

<p align="center">
  <img src="assets/screenshots/rarelink-live-evidence-console.png" alt="RareLink 实际运行的证据驾驶舱：DGX Spark 实机运行收据、三站点聚合和本地模型边界" width="100%" />
</p>

### 评审可操作路径

1. 启动“评审一键复现包”，进入证据驾驶舱；它不会下载影像、模型权重、证书或 API 密钥。
2. 点击“核验本地证据哈希”，确认三站点收据、全局模型和聚合结果未被篡改。
3. 展开站点明细，查看公开 MSD 工程运行的聚合指标与明确的非临床边界。
4. 在工作流沙盘中创建示范研究，依次体验协议、站点统计、合同锁定、训练策略和 Agent 证据解读。
5. 使用 `review_demo.sh` 导出或复核相同的证据门。

<p align="center">
  <img src="assets/rarelink-evidence-scorecard.svg" alt="RareLink 工程证据总览：25/25 重复实验、26/26 Agent 红队、样本级 DP-SGD、Spark-Mac mTLS 与五种策略比较" width="100%" />
</p>

---

## 技术创新点

1. **从“联邦训练”升级为“证据闭环”。** 研究协议、可行性、实验合同、任务状态、聚合指标、模型路径与审计事件被组织为可追溯状态机，而非只输出一次模型分数。
2. **计算边界与语言模型边界分离。** MRI 与标签留在站点；DGX Spark 运行影像训练；FLARE 只协调受批准更新；Step 3.7 或本地 TensorRT-LLM 仅消费经脱敏和小组抑制后的文本/聚合指标。
3. **隐私—效用不只停留在口号。** 以 Local、FedAvg、FedProx、严格 SVT、样本级 DP-SGD 进行对照，保留平均与最弱站点指标，避免仅展示最好看的结果。
4. **把 Agent 放进可审计的安全边界。** 双向网关阻断原始字段、标识符、路径、凭据和诊疗指令；26 条确定性攻击/安全对照用例在 Agent 前后执行。
5. **诚实的本地大模型证据机制。** 本地模型“可配置”不等于“已验证”：系统将端点可用、回执采集、独立验证分层呈现；无真实回执即为 `NOT CLAIMED`。

---

## 系统架构与安全边界

RareLink 使用成熟开源组件完成通用能力；项目自研部分聚焦科研状态机、实验合同、数据外发策略、证据关联与 Spark/FLARE 适配。控制平面负责“谁能做什么、何时可做、留下什么证据”，而不是绕过医院的数据边界。

```text
React 证据驾驶舱
        │  协议 / 审批 / 核验 / 聚合指标
        ▼
FastAPI + Pydantic + SQLModel 审计账本
        ├── 工作流状态机与实验合同（人工 PI 锁定）
        ├── 输入/输出策略网关与 Agent 产物注册表
        ├── FederationRunner
        │     ├── 本地开发：确定性 Mock Runner（始终标记 mock）
        │     └── Spark：MONAI + NVIDIA FLARE Recipe / Client API
        └── 五角色 Agent Team（仅脱敏文本与聚合指标）
              研究主管 → 实验设计 → 统计评审 → 隐私评审 → 科研写作

医院/科室本地边界：NIfTI、标签、患者字段、DICOM UID 不离开站点
跨站点边界：仅实验合同批准的模型更新与聚合指标
Agent 边界：不读取影像、标签、病例路径、凭据或小样本明细
```

每个 Agent 输出均先经过 Pydantic 结构校验，再独立持久化并由审计账本关联。实验设计 Agent 只能提出合同，必须由研究负责人批准并锁定；隐私评审 Agent 可以阻断报告生成，但不能放宽确定性的字段外发策略。输入网关会拒绝原始影像、标识符、DICOM UID、密钥、路径和小样本字段；输出网关阻断诊疗建议、未经批准的合同变更与不安全报告内容。

### Spark 上的执行设计

在原型中，`site-a`、`site-b`、`site-c` 是同一台真实 DGX Spark 内的**逻辑站点**，目的是验证联邦任务、聚合、策略与审计，不伪装成三家医院。NVIDIA FLARE 2.7.2 的 `FedAvgRecipe` / `SimEnv` / Client API 直接编排任务；MONAI SegResNet 在 CUDA 上处理四模态三维 NIfTI。为避免三个三维模型同时争抢统一内存，单 Spark 原型有意串行执行逻辑站点训练；真实部署时每家医院应运行独立 Spark Client，由协调方仅聚合批准更新。

本地大模型路径同样遵守边界：TensorRT-LLM 可在 `127.0.0.1` 的私有 OpenAI 兼容端点服务 NVIDIA 支持模型，仅接收已脱敏的聚合科研上下文。页面把“端点在线”“已采集运行回执”“独立核验通过”分开呈现；没有真实回执就显示 `NOT CLAIMED`，不以模拟数据替代实测。

---

## 实验设计、实测结果与解释

### 真实公开影像工程验证

在 NVIDIA DGX Spark GB10（ARM64、CUDA 13、PyTorch `2.10.0+cu130`、MONAI `1.6.0`、NVIDIA FLARE `2.7.2`）上，RareLink 对公开 MSD `Task01_BrainTumour` 进行了工程兼容性验证。数据归档由 Spark 节点直接下载，校验发布 MD5 与本地 SHA-256；仓库不保存影像、标签、病例 ID、病例级路径或模型权重。24 例四模态三维 MRI 经几何检查后，按肿瘤体素量分位数确定性划分为 3 个逻辑站点、每站 8 例；标签合同将 MSD 原始 `0/1/2/3` 映射为 `0/1/2`，深度从 155 通过 `DivisiblePadd(k=4)` 补齐到 156，以满足网络下采样要求。

| 运行 | 训练配置 | 可复核结果 |
| --- | --- | --- |
| 单站 CUDA 冒烟 | `site-a`：7 例训练 / 1 例验证，1 epoch | 损失 `1.818046`；前景平均 Dice `0.008702`；HD95 `117.379684`；耗时 `6.7476 s`；峰值显存 `5240.349 MiB` |
| 三逻辑站点 FedAvg | 每站 8 例、1 本地 epoch、1 联邦轮 | `3/3` 客户端更新聚合，写入全局模型；端到端 `69.0084 s`；峰值显存 `5240.349 MiB` |

| 站点 | Dice | HD95 | 训练损失 | 本地耗时 |
| --- | ---: | ---: | ---: | ---: |
| `site-a` | `0.012345` | `119.771957` | `1.657893` | `6.6302 s` |
| `site-b` | `0.040765` | `107.582993` | `1.653218` | `6.3943 s` |
| `site-c` | `0.071763` | `79.886047` | `1.649940` | `6.7046 s` |
| 聚合观察值 | **`0.041624`** | **`102.413666`** | — | **`69.0084 s`** |

最弱站点 Dice 为 `0.012345`，站点 Dice 标准差为 `0.024265`。这说明产品同时显示平均值和最弱站点是必要的工程设计。它**只能**证明真实四模态 NIfTI 读取、CUDA 训练、FLARE 三站点聚合与全局模型持久化均已跑通；不能证明临床有效性、策略优劣、真实医院 WAN 通信或儿童罕见病队列性能。

### 稳定性、隐私与安全验证

| 验证 | 方法 | 结果与边界 |
| --- | --- | --- |
| 稳定性 | 5 随机种子 × Local / FedAvg / FedProx / 严格 SVT / DP-SGD，3 轮 | `25/25` 组合完成；使用合成数据和逻辑站点，只用于工程稳定性比较 |
| 样本级 DP-SGD | Opacus 逐样本裁剪、高斯噪声、Poisson 采样与 RDP 会计 | 3 轮保守会计 `ε=6.076881`、`δ=1e-5`；仅覆盖本地训练步骤，不是端到端、用户级或医院级保证 |
| 安全联邦 | Spark–Mac 的 mTLS 注册、重连与错误身份拒绝 | 证明证书化通信演练；不是医院生产网络、身份体系或渗透测试 |
| Agent 安全 | 12 条输入 + 14 条输出的确定性门控用例 | `26/26` 通过；测试策略网关，不宣称已完成通用模型安全认证 |

---

## 权威技术与数据参考

| 主题 | 权威入口 | RareLink 中的具体使用 / 边界 |
| --- | --- | --- |
| NVIDIA DGX Spark | [产品页](https://www.nvidia.com/en-us/products/workstations/dgx-spark/) · [用户指南](https://docs.nvidia.com/dgx/dgx-spark/index.html) | GB10 / ARM64 本地三维训练、FLARE Client 与服务部署；不是以带宽为核心的集中式数据传输方案 |
| CUDA | [NVIDIA CUDA](https://developer.nvidia.com/cuda) | PyTorch CUDA 张量计算与 AMP 训练运行时 |
| NVIDIA FLARE | [官方文档](https://nvidia.github.io/NVFlare/) · [GitHub](https://github.com/NVIDIA/NVFlare) · [医疗目录](https://nvidia.github.io/NVFlare/catalog/) | FedAvg/FedProx、Client API、mTLS；联邦学习不自动等同合规或隐私保证 |
| MONAI | [Project MONAI](https://project-monai.github.io/) · [文档](https://docs.monai.io/) | NIfTI 变换、3D SegResNet、Dice / HD95 评估 |
| PyTorch | [官方文档](https://pytorch.org/docs/stable/index.html) | 模型、优化器、AMP 与 CUDA 张量 |
| Opacus | [官网](https://opacus.ai/) · [PrivacyEngine API](https://opacus.ai/api/privacy_engine.html) | DP-SGD 和隐私会计；不扩展为端到端或机构级 DP 声明 |
| 联邦学习定义与风险 | [NIST 术语表](https://csrc.nist.gov/glossary/term/federated_learning) · [NIST 隐私攻击说明](https://www.nist.gov/blogs/cybersecurity-insights/privacy-attacks-federated-learning) | 原始数据不集中不代表模型更新和指标没有泄露风险，因此仍需策略、身份、审计与 DP |
| 罕见病研究语境 | [NIH GARD FAQ](https://rarediseases.info.nih.gov/diseases/pages/31/faqs-about-rare-diseases) | “罕见病”是本项目服务的研究场景，不构成诊断或流行病学结论 |
| MSD Task01 | [数据页](https://medicaldecathlon.com/dataaws/) · [官方归档](https://msd-for-monai.s3-us-west-2.amazonaws.com/Task01_BrainTumour.tar) · [论文](https://doi.org/10.1038/s41467-022-30695-9) | 当前完成真实公开影像工程验证；不是儿童队列或临床性能验证 |
| BraTS-PEDs（后续） | [TCIA 数据集](https://www.cancerimagingarchive.net/collection/brats-peds/) · [TCIA 使用政策](https://www.cancerimagingarchive.net/tcia-data-usage-policy/) | 面向儿童公开数据的后续工程验证候选，需先满足使用政策和引用要求 |
| Step 3.7 | [Stepfun Platform](https://platform.stepfun.com/) | 只处理策略批准的脱敏协议与聚合上下文；Step 权重不部署在 Spark |

---

## 未来展望

RareLink 的目标不是替代医生，而是成为“**数据不出院、证据可回溯**”的多中心科研操作系统。下一阶段按风险与价值推进：

| 阶段 | 目标 | 前置条件 |
| --- | --- | --- |
| 外部工程验证 | 在合规授权的 BraTS-PEDs 等儿童公开数据上重复工程流程 | 数据使用政策、预处理与公开报告边界 |
| 真实多院试点 | 每院部署独立 Spark Client、证书化 FLARE 通信与本地审计 | IRB / 数据使用协议 / 安全评审 / 医院网络与身份体系 |
| 临床研究协作 | PACS/FHIR 对接、临床研究治理、站点间可行性与证据包 | 医疗机构合作、独立临床验证与法规路径 |
| 本地 Agent 升级 | 在 Spark 捕获真实 TensorRT-LLM 回执、并发数据和安全红队证据 | 获得可用本地模型与合规的推理资源 |

更多企业化路径见 [企业化一页路线图](outputs/RareLink-企业化一页路线图.md)。

---

## 快速开始

### 一键复现（推荐）

无需医学影像、模型权重、证书或 API Key；脚本仅在缺少运行产物时写入带边界标签的演示证据快照，绝不伪装成新实验：

```bash
git clone https://github.com/dingyucanada/RareLink.git
cd RareLink
bash scripts/review_demo.sh
```

随后打开终端给出的本地地址。复现包默认核对四项已记录的工程证据：`25/25` 重复实验、样本级 DP-SGD 会计、Spark–Mac mTLS 负面对照、`26/26` Agent 网关用例。它不会下载影像、模型权重、证书或 API 密钥；若本地缺少运行产物，只会写入明确标为演示快照的脱敏证据，不会伪装成新实验。

### 本地开发

```bash
cp .env.example .env
python3 -m venv .venv
. .venv/bin/activate
make install
make install-web
make dev-api
```

另开一个终端：

```bash
make dev-web
```

访问 `http://localhost:5173`；API 文档为 `http://localhost:8000/docs`。未配置 `STEP_API_KEY` 时，系统使用确定性模板 Agent，依然可以跑通受控工作流。密钥只放在 `.env`，不得提交。

### 可选：真实公开影像工程运行

请在 Spark 节点直接下载公开 MSD Task01，不要通过 SSH/SCP 上传大文件。脚本会校验公开归档 MD5、记录哈希，并按肿瘤体积分位数生成三站点非 IID 分割：

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

部署前应确认 `aarch64`、`nvidia-smi`、Python 3.11+、可用磁盘与安全统一内存余量；推荐使用 NVIDIA PyTorch 容器或仓库的 Spark 启动脚本。原始工程记录仅作为可审计索引保留：[MSD 实机运行报告](outputs/RareLink-2026-07-20-MSD真实影像Spark联邦运行报告.md)、[Spark 部署手册](docs/deployment.md)、[实机系统报告](outputs/RareLink-2026-07-17-DGX-Spark系统移植与实机实验正式报告.md)。

## 安全与责任使用

请勿提交 API 密钥、密码、患者影像、DICOM 标识符、原始清单或可识别临床字段。公开数据须遵守来源许可、引用和访问政策；任何临床或真实多医院部署均需机构审批、数据使用协议、安全审查与独立验证。

## License

[Apache-2.0](LICENSE)
