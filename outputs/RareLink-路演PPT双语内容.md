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

### 本地 Agent 推理补充页（可替换技术附录 A6） / Local-Agent evidence appendix

**中文标题**：本地 LLM 不是口号，而是一条待实机采证的证据链

- 路由：`spark_local` 本地优先，`hybrid` 可回退至 Step 3.7 或确定性模板；所有路径共享输入脱敏、输出门控和人工审批。
- 部署：TensorRT-LLM 仅绑定 Spark 的私有 `127.0.0.1` 端点；模型由 Spark 直连下载，不经 SSH 上传大权重。
- 回执：不保存提示词、回答、影像、标签或患者字段；只写模型名、延迟、GPU 快照、用量、策略类别和输出哈希。
- 核验：真实本地服务完成固定探针与 `26/26` 网关红队后，独立核验器才显示 `VERIFIED`；没有回执时必须展示 `NOT CLAIMED`。
- 并发：提供 `1 / 2 / 4` 固定安全请求的吞吐/延迟采集工具；它不是 200B、生产压测或医学性能声明。

**English title**: Local LLM evidence is a chain to verify — not a slogan

- Routing: `spark_local` first, with `hybrid` fallback to Step 3.7 or deterministic templates; every route shares input redaction, output gating and human approval.
- Deployment: TensorRT-LLM is loopback/private on Spark; model weights are downloaded by Spark, never uploaded over SSH.
- Receipt: no prompts, responses, images, labels or patient fields are persisted; only model, latency, GPU snapshot, usage, policy category and output hash are recorded.
- Verification: `VERIFIED` requires a real local probe, GPU snapshot and the `26/26` gateway red team; otherwise the UI must remain `NOT CLAIMED`.
- Concurrency: the `1 / 2 / 4` fixed safe workload captures latency and throughput only; it is not a 200B, production-load or medical-performance claim.

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

**实验设计小卡片（可放在页面右侧）**：

```text
5 seeds: 2026 / 2027 / 2028 / 2029 / 2030
5 strategies: Local / FedAvg / FedProx / FedAvg+SVT / FedAvg+DP-SGD
3 rounds × 1 local epoch per site
Local baseline: 3 local epochs（对齐计算机会）
Metrics: mean Dice / worst-site Dice / HD95 / win rate / runtime / peak GPU memory
```

**结果解读**：FedAvg 是当前工程候选，原因是最弱站点 Dice 均值 `0.072276`、最弱站点胜率 `40%`；FedProx 在 `4/5` 个种子上改善最弱站点，但不能据此宣称医学优越性；严格 SVT 配置五次均为零效用，保留为重要负结果；DP-SGD 显示隐私开销与效用之间的真实张力。

### English slide

**Title**: Not a one-off run — repeatable, explainable and auditable

| Evidence | Result | Meaning |
| --- | --- | --- |
| Repeated experiments | **25/25** | 5 seeds × 5 strategies × 3 rounds completed |
| Agent safety | **26/26** | Red-team and safe-control cases passed |
| Secure federation | **mTLS** | Registration, reconnect and wrong-identity rejection |
| Private training | **ε=6.076881** | Conservative three-round sample-level DP-SGD accounting, δ=1e-5 |

**Show together**: evidence cockpit, formal report and the output of `bash scripts/review_demo.sh`.

**Experiment card**:

```text
Seeds: 2026 / 2027 / 2028 / 2029 / 2030
Strategies: Local / FedAvg / FedProx / FedAvg+SVT / FedAvg+DP-SGD
3 rounds × 1 local epoch per site
Local baseline: 3 local epochs for a matched local budget
Metrics: mean Dice / worst-site Dice / HD95 / win rate / runtime / peak GPU memory
```

**Interpretation**: FedAvg is the current engineering candidate because its mean worst-site Dice is `0.072276` with a `40%` worst-site win rate. FedProx improved the worst site on `4/5` seeds but cannot be called medically superior. Strict SVT produced zero utility in all five runs and is retained as a meaningful negative result. DP-SGD exposes a real privacy–utility trade-off.

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
| MSD Task01 BrainTumour | 真实公开影像工程基准 | 24 例已在 Spark 完成几何校验、单站 CUDA 与一轮三逻辑站点 FedAvg；不是临床性能 |
| TCIA BraTS-PEDs | 儿童高级别胶质瘤外部验证计划 | 需遵守 TCIA/Synapse 政策，尚未宣称完成临床实验 |

