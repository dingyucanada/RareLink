# RareLink 最终提交清单（DGX Spark Hackathon）

> 提交版本：`v0.2.2`  
> 项目定位：面向多中心罕见病医学影像科研的“数据不出院、证据可回溯”联邦学习 Agent Team。  
> 使用原则：仅作科研工程验证，不提供诊断或治疗建议；不提交、传播或展示任何 API Key、密码、患者原始数据或可识别信息。

## 一、提交入口（提交前填写链接）

| 组委会要求 | 最终提交内容 | 当前状态 | 提交时填写 |
| --- | --- | --- | --- |
| 项目开源提交 | GitHub 仓库与 Release | 已完成 | [GitHub 仓库](https://github.com/dingyucanada/RareLink)；[v0.2.2 Release](https://github.com/dingyucanada/RareLink/releases/tag/v0.2.2) |
| 项目说明文档（600 字以上） | 作品特点、亮点、架构、优化与边界 | 已完成，2,519 字符 | [项目说明](RareLink-比赛项目说明.md) |
| 部署说明 | Spark 本地部署、模型优化、运行与复现 | 已完成 | [部署手册](../docs/deployment.md) |
| 技术栈说明 | NVIDIA、Stepfun 与应用技术栈 | 已完成 | [技术栈说明](RareLink-技术栈说明.md) |
| 作品演示视频 | 3 分钟成片，公开可访问 | 待团队录制与上传 | `【待填：视频链接】` |
| 团队资料 | 真实团队合影 | 待团队提供 | `【待填：团队合影链接或提交附件】` |
| 赛事征文 | DGX Spark 黑客松“十日谈”外链 | 文稿已完成，待发布 | `【待填：CSDN / 知乎文章链接】` |

## 二、100 分评审标准对齐

| 评审维度 | 分值 | RareLink 已交付的可核验证据 | 视频中应出现的画面 |
| --- | ---: | --- | --- |
| 项目实用性、行业落地价值与技术创新性 | 25 | 以儿童高级别胶质瘤等小样本多中心 MRI 科研为具体场景；原始影像留在站点、协调方只见聚合指标；研究协议、实验合同、失败重试与报告均进入账本。 | “数据不出科室”架构、协议到证据的闭环、最弱站点风险指标。 |
| 智能体融合与模型优化技术深度 | 25 | 五角色 Agent Team；Spark Local / Step / Template 三路由；输入脱敏、输出门控、26/26 红队；本地 TensorRT-LLM 元数据回执、独立核验与 `1/2/4` 安全并发基准工具；5 种子 × 5 策略 × 3 轮实验与样本级 DP-SGD。 | Agent 生成受控协议、红队拦截、策略/隐私对照；若完成实机采证，展示 `VERIFIED`，否则明确 `NOT CLAIMED`。 |
| 项目完整性 | 20 | React 证据驾驶舱、FastAPI 控制面、SQLite 审计账本、MONAI 训练、FLARE 编排、Docker Compose、测试与一键核验脚本齐全；GitHub Release 已发布。 | 前端从研究发起到证据导出的一条完整路径；运行中的 API/服务。 |
| 平台适配性 | 15 | DGX Spark GB10 / CUDA 13 实机完成 CUDA、MONAI 3D SegResNet、NVIDIA FLARE 聚合、前后端服务；Docker NVIDIA runtime 与 ARM64 部署说明完备。 | Spark 实机终端、GPU 烟测输出、MONAI / FLARE 日志、服务访问页面。 |
| 演示效果 | 10 | 已提供逐秒脚本与两段短证据素材建议。 | 严格按 3 分钟脚本录制，先结论后证据，最后清楚说明边界。 |
| 赛事征文 | 5 | 十日谈文稿已完成。 | 不必占用主视频时间；发布后在最终提交表填入 CSDN / 知乎 URL。 |

## 三、评委复现入口

在已安装 Python 依赖的环境中执行：

```bash
bash scripts/review_demo.sh
```

该命令验证四项不依赖大数据下载的证据门：五种子多轮结果、样本级 DP-SGD 边界、两物理设备 mTLS 演练证据、Agent 安全红队结果。容器化入口见 `deploy/compose.spark.yml`；完整流程见部署手册。

如 Spark 本地 TensorRT-LLM 已真实运行，可额外执行 `make spark-local-verify` 与 `make spark-local-benchmark`。这两项是可选实机加分证据，不会由一键复现包 seed，也不能在未产生真实 GPU 回执前写为“已验证”。

## 四、提交前最后检查（负责人：团队）

- [ ] 视频链接可公开播放，时长约 3 分钟，开头 15 秒说明问题与结果，末尾明确“科研工程原型、非临床诊断”。
- [ ] 视频不出现终端密码、Step API Key、SSH 地址、患者影像、患者 ID 或任何可识别字段。
- [ ] 团队提交真实合影；不以 AI 生成图替代真实团队资料。
- [ ] 将 `RareLink-DGX-Spark黑客松十日谈.md` 发布到 CSDN 或知乎，按平台规则标注 AI 协助内容（如有），并填写外链。
- [ ] 在组委会的链接提交表中依次粘贴：仓库、说明文档、部署文档、视频、征文、团队合影。
- [ ] 以无痕窗口打开所有外链；确认 GitHub 主页显示项目描述、技术标签、README 与 Release。
