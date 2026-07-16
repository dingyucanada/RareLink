# RareLink 稀联：路演 PPT 双语内容

> 用途：3–5 分钟项目路演、NVIDIA Inception 介绍、黑客松答辩。  
> 建议：中文或英文单语演示，另一种语言作为备份页；不要在同一页堆叠大段双语文字。  
> 统一边界：这是研究用途工程原型，不提供诊断或治疗建议；当前结果来自一台 DGX Spark 上的三个逻辑站点与合成数据工程验证。

## Deck 总览

| 页码 | 中文主旨 | English message |
| ---: | --- | --- |
| 1 | 让多中心罕见病研究在数据不出院的情况下协作 | Make multi-center rare-disease research collaborative without moving patient data |
| 2 | 痛点不是缺一个模型，而是缺一条可信科研生产线 | The gap is not another model; it is a trustworthy research operating workflow |
| 3 | RareLink：从研究问题到可回溯证据 | RareLink: from research question to traceable evidence |
| 4 | 每家医院一个本地 Spark，模型流动而数据留院 | One local Spark per institution: models move, data stays |
| 5 | Agent Team 负责组织研究，不越权接触影像 | The Agent Team orchestrates research without touching raw images |
| 6 | NVIDIA 全栈让原型真正跑在本地算力上 | NVIDIA’s stack turns the architecture into a real local workload |
| 7 | 我们交付的是证据闭环，不是单次 Demo | We deliver an evidence loop, not a one-off demo |
| 8 | 隐私与安全是系统能力，不是演示口号 | Privacy and security are system capabilities, not slogans |
| 9 | 数据来源、验证状态与诚实边界 | Data provenance, validation status and honest boundaries |
| 10 | 从比赛原型到医院科研基础设施 | From hackathon prototype to hospital research infrastructure |
| 11 | 商业化路径与合作请求 | Commercial path and partnership request |
| 12 | 结尾：把稀缺病例变成可协作的证据 | Closing: turn scarce cases into collaborative evidence |

---

## 1. 开场：一个结构性矛盾 / Opening: a structural contradiction

### 中文页面

**标题**：让多中心罕见病研究，在数据不出院的情况下协作

**副标题**：RareLink 稀联｜DGX Spark × NVIDIA FLARE × MONAI × Step 3.7

**页面文案**：

罕见病病例分散在不同医院；单院样本太少，无法形成稳定研究证据；但原始 MRI 和患者字段又不能简单集中。

**推荐画面**：一张左右分裂图：左侧“病例分散”，右侧“数据不能集中”，中间是 RareLink 的连接层。

### English slide

**Title**: Make multi-center rare-disease research collaborative without moving patient data

**Subtitle**: RareLink | DGX Spark × NVIDIA FLARE × MONAI × Step 3.7

**Copy**:

Rare-disease cases are distributed across institutions. A single site has too little data for robust evidence, while raw MRI and patient-level fields cannot simply be pooled.

**Visual**: A split-screen: “scarce cases” on the left, “data cannot be pooled” on the right, with RareLink as the trust and workflow layer.

**口播 / Talk track**：

> “我们不再把问题定义为‘训练一个更大的模型’，而是定义为：如何让分散在不同医院的稀缺病例，在数据不出院的前提下形成可信证据。”

> “We do not define the problem as training one more large model. We define it as creating trustworthy evidence from scarce cases distributed across institutions, without moving patient data.”

## 2. 痛点：缺的是科研生产线 / Problem: the missing research operating workflow

### 中文页面

**标题**：联邦学习解决了数据交换，谁来解决研究治理？

**三列内容**：

- **数据问题**：病例分散、分布不一致、原始影像不能集中。
- **工程问题**：训练失败、站点掉线、内存抢占、结果难复现。
- **治理问题**：谁批准协议？哪些字段可以离站？哪个模型对应哪次实验？

**底部结论**：RareLink 把协议、训练、隐私、审计和报告放进同一条状态机。

### English slide

**Title**: Federated learning addresses data movement. Who governs the research?

- **Data**: sparse cases, heterogeneous sites, raw imaging cannot be pooled.
- **Engineering**: failed jobs, dropped sites, memory contention and irreproducible results.
- **Governance**: who approves the protocol, which fields may leave, and which model came from which run?

**Bottom line**: RareLink puts protocol, training, privacy, audit and reporting into one controlled state machine.

## 3. 产品：从问题到证据 / Product: from question to evidence