**底部小字**：所有公开数据均须按原始数据集的 DOI、许可证和 Data Usage Policy 引用。

### English slide

**Title**: Every claim must match the data actually used

| Data | Current use | Status |
| --- | --- | --- |
| Local synthetic four-modal MRI | Software, training, federation and UI evidence | Engineering validation; not patient data |
| Project MONAI MNI152 | Public NIfTI image/label intake and geometry checks | Completed on Spark; not a tumor benchmark |
| MSD Task01 BrainTumour | Public real-image engineering benchmark | 24 cases completed geometry checks, single-site CUDA and one-round three-logical-site FedAvg on Spark; not clinical performance |
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

---

# 技术附录：实验、开发与复现 / Technical appendix: experiments, development and reproduction

> 这部分可以作为答辩附录，也可以拆成主 PPT 的“点击展开”页面。它回答评委或投资人最常追问的四个问题：怎么设计、怎么跑、结果是什么、下一步怎么变成产品。

## A1. 可复现实验合同 / Reproducible experiment contract

### 中文

**页面标题**：先锁定合同，再比较策略

**固定配置**：

| 参数 | 固定值 |
| --- | --- |
| 逻辑站点 | 3：site-a / site-b / site-c |
| 随机种子 | 2026、2027、2028、2029、2030 |
| 策略 | Local、FedAvg、FedProx、FedAvg+SVT、FedAvg+DP-SGD |
| 联邦轮数 | 3 |
| 每轮本地训练 | 每站点 1 epoch |
| Local 对照 | 3 epochs，匹配联邦总本地训练机会 |
| 统一模型 | 小型 MONAI 3D SegResNet |
| 指标 | Mean Dice、worst-site Dice、HD95、最弱站点胜率、运行时间、峰值 GPU 内存 |

**执行步骤**：

1. 从同一个合成四模态 MRI manifest 生成三个站点。
2. 对每个 seed 建立独立 workspace，避免产物互相覆盖。
3. 运行五种策略，单个组合完成后才写入结果文件。
4. 中断时使用 `--resume`，只复用完整写入的组合。
5. 汇总均值、标准差、t 区间和最弱站点胜率。
6. 将 aggregate-only 结果写入 API、报告和证据驾驶舱。

**结果**：25 个策略—种子组合全部完成（25/25）；不是挑一条最好的训练曲线，而是用同一合同比较稳定性、站点公平性和成本。

### English

**Slide title**: Lock the contract before comparing strategies

**Fixed configuration**:

| Parameter | Value |
| --- | --- |
| Logical sites | 3: site-a / site-b / site-c |
| Seeds | 2026, 2027, 2028, 2029, 2030 |
| Strategies | Local, FedAvg, FedProx, FedAvg+SVT, FedAvg+DP-SGD |
| Federated rounds | 3 |
| Local training | 1 epoch per site per round |
| Local baseline | 3 epochs, matching the federated local budget |
| Model | Small MONAI 3D SegResNet |
| Metrics | Mean Dice, worst-site Dice, HD95, worst-site win rate, runtime, peak GPU memory |

**Run protocol**:

1. Generate three sites from the same synthetic four-modal MRI manifest.
2. Create an isolated workspace for each seed.
3. Persist a strategy result only after the full combination completes.
4. Resume interrupted runs without reusing partial artifacts.
5. Aggregate mean, standard deviation, t intervals and worst-site win rate.
6. Publish aggregate-only evidence to the API, report and cockpit.

**Result**: all 25 strategy–seed combinations completed. The comparison measures stability, site fairness and cost instead of selecting a favorable training curve.

## A2. 五种策略的真实结果 / Results across five strategies

### 中文

**页面标题**：负结果也进入证据链

| 策略 | Mean Dice | Worst-site Dice | HD95 | Worst-site win | 时间 | 峰值 GPU 内存 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Local | 0.049025 ± 0.013654 | 0.023893 ± 0.011558 | 14.514729 | 20% | 1.52 s | 24.38 MB |
| FedAvg | **0.080087 ± 0.080502** | **0.072276 ± 0.075325** | 14.390605 | **40%** | 73.05 s | 20.73 MB |
| FedProx | 0.073442 ± 0.035380 | 0.051055 ± 0.030026 | **13.879725** | 20% | 72.68 s | 21.59 MB |
| FedAvg + SVT | 0.000000 ± 0.000000 | 0.000000 | 0.000000 | 0% | 73.21 s | 20.73 MB |
| FedAvg + DP-SGD | 0.041315 ± 0.052110 | 0.037724 ± 0.048620 | 18.970487 | 20% | 73.59 s | **55.78 MB** |

