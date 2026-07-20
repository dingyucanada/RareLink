# RareLink 三分钟演示视频脚本

> 全程只展示项目界面、合成可视化和聚合指标；不展示真实患者影像、节点凭据、API Key 或原始数据目录。旁白必须说“逻辑站点”“工程验证”“非临床”。

| 时间 | 画面与实际操作 | 旁白/字幕 |
|---|---|---|
| 0:00–0:10 | 只给 3 秒标题卡；立即切入网页顶部的 **DGX Spark · Verified Run Receipt**。 | “RareLink 不是静态大屏，而是一套把多中心研究动作和证据收据连接起来的科研操作系统。” |
| 0:10–0:31 | 在网页点击 **核验本地证据哈希**。等待 `Integrity Verified` 和五项绿色核验结果出现；鼠标停在 `24`、`3/3`、`69.0s`、`5.24 GiB` 四个指标。 | “这是已经提交的 DGX Spark 真实公开影像运行收据。系统重新读取四份聚合文件并核验哈希：二十四例 MSD 四模态 MRI、三个逻辑站点全部聚合、端到端约六十九秒。原始影像和模型权重不回传浏览器。” |
| 0:31–0:47 | 点击 **展开站点收据**，依次指向 site A/B/C 的 Dice、HD95、训练耗时；停在边界声明。 | “每个站点只暴露聚合指标。这个结果是一轮、一 epoch 的工程 smoke test，不是儿童队列、临床性能或真实跨院部署的结论。” |
| 0:47–1:06 | 下滑至 **交互式工作流**，点击“生成研究协议”；展示协议从研究问题变为固定终点、约束和局限性。 | “真实收据与工作流沙盘被明确区分。研究者先提出问题，研究主任 Agent 生成结构化协议；它只能使用脱敏研究上下文。” |
| 1:06–1:25 | 点击批准并运行站点统计；展示三张 `WORKFLOW SANDBOX` 卡片和被阻断字段数量。 | “站点数据管家只返回受控汇总统计。患者字段、小样本明细和原始影像会在策略门控处阻断，不能进入 Agent 或外部模型。” |
| 1:25–1:43 | 点击生成并锁定实验合同；展示策略、固定预算、审批轨迹。 | “实验设计 Agent 可以提出对照策略，但无法自行启动或改变研究合同；PI 锁定相同划分、相同预算和公平性指标后，动作才被允许。” |
| 1:43–2:01 | 点击运行沙盘实验，录制训练任务卡进度与策略公平比较图；随后切 **评审证据驾驶舱**。 | “工作流把每一步写入审计账本。策略比较同时呈现平均 Dice、最弱站点 Dice、站点差异和 HD95，避免只用平均数掩盖小中心退化。” |
| 2:01–2:22 | 点击 **生成证据解读**，展示 Agent 生成的候选策略、公平性和局限性；再滚动到红队、DP 与 mTLS 证据卡。 | “证据 Agent 仅读取已经锁定的聚合指标，生成可追溯解释和限制条件。样本级 DP-SGD、跨设备 mTLS 与 Agent 红队结果均有可复核证据。” |
| 2:22–2:43 | 插入短终端素材：`bash scripts/review_demo.sh` 的必检 gate 通过；立即切回网页的对应证据卡。 | “前端并不是结论来源。评委可以运行一键核验：它不下载医学影像，也不需要 API 密钥，而是验证提交的工程收据。” |
| 2:43–2:55 | 先插入 `assets/screenshots/dgx-spark-openclaw-comfyui-workshop-receipt.png` 约 4 秒，再给脱敏的 Spark 训练/FLARE 聚合完成日志约 4 秒，最后切回实际网页的 Verified Run Receipt 约 4 秒。 | “赛事参考 Workshop 已在同一台 Spark 上完成本地多模态 Agent 链路核验；RareLink 则用这台 Spark 承担 CUDA 三维训练和 FLARE 聚合。两条证据独立呈现，网页统一展示运行结果、边界与文件完整性收据。” |
| 2:55–3:00 | 回到网页顶端，定格 `Integrity Verified` 与项目一句话。 | “RareLink 让数据不出院，让证据可回溯。它是工程原型，不替代医生。” |

## 录制前检查

1. 浏览器打开前端，后端 `/api/health` 返回正常；先确认网页顶部出现 `Receipt Ready`，并且“核验本地证据哈希”可点击。
2. 点击核验按钮一次，录到 `Integrity Verified`、五项通过项与核验时间；再点击“展开站点收据”。这是主视频必须出现的真实功能操作。
3. 再预置或现场完成一个工作流沙盘研究，至少有 Local、FedAvg、FedProx 指标和一条 Agent 证据解读。画面必须标明 `WORKFLOW SANDBOX`，不可将其说成真实跨院训练。
4. 在视频角落或结尾展示：`Research-use engineering demo · MSD public-data smoke test · 3 logical sites on one DGX Spark · Not clinical validation`。
5. 需要证明 Spark 时，展示脱敏后的 `nvidia-smi`、MONAI/NVFLARE 日志摘要或项目内实机验证报告，绝不展示用户名、密码、IP、端口、密钥和数据路径。

## 已准备好的静态插入素材

两张 PNG 已放入仓库，均可直接拖入剪辑软件；不要为它们补造终端画面或模拟运行记录。

| 文件 | 用途 | 推荐位置 | 必须保留的说明 |
|---|---|---|---|
| `assets/screenshots/rarelink-live-evidence-console.png` | RareLink 实际本地运行的证据驾驶舱截图 | 主视频开头；也可在点击哈希核验后用作 1–2 秒定格画面 | `MSD public-data engineering smoke test · 3 logical sites on one DGX Spark · Not clinical validation` |
| `assets/screenshots/dgx-spark-openclaw-comfyui-workshop-receipt.png` | 官方 OpenClaw + ComfyUI 参考 Workshop 的无敏感完赛收据 | 2:43–2:47 的短切片或答辩插图 | “赛事参考代码基础完赛，与 RareLink 医学科研链路独立。” |