### 中文页面

**标题**：RareLink 是“协议到证据”的多中心科研操作系统

**流程图**：

```text
研究问题 → 结构化协议 → 站点可行性 → 锁定实验合同
    → 本地训练 → 联邦聚合 → 统计复核 → 可审计研究报告
```

**核心能力**：

- 研究状态机与审计账本
- 多站点本地训练与 FedAvg / FedProx
- 站点公平性指标：平均 Dice、最弱站点 Dice、站点差异、HD95
- Agent 生成协议、评审证据和科研叙事
- 失败任务可追踪、可重试、可解释

### English slide

**Title**: RareLink is a research operating system from protocol to evidence

**Flow**:

```text
Research question → structured protocol → site feasibility → locked contract
    → local training → federated aggregation → statistical review → auditable report
```

**Capabilities**:

- Research state machine and audit ledger
- Local multi-site training with FedAvg / FedProx
- Fairness-aware metrics: mean Dice, worst-site Dice, site variation and HD95
- Agents for protocol design, evidence review and scientific narrative
- Traceable, retryable and explainable failures

## 4. 架构：模型流动，数据留院 / Architecture: models move, data stays

### 中文页面

**标题**：每家医院一个本地 DGX Spark

**四层架构**：

1. 医院 / 科室：MRI、标签和患者级字段留在本地。
2. DGX Spark：CUDA、PyTorch、MONAI 和 FLARE Client 承载本地训练。
3. NVIDIA FLARE：组织 FedAvg/FedProx、身份和安全通信。
4. Agent Team：只读取经过策略过滤的协议、聚合指标和报告上下文。

**强调句**：联邦学习不是“把数据上传后再说隐私”，而是从架构上减少原始数据集中需求。

### English slide

**Title**: One local DGX Spark per institution

1. **Hospital / department**: MRI, labels and patient-level fields stay local.
2. **DGX Spark**: CUDA, PyTorch, MONAI and the FLARE Client run local training.
3. **NVIDIA FLARE**: coordinates FedAvg/FedProx, identity and secure communication.
4. **Agent Team**: reads only policy-filtered protocols, aggregate metrics and report context.

**Key message**: Federated learning is not “upload first and promise privacy later”; it reduces the need to centralize raw data by design.

## 5. Agent Team：组织研究，不接触原始影像 / Agent Team: orchestrate research, not raw images

### 中文页面

**标题**：五个角色，一个受控研究闭环

| Agent | 职责 |
| --- | --- |
| 研究主任 | 把自然语言问题转成结构化研究协议 |
| 站点数据管家 | 生成最小化、阈值保护后的可行性统计 |
| 实验设计 | 设计 Local / FedAvg / FedProx 等可比合同 |
| 隐私评审 | 阻断患者字段、小样本明细和敏感输出 |
| 证据叙事 | 解释聚合指标、局限性和下一步实验 |

**安全闸门**：输入脱敏 → 人工审批 → 输出门控 → 审计记录。

### English slide

**Title**: Five roles, one governed research loop

| Agent | Responsibility |
| --- | --- |
| Study Director | Converts a natural-language question into a structured protocol |
| Site Data Steward | Produces threshold-protected feasibility aggregates |
| Experiment Designer | Creates comparable Local / FedAvg / FedProx contracts |
| Privacy Reviewer | Blocks patient fields, small groups and unsafe outputs |
| Evidence Narrator | Explains aggregate metrics, limitations and next experiments |

**Guardrails**: input redaction → human approval → output gating → audit record.

## 6. 为什么是 NVIDIA DGX Spark / Why NVIDIA DGX Spark

### 中文页面

**标题**：Spark 的价值不是“把视频搬到本地”，而是把科研节点放到数据旁边

**三点**：

- **本地算力**：三维 MRI 训练、数据预处理和 FLARE Client 在院内节点运行。
- **统一内存与 GPU 生态**：CUDA / PyTorch / MONAI / FLARE 在同一 ARM64 环境形成可复现实链路。
- **并发与治理**：一个 Spark 可以承载多个逻辑站点和后台任务队列；统一内存保护锁避免三维任务互相抢占。

**实机事实**：已在 NVIDIA DGX Spark GB10、ARM64、CUDA 13 上完成 CUDA 矩阵计算、MONAI 3D 训练、FLARE 聚合和 API/Web 服务。

### English slide

**Title**: Spark puts the research node next to the data