**讲解顺序**：

- FedAvg：当前演示候选，依据是最弱站点指标而不是单纯平均值。
- FedProx：最弱站点改善次数更多，但本轮样本与轮数不足以给出优越性结论。
- SVT：严格的 1% 更新过滤配置导致五次零效用；保留它，说明隐私强度会影响可用性。
- DP-SGD：内存从约 20–24 MB 增至 55.78 MB，Mean Dice 低于 FedAvg，展示真实隐私—效用—成本权衡。

**一句边界**：这些是合成数据上的工程行为，不是临床性能统计。

### English

**Slide title**: Negative results stay in the evidence chain

| Strategy | Mean Dice | Worst-site Dice | HD95 | Worst-site win | Time | Peak GPU memory |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Local | 0.049025 ± 0.013654 | 0.023893 ± 0.011558 | 14.514729 | 20% | 1.52 s | 24.38 MB |
| FedAvg | **0.080087 ± 0.080502** | **0.072276 ± 0.075325** | 14.390605 | **40%** | 73.05 s | 20.73 MB |
| FedProx | 0.073442 ± 0.035380 | 0.051055 ± 0.030026 | **13.879725** | 20% | 72.68 s | 21.59 MB |
| FedAvg + SVT | 0.000000 ± 0.000000 | 0.000000 | 0.000000 | 0% | 73.21 s | 20.73 MB |
| FedAvg + DP-SGD | 0.041315 ± 0.052110 | 0.037724 ± 0.048620 | 18.970487 | 20% | 73.59 s | **55.78 MB** |

**How to explain it**:

- FedAvg is the current demo candidate because of the worst-site evidence, not just the mean.
- FedProx improved the worst site more often, but this small synthetic setting cannot establish superiority.
- SVT’s strict 1% update filter produced zero utility in all five runs; the negative result is retained.
- DP-SGD increased peak memory from roughly 20–24 MB to 55.78 MB and reduced mean Dice, showing a real privacy–utility–cost trade-off.

**Boundary**: these are engineering behaviors on synthetic data, not clinical performance statistics.

## A3. 样本级 DP-SGD 实现 / Sample-level DP-SGD implementation

### 中文

**页面标题**：隐私预算从代码路径中产生

**实现步骤**：

1. 在站点本地加载 SegResNet 与 DataLoader。
2. 通过 Opacus expanded-weights 路径计算逐样本梯度。
3. 对每个样本的梯度执行 `max_grad_norm=1.0` 裁剪。
4. 注入 `noise_multiplier=1.2` 的高斯噪声。
5. 使用 Poisson sampling，采样率为 `1/3`。
6. 每站点每轮 1 个 epoch，3 轮保守计入 9 个计划优化步。
7. 使用 RDP 组合，在 `delta=1e-5` 下得到 `epsilon=6.076881`。
8. 只把预算摘要和策略标签写入证据；不上传梯度或患者样本。

**代码入口**：`rarelink/privacy/dpsgd.py`
**准确结论**：这是样本级本地训练步骤的会计，不覆盖传输、聚合、用户级/机构级邻接关系或临床合规。

### English

**Slide title**: The privacy budget comes from an executable path

**Implementation**:

1. Load SegResNet and the local DataLoader at each site.
2. Compute per-sample gradients using the Opacus expanded-weights path.
3. Clip each sample gradient at `max_grad_norm=1.0`.
4. Add Gaussian noise with `noise_multiplier=1.2`.
5. Use Poisson sampling with rate `1/3`.
6. Run one local epoch for three federated rounds; conservatively count nine planned optimizer steps.
7. Compose RDP and obtain `epsilon=6.076881` at `delta=1e-5`.
8. Publish only the budget summary and strategy label, never gradients or patient samples.

**Code**: `rarelink/privacy/dpsgd.py`
**Exact claim**: accounting for sample-level local training steps only, not transport, aggregation, user/institution adjacency or clinical compliance.

## A4. 两物理设备 mTLS 演练 / Two-device mTLS rehearsal

### 中文

**页面标题**：身份链路经过负面测试

**演练步骤**：