## 两段可插入答辩的短证据素材（各 20–30 秒）

### 素材 A：评审一键核验（推荐 25 秒）

**目的**：证明成果不是只存在于前端截图中；25 次实验、DP 边界、mTLS 演练和 Agent 红队均有可重复校验的收据。

**画面准备**：在本地项目根目录打开干净终端，隐藏终端标题中的用户名与路径；字体调大到 20–24 pt。只输入以下命令，不展示 `.env`、历史命令或任何连接信息：

```bash
bash scripts/review_demo.sh
```

录到四个**必检** gate 都显示 `true` 且总结果 `passed: true` 后，立刻切到证据驾驶舱的对应四张卡片。`spark_local_inference_verified=false` 是尚未采集真实本地 LLM 回执时的**可选项**，不属于这段素材的四个 gate；录屏时裁掉该行，不要把它解释为主证据失败。不要录安装依赖、下载数据或大段滚动日志。

**口播（约 25 秒）**：

> “这是评委可直接运行的一键核验。它不下载医学影像，也不依赖 API 密钥；它核验四类已经提交的工程证据：五种子多轮实验、样本级 DP-SGD 的声明边界、Spark 与 Mac 两物理设备的 mTLS 演练，以及 Agent 安全红队。现在四个必检 gate 都通过。前端只呈现这些聚合结论和可追溯收据，不呈现原始影像或患者字段。”

**剪辑点**：命令执行前留 1 秒；四个通过结果停留 3 秒；切到前端四张卡片停留 4 秒。全段控制在 22–28 秒。

### 素材 B：Spark 实机训练与安全边界（推荐 25 秒）

**目的**：证明 DGX Spark 不是静态部署页面，而是承担 CUDA/三维训练/联邦编排；同时说明不夸大为临床系统。

**画面准备**：使用已准备好的、脱敏的实机日志或报告截图。优先展示 MSD 报告中的“24 cases / 3 logical sites / 3 of 3 aggregated / global model persisted / 69.0084 s”，并在另一侧展示证据驾驶舱的 Spark 卡片。若录制终端，只保留 GPU 名称、CUDA、MONAI、FLARE、训练完成和聚合完成等行；裁掉用户名、主机名、IP、端口、容器 ID、文件路径和所有凭据。不要现场运行长训练，不展示真实 MRI 切片，也不要展示尚未采证的 Spark 本地 LLM 路径。

**口播（约 25 秒）**：

> “这是 NVIDIA DGX Spark 上的真实公开影像工程验证。二十四例 MSD 四模态脑肿瘤 MRI 在本地完成校验和 MONAI CUDA 训练，NVIDIA FLARE 收到三个逻辑站点的全部更新并生成全局模型，端到端约六十九秒。比赛版本仍是在一台 Spark 上串行模拟三个科室；它证明真实数据链路能够运行和审计，不代表儿童队列、临床有效性或真实多医院部署。”

**剪辑点**：先给 4 秒实机环境摘要，再给 8 秒训练/聚合完成行，最后 8 秒回到前端的“3 logical sites / engineering validation”边界标签；结尾静止 2 秒。

### 素材 C：本地 LLM 证据链（仅在真实 Spark 回执存在时使用，推荐 20 秒）

**目的**：把 Spark 的本地 Agent 能力展示为可审计工程链路，而非一句“可运行 200B”的口号。

**画面准备**：只展示脱敏后的终端输出和驾驶舱 `SPARK LOCAL LLM` 卡片。先后显示本地模型服务、`capture_spark_local_inference_evidence.py`、`run_spark_local_llm_redteam.py`、`verify_spark_local_inference_evidence.py` 的结果。画面中必须能看到 `remote_step_api_called=false`、`raw_patient_data_transmitted=false`、GPU 快照和 `26/26`；不得展示模型下载 token、IP、端口、提示词或模型回答。

**口播（约 20 秒）**：

> “这是 Spark 上的本地 Agent 证据链。模型只接收策略批准的聚合科研上下文，系统不保存提示词、回答或患者字段，只记录模型、延迟、GPU 快照和输出哈希。我们再用固定 26 条网关用例核验输入脱敏和输出门控；没有这份真实回执，驾驶舱不会把本地推理写成已完成。”

**替代规则**：若尚未完成真实本地模型运行，不录制本段，也不要用截图、种子文件或模拟数字替代；改在主视频口播“本地路径已实现，实机证据待采集”。

## 推荐录屏方式

主视频以**可操作的前端界面为主（约 70%）**，但不建议全程只录前端。前 47 秒必须包含“点击核验哈希 → 返回通过结果 → 展开三站点聚合收据”，用实际交互证明不是 PPT 或模拟游戏；随后用工作流沙盘呈现 Agent 的可控动作。至少插入上述两段短素材：它们分别回答评委最常问的“如何复现”和“Spark 实际做了什么”。录屏分辨率使用 1920×1080、30 fps，浏览器缩放 100%–110%，鼠标移动缓慢并在每个关键数字停留约 2 秒。字幕只强化结论，不重复整段口播：

- `数据不出科室 · 仅聚合证据`
- `5 seeds × 5 strategies × 3 rounds`
- `Sample-level DP-SGD · ε=6.076881, δ=1e-5`
- `3 logical sites on one DGX Spark · Engineering validation`
- `Not clinical validation`

不要使用 AI 生成的团队合影替代真实团队资料；若社媒成片含 AI 生成的图像、配音或视觉素材，按发布平台规则作出 AI 生成标注。