- **Local compute**: 3D MRI training, preprocessing and the FLARE Client run inside the institution.
- **Unified software path**: CUDA, PyTorch, MONAI and FLARE form one reproducible ARM64 environment.
- **Concurrency and governance**: one Spark can host multiple logical sites and queued jobs; a memory-protection lock prevents competing 3D workloads.

**Verified fact**: CUDA matrix operations, MONAI 3D training, FLARE aggregation and API/Web services ran on an NVIDIA DGX Spark GB10 with ARM64 and CUDA 13.

## 7. 证据：交付的是闭环 / Evidence: we deliver the loop

### 中文页面

**标题**：不是一次“跑通”，而是可重复、可解释、可审计

**四个大数字**：

| 指标 | 结果 | 含义 |
| --- | --- | --- |
| 重复实验 | **25/25** | 5 seeds × 5 strategies × 3 rounds 全部完成 |
| Agent 安全 | **26/26** | 攻击与安全控制用例通过 |
| 安全联邦 | **mTLS** | 注册、掉线重连、错误身份拒绝 |
| 隐私训练 | **ε=6.076881** | 三轮样本级 DP-SGD 保守会计，δ=1e-5 |

**必须同时显示**：证据驾驶舱、实验报告、`bash scripts/review_demo.sh` 输出。

### English slide

**Title**: Not a one-off run — repeatable, explainable and auditable

| Evidence | Result | Meaning |
| --- | --- | --- |
| Repeated experiments | **25/25** | 5 seeds × 5 strategies × 3 rounds completed |
| Agent safety | **26/26** | Red-team and safe-control cases passed |
| Secure federation | **mTLS** | Registration, reconnect and wrong-identity rejection |
| Private training | **ε=6.076881** | Conservative three-round sample-level DP-SGD accounting, δ=1e-5 |

**Show together**: evidence cockpit, formal report and the output of `bash scripts/review_demo.sh`.

## 8. 隐私与安全：准确说清楚 / Privacy and security: say exactly what is proven

### 中文页面

**标题**：我们不把“联邦学习”四个字当作合规结论

**已完成**：

- Opacus 样本级 DP-SGD：逐样本裁剪、高斯噪声、Poisson 采样、RDP 会计。
- FLARE mTLS：证书化注册、掉线重连、错误身份拒绝。
- Agent 红队：原始数据、患者字段、凭据、诊断/治疗建议和不安全合同升级会被阻断。

**明确限制**：当前不是端到端、用户级、机构级或临床隐私保证；不是完整渗透测试；不是医院生产 WAN 认证。

### English slide

**Title**: “Federated” is not a compliance conclusion

**Completed**:

- Opacus sample-level DP-SGD: per-sample clipping, Gaussian noise, Poisson sampling and RDP accounting.
- FLARE mTLS: certificate-based registration, reconnect and wrong-identity rejection.
- Agent red team: raw data, patient fields, credentials, clinical advice and unsafe contract escalation are blocked.

**Boundaries**: this is not an end-to-end, user-level, institution-level or clinical privacy guarantee; not a complete penetration test; and not hospital-WAN production certification.

## 9. 数据来源：公开、合规、可追溯 / Data provenance: public, governed and traceable

### 中文页面

**标题**：数据状态必须和实验结论一一对应

| 数据 | 当前用途 | 当前状态 |
| --- | --- | --- |
| 本地合成四模态 MRI | 软件、训练、联邦聚合和前端展示 | 已完成工程验证，不是患者数据 |
| Project MONAI MNI152 | 公开 NIfTI 图像/标签接入与几何校验 | 已在 Spark 完成；不是肿瘤基准 |
| MSD Task01 BrainTumour | 公开研究基准下载与分区工具 | 脚本已实现；节点下载受限，未伪造完成结果 |
| TCIA BraTS-PEDs | 儿童高级别胶质瘤外部验证计划 | 需遵守 TCIA/Synapse 政策，尚未宣称完成临床实验 |

**底部小字**：所有公开数据均须按原始数据集的 DOI、许可证和 Data Usage Policy 引用。

### English slide

**Title**: Every claim must match the data actually used

| Data | Current use | Status |
| --- | --- | --- |
| Local synthetic four-modal MRI | Software, training, federation and UI evidence | Engineering validation; not patient data |
| Project MONAI MNI152 | Public NIfTI image/label intake and geometry checks | Completed on Spark; not a tumor benchmark |
| MSD Task01 BrainTumour | Public benchmark downloader and partitioning tools | Implemented; slow node download is not presented as completed evidence |
| TCIA BraTS-PEDs | Planned external validation for pediatric HGG | Requires TCIA/Synapse policy compliance; no completed clinical experiment is claimed |