1. 在 Spark 使用 FLARE Provision 生成 Root CA、Server 和 Site A/B/C 证书。
2. 第一阶段：Spark 上 Server + 三 Client 完成证书注册。
3. 第二阶段：Server 留在 Spark，Site C 运行在 Mac，通过加密隧道连接。
4. 主动结束 Site C，模拟掉线。
5. Site C 重新注册，验证重连恢复。
6. 将 Site B 证书替换到声明为 Site C 的启动包中。
7. FLARE 启动签名校验拒绝错误身份，产生负面证据。

**结果**：注册成功、掉线重连成功、错误身份拒绝成功。
**未覆盖**：医院 WAN 压力、证书轮换、撤销列表、生产 SSO、多 Spark 横向压力。

### English

**Slide title**: The identity chain is tested with a negative control

**Procedure**:

1. Provision Root CA and independent Server/Site A/B/C certificates on Spark.
2. Register Server and three clients on Spark.
3. Keep the Server on Spark and run Site C on a Mac through an encrypted tunnel.
4. Stop Site C to simulate a dropout.
5. Re-register Site C and verify recovery.
6. Replace the declared Site C certificate with Site B’s certificate.
7. Verify that FLARE rejects the wrong identity during startup/signature validation.

**Result**: registration, reconnect and wrong-identity rejection passed.
**Not covered**: hospital-WAN stress, certificate rotation/revocation, production SSO or multi-Spark horizontal load.

## A5. Agent 安全红队 / Agent safety red team

### 中文

**页面标题**：Agent 的能力边界可以被测试

**26 个用例覆盖**：

- 患者姓名、身份证、联系方式、DICOM UID、原始影像路径
- 小样本明细、站点可识别统计、凭据与 API Key
- “请给出诊断/治疗建议”等临床越权请求
- 要求绕过人工审批、修改锁定合同、伪造临床效果
- 正常的安全控制和合规研究请求，避免只测攻击不测可用性

**执行路径**：请求分类 → 敏感字段脱敏 → Step 3.7 调用（如启用）→ 结构化输出校验 → 高风险响应阻断 → 审计记录。

**结果**：Spark 实跑 `26/26` 通过；这是确定性工程评估，不是完整渗透测试或医疗安全认证。

### English

**Slide title**: Agent boundaries are testable

**The 26 cases cover**:

- Names, IDs, contact details, DICOM UIDs and raw-image paths
- Small-group details, site-identifying aggregates, credentials and API keys
- Clinical overreach such as diagnosis or treatment requests
- Attempts to bypass approval, alter locked contracts or fabricate clinical claims
- Safe controls and compliant research requests, so usability is tested alongside attacks

**Execution path**: classify → redact → call Step 3.7 when enabled → validate structured output → block high-risk response → audit.

**Result**: `26/26` passed on Spark. This is a deterministic engineering evaluation, not a complete penetration test or medical-safety certification.

## A6. 公开 MRI 接入与数据边界 / Public MRI intake and data boundaries

### 中文

**页面标题**：先证明数据链路，再谈基准结果

**MNI152 已完成的步骤**：

1. 从 Project MONAI 官方测试资产获取公开 image/structural-label pair。
2. 在 Spark 本地读取 NIfTI，不经过 SSH 上传大文件。
3. 校验 image/label shape 一致。
4. 记录空间尺寸 `91×109×91` 与 `2 mm` spacing。
5. 写入图像与标签 SHA-256，但 evidence 只保留聚合收据，不保留原始像素。

**MSD 新增结果**：24 例四模态 MRI 完成 Spark 几何校验、单站 CUDA 和一轮三逻辑站点 FedAvg；3/3 更新聚合并生成全局模型。该单轮结果只证明工程链路，不等于儿童队列、临床性能或真实跨院验证。

**MNI152 / BraTS-PEDs**：MNI152 保留为早期 NIfTI 接入收据；BraTS-PEDs 仍是后续合规儿童外部研究来源，必须完成访问政策、引用和授权检查。

### English

**Slide title**: Prove the data path before claiming benchmark performance

**Completed for MNI152**:

1. Obtain a public image/structural-label pair from the Project MONAI test asset.
2. Read NIfTI locally on Spark; do not upload large files over SSH.
3. Verify image/label shape alignment.
4. Record `91×109×91` geometry and `2 mm` spacing.
5. Record SHA-256 values while publishing aggregate-only evidence without raw pixels.

