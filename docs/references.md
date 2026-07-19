# RareLink 技术与数据参考 / Technical & Data References

本页集中列出项目依赖、术语和公开数据的权威入口。链接用于解释来源和使用边界，不代表 RareLink 已经完成这些数据集上的临床验证。

## NVIDIA 与医学 AI 技术栈

| 主题 | 官方资料 | RareLink 中的用途 |
| --- | --- | --- |
| NVIDIA DGX Spark | [产品页](https://www.nvidia.com/en-us/products/workstations/dgx-spark/) · [User Guide](https://docs.nvidia.com/dgx/dgx-spark/index.html) | GB10 / ARM64 本地训练、联邦 Client 与服务部署。 |
| CUDA | [NVIDIA CUDA Platform](https://developer.nvidia.com/cuda) | GPU 张量计算与 PyTorch CUDA 运行时。 |
| NVIDIA FLARE | [官方文档](https://nvidia.github.io/NVFlare/) · [GitHub](https://github.com/NVIDIA/NVFlare) · [医疗影像目录](https://nvidia.github.io/NVFlare/catalog/) | FedAvg/FedProx 编排、Client API、mTLS 安全通信与模拟/演练。 |
| MONAI | [Project MONAI](https://project-monai.github.io/) · [Docs](https://docs.monai.io/) | NIfTI transforms、3D SegResNet、医学影像训练和评估。 |
| PyTorch | [官方文档](https://pytorch.org/docs/stable/index.html) | 模型、优化器、AMP 与 CUDA 张量。 |
| Opacus | [官方站点](https://opacus.ai/) · [PrivacyEngine API](https://opacus.ai/api/privacy_engine.html) | 样本级 DP-SGD、逐样本梯度、裁剪、噪声和隐私会计。 |

## 术语与研究依据

| 主题 | 权威资料 | 项目表述边界 |
| --- | --- | --- |
| 联邦学习定义 | [NIST CSRC Glossary](https://csrc.nist.gov/glossary/term/federated_learning) | 交换模型更新而不是集中原始数据；不等于自动满足合规或隐私。 |
| 联邦学习安全与隐私 | [NIST: Privacy Attacks in Federated Learning](https://www.nist.gov/blogs/cybersecurity-insights/privacy-attacks-federated-learning) | 模型更新、统计结果和日志仍可能泄露信息，因此需要策略、身份、审计和 DP 等额外控制。 |
| 罕见病定义 | [NIH GARD FAQ](https://rarediseases.info.nih.gov/diseases/pages/31/faqs-about-rare-diseases) | 本项目使用“罕见病”描述研究场景，不据此宣称疾病诊断或流行病学结论；GARD 的定义是美国语境下少于 200,000 人受影响。 |
| 医学分割基准 | [Medical Segmentation Decathlon](https://medicaldecathlon.com/) · [Nature Communications paper](https://doi.org/10.1038/s41467-022-30695-9) | MSD 是公开研究基准，适合工程泛化/分割评估，不等于临床验证。 |

## 数据来源与当前状态

| 数据 / 资产 | 来源与政策 | RareLink 当前状态 |
| --- | --- | --- |
| 合成四模态 MRI | RareLink 本地生成器 | 用于软件、训练、联邦聚合和前端链路冒烟；不是患者数据。 |
| MNI152 结构 MRI/NIfTI 对 | [Project MONAI extra-test-data release](https://github.com/Project-MONAI/MONAI-extra-test-data/releases/tag/0.8.1) | 已在 Spark 完成一对公开 NIfTI 图像/结构标签的几何与哈希接入校验；不是 MSD、肿瘤分割或临床结果。 |
| MSD Task01_BrainTumour | [官方数据页](https://medicaldecathlon.com/dataaws/) · [官方 S3 archive](https://msd-for-monai.s3-us-west-2.amazonaws.com/Task01_BrainTumour.tar) · [任务论文](https://doi.org/10.1038/s41467-022-30695-9) | 赛事 Spark 已完成归档校验、24 例几何检查、单站 CUDA 与三逻辑站点一轮 FedAvg；仅作工程兼容性证据，不等于儿童队列或临床性能。 |
| BraTS-PEDs | [TCIA collection](https://www.cancerimagingarchive.net/collection/brats-peds/) · [TCIA policy](https://www.cancerimagingarchive.net/tcia-data-usage-policy/) | 计划中的儿童高级别胶质瘤外部研究验证数据；需遵守 TCIA/Synapse 条款和数据引用要求，当前版本不宣称已完成该基准训练。 |

## Stepfun Step 3.7

| 组件 | 官方入口 | RareLink 的边界 |
| --- | --- | --- |
| Step 3.7 / Step Plan | [Stepfun Platform](https://platform.stepfun.com/) | 作为远程 Agent 推理服务，处理脱敏研究协议、聚合指标和报告上下文；不在 Spark 上加载 Step 权重。 |
| API 使用 | 项目部署手册中的兼容 OpenAI API 配置 | API Key 只放在本地 `.env`，不进入仓库、日志、截图或数据包。 |

## 引用建议

引用 RareLink 的工程实现时，请同时说明：版本、运行节点、数据来源、是否为合成数据、是否为逻辑站点模拟，以及“非临床验证”的边界。公开数据集请按各自页面的作者、DOI、许可证和 Data Usage Policy 要求引用。