**Footer**: Cite each public dataset by its DOI, license and Data Usage Policy.

## 10. 产品化：从比赛原型到医院科研基础设施 / Productization: from prototype to infrastructure

### 中文页面

**标题**：先做科研操作系统，再进入临床工作流

**路线图**：

1. **现在**：单 Spark、三逻辑站点、合成数据、完整工程证据。
2. **下一阶段**：每家医院独立 Spark Client；正式授权 BraTS-PEDs 等数据；预注册多轮实验。
3. **产品阶段**：证书轮换、PACS/FHIR 接入、机构级隐私评审、模型注册与版本治理。
4. **临床前阶段**：伦理审批、数据使用协议、独立验证、前瞻性试点和安全评估。

**产品定位**：医院科室级的多中心科研协作与证据管理平台，不替代医生。

### English slide

**Title**: Build the research operating system before entering clinical workflows

1. **Now**: one Spark, three logical sites, synthetic data and a complete engineering evidence loop.
2. **Next**: one independent Spark Client per institution; governed BraTS-PEDs-scale data; preregistered repeated experiments.
3. **Product**: certificate rotation, PACS/FHIR connectors, institution-level privacy review, model registry and version governance.
4. **Pre-clinical**: ethics approval, data-use agreements, independent validation, prospective pilots and security assessment.

**Positioning**: a department-level platform for multi-center research collaboration and evidence management — not a physician replacement.

## 11. 合作请求 / Partnership request

### 中文页面

**标题**：我们需要的不是更多 Demo，而是进入真实科研场景

**希望获得的支持**：

- NVIDIA FLARE 生产安全架构与多机构运维指导
- DGX Spark / MONAI 性能调优与推荐容器验证
- 儿童脑肿瘤或其他罕见病研究团队的设计合作
- 数据使用协议、伦理流程和医院科研试点伙伴

**我们带来的能力**：已有可运行的本地系统、证据驾驶舱、复现脚本和清晰的工程边界。

### English slide

**Title**: We need real research partners, not another demo

**We are looking for**:

- Production security and multi-institution operations guidance for NVIDIA FLARE
- DGX Spark / MONAI optimization and recommended-container validation
- Design partners in pediatric brain tumors or other rare-disease research
- Data-use, ethics and hospital research-pilot partnerships

**What we bring**: a runnable local system, evidence cockpit, reproducibility package and explicit claim boundaries.

## 12. 结尾 / Closing

### 中文页面

**标题**：把稀缺病例，变成可协作的证据

**三行结论**：

- 数据留在科室。
- Agent 组织研究，不能越权。
- Spark、FLARE 和 MONAI 把本地算力变成可信科研节点。

**落版**：

`RareLink 稀联`  
`Data-local · Evidence-traceable · Research-use prototype`

### English slide

**Title**: Turn scarce cases into collaborative evidence

- Data stays in the department.
- Agents orchestrate research without overreach.
- Spark, FLARE and MONAI turn local compute into a trustworthy research node.

**End card**:

`RareLink`  
`Data-local · Evidence-traceable · Research-use prototype`

---

## 路演制作规范 / Production notes

### 中文

- 一页只讲一个观点；每页正文不超过 40–60 个中文字符。
- 主视频 3 分钟：前端证据驾驶舱约占 80%，插入一键复现和 Spark 实机两段短证据。
- 证据数字必须同时标注“合成数据 / 逻辑站点 / 工程验证”边界。
- 不展示密码、API Key、SSH 地址、端口、患者影像、DICOM UID 或数据路径。
- 使用真实团队合影，不用 AI 生成图替代；社媒发布 AI 辅助内容时按平台规则标注。

### English

- One idea per slide; keep body copy below 40–60 Chinese characters or 25–35 English words.
- For the 3-minute demo, keep the evidence cockpit on screen for about 80% of the time and insert the reproducibility and Spark proof clips.
- Every metric must carry its boundary: synthetic data, logical sites and engineering validation.
- Never show passwords, API keys, SSH addresses, ports, patient images, DICOM UIDs or raw data paths.
- Use a real team photo; do not replace it with an AI-generated image. Label AI-assisted content on social platforms when required.