**New MSD result**: 24 four-modal cases completed Spark geometry checks, single-site CUDA and one-round three-logical-site FedAvg; 3/3 updates were aggregated and a global model was persisted. This proves an engineering path, not pediatric-cohort, clinical-performance or real cross-hospital validity.

**MNI152 / BraTS-PEDs**: MNI152 remains the earlier NIfTI intake receipt; BraTS-PEDs remains a governed future pediatric external-validation source subject to access and citation policy.

## A7. 开发过程：从 API 到实机 / Development path: from API to hardware

### 中文

**页面标题**：今天完成的不只是一个界面

**开发阶段**：

| 阶段 | 交付内容 | 验证方式 |
| --- | --- | --- |
| 领域建模 | Study、Protocol、Contract、Run、Evidence 状态机 | API 工作流测试、审计账本 |
| Agent 层 | 五角色协作、模板回退、输入/输出网关 | Step 3.7 JSON 冒烟、26 项红队 |
| 影像层 | NIfTI、四模态合成数据、SegResNet、Dice/HD95 | MONAI 单站点训练、叠加预览 |
| 联邦层 | FLARE Recipe/Client、FedAvg/FedProx、SVT | 三站点聚合、全局模型持久化 |
| 隐私层 | Opacus DP-SGD 与 RDP 会计 | 预算收据、效用对照 |
| 安全层 | Provision、证书、双设备演练 | mTLS 注册/重连/拒绝 |
| 交付层 | React 驾驶舱、FastAPI、Docker、评审一键包与 GitHub 发布基线 | 43 项 Python 测试、Ruff、Vite build、review script |

**开发原则**：优先复用 NVIDIA FLARE、MONAI、PyTorch、Opacus 的现成能力，把时间投入到医院研究流程、证据治理和边界控制，而不是重复造轮子。

### English

**Slide title**: More than a front-end demo

| Stage | Delivery | Verification |
| --- | --- | --- |
| Domain model | Study, Protocol, Contract, Run and Evidence state machine | API workflow tests and audit ledger |
| Agent layer | Five roles, deterministic fallback, input/output gates | Step 3.7 JSON smoke test and 26 red-team cases |
| Imaging | NIfTI, synthetic four-modal data, SegResNet, Dice/HD95 | MONAI single-site training and overlays |
| Federation | FLARE Recipe/Client, FedAvg/FedProx, SVT | Three-site aggregation and global checkpoint |
| Privacy | Opacus DP-SGD and RDP accounting | Budget receipt and utility comparison |
| Security | Provisioning, certificates and two-device rehearsal | mTLS registration/reconnect/rejection |
| Delivery | React cockpit, FastAPI, Docker, reviewer one-command package and a GitHub release baseline | 43 Python tests, Ruff, Vite build and review script |

**Development principle**: reuse NVIDIA FLARE, MONAI, PyTorch and Opacus instead of rebuilding infrastructure; invest engineering time in research workflow, evidence governance and safe boundaries.

## A8. 评委一键复现路径 / One-click reviewer path

### 中文

**页面标题**：不下载大数据，也能先验证系统完整性

**命令**：

```bash
bash scripts/review_demo.sh
```

**脚本执行**：

1. 只在缺少运行证据时写入明确标记为 snapshot 的 compact fixtures。
2. 检查五种子多轮结果是否为 `25/25`。
3. 检查 DP 是否标注为 sample-level，并拒绝端到端夸大。
4. 检查 mTLS 是否包含注册、重连、错误身份拒绝且不含 token。
5. 检查 Agent 红队是否 `26/26`，攻击 payload 不进入发布 evidence。
6. 将四个 gate 的结果写入证据驾驶舱。

**演示画面**：终端 20 秒 → 四张证据卡 20 秒 → 运行报告和边界声明 20 秒。

### English

**Slide title**: Verify system completeness before downloading large data

```bash
bash scripts/review_demo.sh
```

**What it does**:

1. Seeds clearly labelled compact snapshots only when runtime evidence is absent.
2. Verifies the 5-seed multi-round matrix is `25/25`.
3. Verifies that DP is labelled sample-level and rejects end-to-end overclaiming.
4. Verifies mTLS registration, reconnect, wrong-identity rejection and token absence.
5. Verifies `26/26` Agent red-team coverage without publishing attack payloads.
6. Writes the four gates to the evidence cockpit.

**Demo timing**: terminal 20 seconds → four evidence cards 20 seconds → report and boundaries 20 seconds.
