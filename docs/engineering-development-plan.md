# RareLink 正式工程开发计划

**文档状态：** Implementing Baseline
**适用版本：** Physical Federation Control Plane v0.2 及后续版本
**目标环境：** 三家研究机构各部署一台 NVIDIA DGX Spark，并由独立协调端运行 NVIDIA FLARE Server
**文档责任人：** RareLink 工程团队
**变更原则：** 涉及数据边界、身份、quorum、隐私预算或结果发布条件的变更，必须通过架构决策记录（ADR）和人工审批。

> **用途声明：** RareLink 是多中心科研协作软件，不是医疗器械，不用于自动诊断、治疗建议或替代医生。本文定义的是达到受控科研试点所需的工程能力；不能替代伦理审批、数据使用协议、医院信息安全评估、DPIA/等保、渗透测试、临床验证或适用监管程序。

## 1. 文档目的

本文把 RareLink 从“单机仿真与物理部署工具集”演进为“可运营的三站点联邦科研软件”，并给出可直接进入迭代管理的工作分解、接口草案、状态机、安全控制、测试矩阵和验收口径。

本文解决以下问题：

1. 三台物理 Spark 如何被独立识别、预检、启动、监控、断线重连和审计；
2. 中心控制面如何审批并提交真实 NVIDIA FLARE 作业，保存真实 Job ID；
3. 如何确保病例、影像、标签、病例级指标和本地路径始终留在所属医院；
4. 如何防止重复提交、重复轮次、迟到更新以及未满足参与方合同时错误发布结果；
5. 如何在设备到位前以三个隔离容器验证控制协议，设备到位后不修改业务协议；
6. 如何定义“完成”，避免把 UI 演示、SimEnv 或单机逻辑站点误认为真实多中心验证。

### 1.1 2026-07-26 实现检查点

本检查点已经把 P0 控制协议从方案落实为可运行代码，但不将其表述为三院上线：

| 能力 | 当前实现 | 验收证据 | 尚未完成 |
| --- | --- | --- | --- |
| 独立 Site Agent | 每站独立 FastAPI、SQLite 状态库、健康预检、签名心跳 | Site Agent 与负面测试 | 医院证书吊销和多实例高可用 |
| 本地任务控制 | `start/stop/recover` 状态机、`task + round + contract` 幂等、重启失败关闭 | 重复执行、合同冲突、恢复测试 | checkpoint 语义和跨进程事务锁 |
| FLARE Client 生命周期 | 固定 unit、无 shell 的 systemd 适配器；默认禁用 | 命令白名单和敏感错误输出测试 | 三台 Spark 上的 polkit 与现场故障演练 |
| 中心物理作业 | 导出包校验、人工审批、真实 FLARE Job ID、sync/abort/retry/resume | 注入式 NVIDIA FLARE CLI 契约测试 | 真实 Admin Kit 的三设备端到端运行 |
| 固定参与方 | 严格三个指定 Site ID、`3/3` quorum，2/3 不得完成 | 不完整 quorum 失败测试 | 安全聚合和迟到更新的 FLARE 侧插件 |
| 结果入账 | 全局模型文件与可信 SHA-256 核验，路径不出协调端 | 模型篡改负面对照 | 模型签名、模型卡和发布双人审批 |
| 物理运行面 | 真实 Site/Job API 轮询，显示站点、轮次、Job ID、quorum 与回执 | TypeScript 生产构建 | SSE 和操作按钮审批流 |
| OIDC/RBAC | 受信内存 JWKS 离线验证 RS256/ES256；校验 issuer/audience/time/sub/角色/组织/站点 claims；五角色九权限，physical 拒绝 legacy token | JWT 正反例、权限矩阵与 API 硬门测试 | discovery/HTTPS JWKS、自动缓存轮换、MFA、会话吊销 |
| 合同双人审批 | Contract v1 锁定 study/strategy/bundle/排序三站/逐站数据指纹/轮数/本地 epochs/3-of-3；不同 OIDC `sub` 持久化第二审批 | 摘要变化、自批、幂等、竞争、明文 note 泄露和提交硬门测试 | 撤销、过期、替补、执行动作双审和 PostgreSQL 并发 |
| 站点资源 scope | 所有目标站点必须为 OIDC `site_ids` 子集；覆盖登记、合同创建/批准、提交、同步、停止、重试/恢复和模型核验，NVFLARE 前失败关闭 | 逐端点越界负例和错误信息最小化 | 公开列表/audit 过滤、组织/研究 scope、跨组织治理 |
| 物理审计链 | 规范化事件、前序摘要、SHA256 历史兼容、HMAC-SHA256 新事件、公开摘要/受保护明细分离 | 篡改、敏感字段、密钥硬门和 API 边界测试 | PostgreSQL 串行写入、WORM 锚定、拒绝事件全集和 HMAC key-ring |
| 模式隔离 | `disabled / isolated-integration / physical` 进入 API 和 UI | 默认失败关闭、模式测试 | 生产策略中心 |
| 设备前验收 | 三个独立 OS 进程生成各自签名心跳，中心接受 3/3 并创建合同 | `make physical-control-smoke` 返回 `passed=true` | 三容器网络故障矩阵和三 Spark Level 2 |
| 医院 NIfTI 数据层 | 四模态、几何、标签、路径和直接标识质控；生成脱敏内容指纹 | 数据证明、篡改/外站/标识/几何负面对照 | DICOM/PACS、MONAI 缓存服务和医院数据治理审批 |
| 数据版本合同 | 物理作业固定三站数据指纹；变化时自动失败且禁止 retry/resume | API 失效测试与训练前内容复核 | 合同修订 UI、双人复核和 PostgreSQL 事务 |

当前全量回归为 **194 项测试通过**；Python lint、前端 TypeScript/Vite 生产构建和
Git diff 完整性检查通过。这些是软件回归证据，不是医学性能或临床验证证据。
当前 Site Agent 心跳仍使用每站独立 HMAC，NVIDIA FLARE 数据面使用证书化通信；
操作员 API 已增加离线 OIDC JWT 验证与固定 RBAC，`physical` 模式拒绝 legacy
token。JWKS 仍由环境 JSON 注入，尚无 discovery/HTTPS 拉取、自动缓存轮换、
MFA 和会话吊销。目标明确的控制操作已强制 `site_ids` 全目标站点子集，但公开
列表、audit read、组织/研究 scope 和跨组织治理仍待完成，见
[物理控制面 OIDC/RBAC 文档](physical-identity-rbac.md)和
[站点资源级授权](physical-site-scope.md)。物理合同的不同主体
第二审批已经持久化并在 submit/retry/resume 前重新核验；审批撤销、过期、替补
和执行动作双审仍待完成，见[物理合同双人审批](physical-dual-approval.md)。
物理事件链已能检测历史修改并在 `physical` 模式强制配置
HMAC 密钥，但 SQLite pilot 不是 WORM，尚未覆盖全部拒绝操作，也没有旧 HMAC
key-ring 轮换；多 worker 串行写入仍需 PostgreSQL。医院级 mTLS/OIDC 身份、
PACS/FHIR、安全聚合和真实三设备运行仍按下文 P1/P2 与 Level 2 推进。完整设计、
API 边界与验收见[物理控制面审计文档](physical-audit.md)。

## 2. 产品范围与非目标

### 2.1 本阶段范围

- 独立的 RareLink Site Agent，每家医院一套实例、一套身份和一套本地状态库；
- 中心 Federation Controller，通过受控 Admin Kit 管理真实 NVIDIA FLARE 作业；
- 站点注册、证书身份、心跳、环境预检和数据就绪证明；
- 作业审批、提交、轮次监控、停止、受控重试、恢复和结果入账；
- Job、Site、Round 和 Command 四级幂等；
- 固定参与方合同、3/3 quorum、掉站与迟到更新处理；
- NIfTI + JSON manifest 的院内数据导入、质控、版本和失效机制；
- OIDC/RBAC/PostgreSQL、审计事件链和密钥隔离；
- 样本级 DP-SGD 会计、更新裁剪、模型完整性和基础投毒检测；
- 真实物理模式与模拟模式在 API、数据库、UI 和证据包中的强制区分；
- 三容器集成环境和三台物理 Spark 的分级验收。

### 2.2 明确非目标

- 本阶段不直接提供诊断结论、临床决策或自动发布科研结论；
- 不把联邦学习、mTLS 或差分隐私描述为“天然合规”或“绝对不会泄露”；
- 不允许中心控制面、Agent 或第三方模型访问原始影像、标签和病例级记录；
- 不在首个正式版本接入生产 PACS；首版只支持 NIfTI + JSON manifest；
- 不承诺跨医院生产部署已经完成，除非三台物理设备按本文完成验收；
- 不把单 Spark 的三个进程、三个容器或 NVIDIA FLARE SimEnv 作为跨院证据；
- 不在首个版本实现任意拓扑、动态匿名站点加入或无审批自动训练；
- 不允许 Agent 放宽隐私、quorum、结果发布或人类审批门；
- 不把外部公开数据集实验包装为临床有效性验证。

## 3. 角色、责任与权限边界

| 角色 | 主要责任 | 允许操作 | 禁止操作 |
| --- | --- | --- | --- |
| Principal Investigator（PI） | 研究目标、合同、结果解释与发布审批 | 批准合同、启动和发布；中止研究 | 查看其他医院病例级数据；绕过安全门 |
| Federation Administrator | FLARE Server、Admin Kit、作业运维 | Provision、提交、停止、恢复、轮换证书 | 接触医院原始影像；修改已签名运行收据 |
| Site Administrator | 本站 Spark、Site Agent、Client Kit | 本站预检、服务启停、故障恢复 | 操作其他站点；读取 Admin Kit |
| Data Steward | 本站数据授权、导入、质控和版本 | 生成/撤销本地 manifest 和数据证明 | 导出病例数据到协调端 |
| Security/Privacy Reviewer | 威胁、DP 预算和发布边界审查 | 阻断作业或发布；审阅审计材料 | 单方面降低安全阈值 |
| Statistical Reviewer | 聚合统计、稳定性和最弱站点审查 | 审阅获批准的聚合指标 | 查询病例级指标或未经批准的小分组 |
| Research Viewer | 查看获批准的研究状态和报告 | 只读访问 | 启动作业、下载模型或查看敏感日志 |
| RareLink Agent Team | 基于获批准聚合证据生成建议稿 | 生成结构化草案并引用证据 | 发起训练、修改合同、访问影像或自动发布 |

高风险操作必须使用双人复核：锁定/修订研究合同、提交正式作业、改变 DP 预算、降低 quorum、撤销证书、下载或发布全局模型、发布研究结论。

## 4. 目标组件架构

```mermaid
flowchart TB
    UI["RareLink Research Console"] --> API["FastAPI Control API"]
    API --> AUTH["OIDC / RBAC"]
    API --> DB["PostgreSQL\n合同·作业·审批·审计"]
    API --> FC["Federation Controller"]
    API --> EV["Event Stream\nSSE / WebSocket"]
    FC --> ADM["受控 Admin Kit Adapter"]
    ADM --> FS["NVIDIA FLARE Server\nCoordinator"]
    FS <-->|"mTLS"| SA["Hospital A\nSite Agent + FLARE Client + MONAI"]
    FS <-->|"mTLS"| SB["Hospital B\nSite Agent + FLARE Client + MONAI"]
    FS <-->|"mTLS"| SC["Hospital C\nSite Agent + FLARE Client + MONAI"]
    SA --> DA["A 院内 NIfTI / Label / Manifest"]
    SB --> DBB["B 院内 NIfTI / Label / Manifest"]
    SC --> DC["C 院内 NIfTI / Label / Manifest"]
    API --> REG["Artifact / Evidence Registry\n哈希·签名·聚合结果"]
    API --> AG["Agent Gateway\n仅脱敏合同与批准聚合证据"]
    OBS["Prometheus · OpenTelemetry · 脱敏日志"] -.-> API
    OBS -.-> FC
    OBS -.-> SA
    OBS -.-> SB
    OBS -.-> SC
```

### 4.1 组件职责

| 组件 | 唯一职责 | 持久化内容 | 不得持有 |
| --- | --- | --- | --- |
| Control API | 身份、授权、审批、状态查询和命令编排 | 研究、合同、审批、命令和审计元数据 | 原始影像、标签、FLARE 私钥 |
| Federation Controller | 作业导出、提交、查询、停止、恢复、结果核验 | 外部 Job ID、轮次映射、聚合结果引用 | 病例 manifest、本地路径 |
| Site Agent | 本站预检、心跳、本地训练控制和收据 | 本站任务、资源快照、DP 会计、签名回执 | 其他站点数据和 Admin Kit |
| FLARE Server | 联邦任务编排和模型聚合 | 全局模型、批准的更新与聚合状态 | 医院影像盘和本地 checkpoint |
| FLARE Client / MONAI | 院内训练和本地验证 | 本地 checkpoint、病例级日志 | 其他站点数据 |
| Evidence Registry | 可验证证据索引 | 哈希、签名、批准的聚合指标、模型卡 | 未批准病例级或小分组结果 |
| Agent Gateway | 结构化科研草案 | 提示模板、模型版本、脱敏输入摘要、输出哈希 | 影像、密钥、私钥、原始训练日志 |

## 5. 数据分类与数据流

### 5.1 数据分类

| 等级 | 示例 | 允许位置 | 允许传输 |
| --- | --- | --- | --- |
| R4 患者/影像数据 | DICOM、NIfTI、标签、病例 ID、病例级指标 | 所属医院受控存储 | 不得进入中心、Git、Agent 或公共演示 |
| R3 安全秘密 | FLARE 私钥、Admin Kit、OIDC Secret、Vault Token | 对应受控节点或密钥系统 | 仅按专用安全分发流程 |
| R2 受控研究工件 | 模型更新、全局模型、DP 账本、详细训练日志 | 站点或协调端受控工作区 | 仅合同允许的端点和人员 |
| R1 脱敏研究元数据 | Site ID、数据版本哈希、样本数量、聚合指标 | Control API / Evidence Registry | 受 RBAC 与发布规则约束 |
| R0 公开信息 | 软件版本、公开文档、已批准报告 | 公共仓库或主页 | 可公开 |

### 5.2 训练数据流

```mermaid
sequenceDiagram
    participant PI as PI
    participant API as Control API
    participant FC as Federation Controller
    participant FL as FLARE Server
    participant SA as Site Agent A/B/C
    participant DATA as 本院数据

    PI->>API: 审批锁定合同
    API->>FC: create_job(contract_hash, idempotency_key)
    FC->>FC: 导出并校验作业包
    FC->>FL: submit_job(Admin Kit)
    FL-->>FC: nvflare_job_id
    FC-->>API: 保存外部 Job ID
    FL->>SA: 下发轮次任务（mTLS）
    SA->>SA: 校验 site/contract/round/idempotency
    SA->>DATA: 本地读取、MONAI 训练
    DATA-->>SA: 本地批次
    SA->>SA: 裁剪、DP 会计、签名回执
    SA-->>FL: 模型更新 + 合同允许指标
    FL->>FL: quorum 校验与聚合
    FL-->>FC: 轮次/作业状态
    FC->>FC: 校验全局模型签名与哈希
    FC-->>API: 聚合指标与证据引用入账
    API-->>PI: 人工统计评审与发布审批
```

不可变约束：

- Control API 发出的命令只引用 `site_id`、`contract_hash`、`job_id` 和不透明工件引用；
- Site Agent 心跳不得包含文件名、病例 ID、本地绝对路径、图像元数据或病例级异常；
- 数据 manifest 的原文不得上传；中心只接收规范化摘要的哈希、记录数和质控结论；
- 外部 Agent 只消费已通过发布策略的 R0/R1 数据；
- 任何数据版本变化都会生成新 `dataset_fingerprint`，并使依赖旧指纹的未执行合同失效。

## 6. 工作分解结构（WBS）

### 6.1 P0：真实分布式控制面

| WBS | 工作包 | 关键任务 | 交付物 | 前置依赖 | 验收条件 |
| --- | --- | --- | --- | --- | --- |
| P0.1 | Site Agent 基础 | 配置模型、生命周期、健康端点、本地状态库 | 独立服务/容器 | 无 | 三个隔离实例具有不同 Site ID |
| P0.2 | 站点预检 | GPU、磁盘、内存、MONAI、NVFLARE、证书、manifest | 脱敏预检回执 | P0.1 | 任一强制检查失败即 `NOT_READY` |
| P0.3 | 安全注册与心跳 | mTLS 身份绑定、TTL、时钟偏差、最小字段 | 注册/心跳协议 | P0.1 | 中心能区分在线、过期、撤销和不匹配 |
| P0.4 | 本地命令执行 | start/abort/resume/status、幂等和本地恢复 | Command Executor | P0.2/P0.3 | 重复命令不重复计算 |
| P0.5 | 本地工件与收据 | checkpoint、DP 账本、日志、签名收据 | Site Receipt | P0.4 | 收据可验证且不含 R4 数据 |
| P0.6 | FLARE Adapter | export/validate/submit/list/status/abort/download | Controller Adapter | 现有脚本 | 保存真实 NVFLARE Job ID |
| P0.7 | 中心状态协调 | Job/Round/Site/Command 状态机 | Durable Orchestrator | P0.3/P0.6 | 重启后状态可恢复和对账 |
| P0.8 | Quorum 与掉站 | 固定参与方、超时、迟到和重复更新策略 | Policy Engine | P0.7 | 3/3 合同不因 2/3 静默完成 |
| P0.9 | 结果入账 | 模型哈希、签名、指标、工件关联 | Evidence Adapter | P0.6/P0.8 | 仅成功且已核验作业进入评审 |
| P0.10 | 实时控制台协议 | 站点面板、轮次事件、审批、停止/恢复 | API + SSE 契约 | P0.7 | UI 状态来自真实控制面 |

### 6.2 P1：医院数据、身份与联邦安全

| WBS | 工作包 | 关键任务 | 交付物 | 验收条件 |
| --- | --- | --- | --- | --- |
| P1.1 | NIfTI 数据服务 | 导入、四模态匹配、几何/标签质控、确定性划分 | Site Data Service | 未通过质控数据不得训练 |
| P1.2 | 数据版本与证明 | 规范化 manifest 哈希、版本失效、脱敏证明 | Dataset Receipt | 证明不含病例 ID 和路径 |
| P1.3 | PostgreSQL | schema、迁移、事务、备份 | 生产数据库层 | 并发命令和重启不破坏状态 |
| P1.4 | OIDC/RBAC | 医院登录、角色、作用域和拒绝审计 | AuthN/AuthZ | 默认拒绝；越权均被记录 |
| P1.5 | 双人审批 | 合同、提交、预算、发布等审批策略 | Approval Workflow | 发起人与复核人不能相同 |
| P1.6 | 审计事件链 | 规范化事件、前序哈希、签名和验证工具 | Audit Ledger v2 | 篡改/删除可被检测 |
| P1.7 | 密钥与证书 | Vault/KMS、轮换、吊销、到期告警 | Secret Adapter | 私钥不进数据库和日志 |
| P1.8 | DP-SGD 会计 | 样本级裁剪、噪声、每站/全局预算 | Privacy Ledger | 超预算自动阻断 |
| P1.9 | 更新防护 | 更新裁剪、范数/方向异常、迟到与重复保护 | Update Guard | 注入测试触发阻断或告警 |
| P1.10 | 模型完整性 | 全局模型签名、哈希、来源和批准 | Model Receipt | 篡改模型不能发布 |

### 6.3 P2：科研产品与运维

| WBS | 工作包 | 关键任务 | 交付物 | 验收条件 |
| --- | --- | --- | --- | --- |
| P2.1 | 多研究/多模型 | 租户隔离、研究/疾病/模型版本 | Registry | 工件不会跨研究串联 |
| P2.2 | 合同修订与站点生命周期 | 纳入、暂停、退出、修订和重审批 | Governance Workflow | 所有变更可追溯 |
| P2.3 | 科研证据 | 模型卡、数据卡、运行卡、外部验证 | Evidence Package | 结论均能链接到原始证据 |
| P2.4 | 统计分析 | 重复实验、置信区间、最弱站点 | Statistical Review | 不只报告总体平均值 |
| P2.5 | FHIR | ResearchStudy/ImagingStudy 元数据接口 | FHIR Adapter | 不通过 FHIR 传影像像素 |
| P2.6 | 可观测性 | metrics、traces、结构化脱敏日志 | 运维面板 | 单次 Job 可跨组件追踪 |
| P2.7 | 供应链与交付 | ARM64 CI、SBOM、签名、离线包 | Release Bundle | 隔离网络可验证安装 |
| P2.8 | 可靠性 | 备份恢复、故障演练、灰度和回滚 | Runbook | 达到定义的 RTO/RPO |

## 7. API 契约草案

所有写请求必须包含：

- `Authorization: Bearer <OIDC access token>`；
- `Idempotency-Key: <UUID>`，同一操作者、作用域和请求体重复调用返回原结果；
- `X-Correlation-ID: <UUID>`，用于跨服务追踪；
- `If-Match: "<resource_version>"`，用于状态修改的乐观并发控制。

所有资源标识均为不透明 UUID；不得使用患者 ID、设备序列号或本地路径构造 ID。时间统一为 UTC RFC 3339。错误采用 `application/problem+json`，响应中不得包含栈、密钥或本地路径。

### 7.1 站点 API

| 方法与路径 | 调用方 | 用途 | 关键请求字段 | 关键响应字段 |
| --- | --- | --- | --- | --- |
| `POST /api/v1/sites/register` | Site Agent | 使用证书身份注册/续注册 | `site_id`, `agent_version`, `capabilities`, `nonce`, `signature` | `registration_id`, `heartbeat_interval_s`, `policy_version` |
| `PUT /api/v1/sites/{site_id}/heartbeat` | Site Agent | 上报最小运行状态 | `observed_at`, `status`, `active_job_id`, `active_round`, `resource_summary` | `server_time`, `commands_available` |
| `POST /api/v1/sites/{site_id}/preflights` | Site Agent | 上传脱敏预检回执 | `receipt_hash`, `checks`, `dataset_fingerprint`, `signature` | `preflight_id`, `decision` |
| `GET /api/v1/sites` | 已授权用户 | 查询站点状态 | filters | 状态、最后心跳、证书/数据就绪结论 |
| `GET /api/v1/sites/{site_id}/commands/next` | Site Agent | 长轮询获取待执行命令 | `after_sequence` | 单条签名命令或 204 |
| `POST /api/v1/sites/{site_id}/commands/{command_id}/ack` | Site Agent | 确认接收/执行结果 | `attempt`, `state`, `receipt_hash`, `signature` | 当前命令状态 |

### 7.2 研究、审批和作业 API

| 方法与路径 | 调用方 | 用途 | 关键请求字段 | 成功语义 |
| --- | --- | --- | --- | --- |
| `POST /api/v1/studies/{study_id}/contracts` | PI | 创建合同草案 | 站点、策略、轮次、quorum、DP 和发布规则 | 返回不可变版本草案 |
| `POST /api/v1/contracts/{contract_id}/approvals` | 审批人 | 添加批准或拒绝 | `decision`, `reason`, `scope` | 满足审批策略后变为 `LOCKED` |
| `POST /api/v1/federation/jobs` | PI/管理员 | 基于锁定合同创建作业 | `contract_id`, `strategy`, `artifact_refs` | 返回 RareLink Job ID，不立即宣称运行 |
| `POST /api/v1/federation/jobs/{job_id}/approvals` | 第二审批人 | 允许正式提交 | `decision`, `reason` | 满足双人审批后进入 `APPROVED` |
| `POST /api/v1/federation/jobs/{job_id}:submit` | Federation Admin | 提交到 NVIDIA FLARE | 无患者数据；依赖 Idempotency-Key | 保存 `nvflare_job_id` |
| `GET /api/v1/federation/jobs/{job_id}` | 已授权用户 | 查询聚合状态 | 无 | 返回 Job/Round/Site 状态 |
| `POST /api/v1/federation/jobs/{job_id}:abort` | PI/管理员 | 请求受控停止 | `reason` | 先 `ABORT_REQUESTED`，确认后 `ABORTED` |
| `POST /api/v1/federation/jobs/{job_id}:retry` | 管理员 | 重试可恢复失败 | `failed_step`, `reason` | 新 attempt，保留原 Job 关联 |
| `POST /api/v1/federation/jobs/{job_id}:resume` | PI/管理员 | 从核验 checkpoint 恢复 | `checkpoint_ref`, `reason` | 校验后产生恢复 attempt |
| `GET /api/v1/federation/jobs/{job_id}/events` | UI | SSE 状态流 | `Last-Event-ID` | 可断点续读、至少一次投递 |
| `GET /api/v1/federation/jobs/{job_id}/evidence` | 审阅者 | 获取证据索引 | 无 | 仅返回获授权引用与哈希 |

### 7.3 关键资源最小模型

```json
{
  "job_id": "01J...opaque",
  "mode": "physical",
  "contract_id": "01J...",
  "contract_hash": "sha256:...",
  "expected_sites": ["hospital-a", "hospital-b", "hospital-c"],
  "required_quorum": 3,
  "state": "ROUND_RUNNING",
  "current_round": 2,
  "total_rounds": 5,
  "nvflare_job_id": "external-id-after-submit",
  "site_states": {
    "hospital-a": "UPDATE_ACCEPTED",
    "hospital-b": "TRAINING",
    "hospital-c": "OFFLINE"
  },
  "resource_version": 17,
  "updated_at": "2026-07-26T12:00:00Z"
}
```

`mode` 必须是 `physical`、`isolated-integration` 或 `simulation` 之一。`simulation` 和 `isolated-integration` 产生的结果不得进入物理部署证据包。

## 8. 状态机与一致性规则

### 8.1 全局作业状态

```mermaid
stateDiagram-v2
    [*] --> DRAFT
    DRAFT --> VALIDATING: export
    VALIDATING --> VALIDATION_FAILED: invalid
    VALIDATION_FAILED --> DRAFT: revise
    VALIDATING --> AWAITING_APPROVAL: valid
    AWAITING_APPROVAL --> APPROVED: dual approval
    AWAITING_APPROVAL --> REJECTED: reject
    APPROVED --> SUBMITTING: submit
    SUBMITTING --> QUEUED: external Job ID saved
    SUBMITTING --> SUBMIT_UNKNOWN: timeout/ambiguous
    SUBMIT_UNKNOWN --> QUEUED: reconcile by idempotency token
    SUBMIT_UNKNOWN --> FAILED: proved absent
    QUEUED --> ROUND_RUNNING
    ROUND_RUNNING --> ROUND_WAITING: local tasks dispatched
    ROUND_WAITING --> ROUND_AGGREGATING: quorum satisfied
    ROUND_WAITING --> DEGRADED: site timeout
    DEGRADED --> ROUND_WAITING: site recovered
    DEGRADED --> ABORT_REQUESTED: contract requires all sites
    ROUND_AGGREGATING --> ROUND_RUNNING: next round
    ROUND_AGGREGATING --> VERIFYING_RESULTS: final round
    VERIFYING_RESULTS --> SUCCEEDED: signatures/hashes valid
    VERIFYING_RESULTS --> FAILED: verification failed
    QUEUED --> ABORT_REQUESTED
    ROUND_RUNNING --> ABORT_REQUESTED
    ROUND_WAITING --> ABORT_REQUESTED
    ABORT_REQUESTED --> ABORTED: external confirmation
    ABORT_REQUESTED --> ABORT_UNKNOWN: confirmation timeout
    FAILED --> RETRY_PENDING: approved retry
    RETRY_PENDING --> QUEUED: new attempt
    SUCCEEDED --> [*]
    ABORTED --> [*]
    REJECTED --> [*]
```

终态：`REJECTED`、`SUCCEEDED`、`ABORTED`。`FAILED` 只有在明确决定不再重试时才可归档为终态。所有状态转换必须通过服务器端状态机，不能由前端直接写状态。

### 8.2 站点和命令状态

- 站点状态：`UNREGISTERED → REGISTERING → NOT_READY/READY → BUSY → READY`；
- 心跳超过 `2 × heartbeat_interval` 为 `STALE`，超过策略阈值为 `OFFLINE`；
- 命令状态：`PENDING → DELIVERED → ACKNOWLEDGED → RUNNING → SUCCEEDED/FAILED/CANCELLED`；
- 同一 `command_id + attempt` 只允许一个有效结果；
- ACK 丢失时可以重投相同命令，不得生成新的训练动作；
- 站点重启后从本地 durable store 恢复命令，不以中心重复投递作为新任务。

### 8.3 Round 与 quorum

- `expected_sites` 和 `required_quorum` 在合同锁定后不可变；
- 当前三站临床科研试点默认 `required_quorum=3`，任何 2/3 完成都不能自动聚合；
- 降低 quorum 必须创建合同新版本并重新双人审批，不能修改运行中作业；
- 每个更新绑定 `job_id + attempt + round_id + site_id + base_model_hash`；
- 迟到、重复、签名错误或 base model 不匹配的更新必须拒绝并留审计事件；
- 聚合完成前必须记录每个预期站点的接受/拒绝理由；
- 超时后进入 `DEGRADED`，按合同等待、恢复或中止，禁止静默跳过站点。

## 9. 幂等、恢复和对账

| 风险场景 | 处理规则 |
| --- | --- |
| HTTP 提交响应丢失 | 复用相同 Idempotency-Key 查询原结果；不得新建第二个外部作业 |
| FLARE 已提交但本地未保存 Job ID | 进入 `SUBMIT_UNKNOWN`，用提交 token 和作业哈希对账 |
| Site Agent 收到重复 start | 返回已有 command/round 状态，不启动第二训练进程 |
| Agent 重启 | 从本地 SQLite/PostgreSQL 状态恢复，核验实际进程和 checkpoint |
| 中心重启 | 从 PostgreSQL 恢复并向 FLARE/Site Agent 对账，不从 UI 缓存推断 |
| SSE 重连 | 使用 `Last-Event-ID` 续读；事件至少一次投递，前端按 event ID 去重 |
| abort 响应不明确 | 保持 `ABORT_UNKNOWN`，直到外部系统和站点均确认 |
| checkpoint 恢复 | 校验 Job、合同、代码、数据版本、轮次和模型哈希后创建新 attempt |

## 10. 威胁模型与安全控制

### 10.1 保护资产

- R4 患者影像、标签、病例标识和病例级指标；
- FLARE Client/Admin 私钥、OIDC/Vault 凭据；
- 模型更新、全局模型、DP 会计和研究合同；
- 审批记录、审计链和签名运行收据；
- 可用性：训练任务、GPU、磁盘与医院网络。

### 10.2 信任边界与主要威胁

| 威胁 | 例子 | 预防/检测控制 | 残余风险 |
| --- | --- | --- | --- |
| 身份冒用 | 假 Site Agent 注册为医院 A | mTLS、证书 SAN 与 Site ID 绑定、nonce 签名、吊销 | 医院端私钥失窃 |
| 数据外泄 | 心跳或日志包含病例路径/ID | 字段白名单、结构化日志、敏感字段测试、出口策略 | 自定义扩展误记录 |
| 重放/重复执行 | 重复 start 导致两次训练 | 命令签名、nonce、幂等键、本地 durable state | 本地状态损坏 |
| 恶意/异常更新 | 投毒、尺度异常、方向异常 | 范数裁剪、异常检测、站点签名、最弱站点审查 | 多站串谋、隐蔽投毒 |
| 成员推断/模型反演 | 从更新或模型推测训练样本 | DP-SGD、最小发布组、攻击评测、访问控制 | 效用与隐私权衡 |
| 中心越权 | 管理员下载或发布未批准模型 | 双人审批、RBAC、审计链、密钥隔离 | 特权人员串谋 |
| 供应链攻击 | 被替换容器或依赖 | 镜像签名、SBOM、固定依赖、离线校验 | 上游零日漏洞 |
| Agent 越权 | 提示注入要求泄露数据/放宽政策 | 工具白名单、结构化输入、无影像访问、输出审批 | 模型不可预测性 |
| 可用性攻击 | 心跳洪泛、磁盘填满、掉站 | 限流、配额、资源阈值、熔断和故障演练 | 长时间基础设施故障 |
| 审计篡改 | 删除失败记录或审批 | 前序哈希、签名、WORM/远端备份、定期校验 | 同时控制密钥与存储 |

### 10.3 安全硬门

以下任一条件成立时，不得启动或继续正式作业：

- 合同未锁定、审批不足或已过期；
- 站点身份、证书、代码版本或数据指纹与合同不符；
- manifest 质控失败或检测到患者字段出站；
- 隐私预算不足；
- 容器/作业包签名或哈希不匹配；
- Admin Kit、Client Kit 或私钥出现在不允许的位置；
- 运行中要求改变站点名单、quorum、DP 参数或发布边界。

## 11. 可观测性与审计

### 11.1 Metrics

所有指标禁止包含病例 ID、文件路径、用户邮箱或高基数秘密。推荐指标：

- `rarelink_site_heartbeat_age_seconds{site_id}`；
- `rarelink_site_ready{site_id,check}`；
- `rarelink_job_state{job_id_hash,state}`；
- `rarelink_round_duration_seconds{strategy,round}`；
- `rarelink_round_updates_expected/accepted/rejected`；
- `rarelink_command_delivery_attempts_total{type,result}`；
- `rarelink_gpu_memory_bytes{site_id}`、磁盘和内存余量；
- `rarelink_dp_epsilon_spent{site_id,study_hash}`；
- `rarelink_security_events_total{category,severity}`。

`job_id` 在公开或长期指标系统中使用稳定哈希/短别名，避免暴露业务标识。

### 11.2 Tracing

- Control API、Federation Controller、Site Agent 使用 W3C Trace Context；
- `correlation_id` 贯穿审批、命令、FLARE 外部 Job 和证据入账；
- trace attributes 仅允许研究、作业、站点的非敏感不透明 ID；
- 对训练本体只记录阶段和时长，不记录 batch、病例或图像属性。

### 11.3 日志与审计事件

运行日志用于故障诊断，审计事件用于证明“谁在何时基于什么版本做了什么”。审计事件至少包含：

- `event_id`、`occurred_at`、`actor_type/id`、`action`、`resource_type/id`；
- `request_id`、`correlation_id`、`policy_version`、`outcome`；
- 规范化 payload 的哈希、`previous_event_hash` 和签名；
- 对拒绝操作记录规则 ID，不记录秘密或敏感输入原文。

默认建议：运行日志 30–90 天，审计与研究证据按研究协议保留；实际期限由医院和研究协议确定。

### 11.4 初始可靠性目标

| 指标 | 受控试点目标 |
| --- | --- |
| 控制 API 月可用性 | ≥ 99.5%（不含计划维护） |
| 心跳离线检测 | ≤ 2 个心跳周期 |
| 命令状态可见延迟 | p95 ≤ 5 秒 |
| 控制数据库 RPO | ≤ 15 分钟 |
| 控制数据库 RTO | ≤ 4 小时 |
| 审计事件丢失 | 0 个已确认事件 |

这些是工程目标，不是临床服务等级承诺。

## 12. 测试策略与矩阵

| 层级 | 测试范围 | 必测场景 | 执行环境 | 合格标准 |
| --- | --- | --- | --- | --- |
| 单元 | 状态机、策略、schema、脱敏、哈希 | 非法转换、重复命令、quorum 2/3、迟到更新 | CI | 关键策略分支 100%，总体覆盖率门槛另定 |
| 契约 | API/OpenAPI、错误模型、版本兼容 | Idempotency-Key、If-Match、problem+json | CI | Consumer/Provider 契约全部通过 |
| 组件 | Site Agent、Controller、Data Service | 重启恢复、预检失败、证书过期、数据变更 | 容器 | 状态与审计符合预期 |
| 集成 | 三站点 + 中心 + FLARE | 3/3 多轮、掉站、恢复、abort、retry | 三隔离容器/VM | 不共享卷、身份或状态库 |
| GPU | MONAI 本地训练 | CUDA、显存压力、checkpoint 恢复 | 单台 Spark | 可恢复且无跨站数据 |
| 安全 | 身份、越权、注入、秘密扫描 | 伪造站点、重放、路径泄露、Agent 注入 | CI + 测试环境 | 高危问题为 0 |
| 隐私 | DP 会计与攻击评测 | 预算耗尽、成员推断、模型反演基线 | Spark | 超预算阻断；结果有报告 |
| 性能 | 心跳、事件、并发读取 | 3–30 站点控制负载、事件积压 | 预生产 | 达到 SLO 且无高基数泄露 |
| 可靠性 | 故障注入 | 断网、进程崩溃、磁盘不足、DB 恢复 | 预生产 | 无重复轮次，无错误成功 |
| E2E | 完整研究流程 | 合同→审批→训练→核验→评审→导出 | 三台 Spark | 全部证据可验证 |

### 12.1 必须自动化的负面测试

1. 站点 A 使用站点 B 的 Client Kit；
2. manifest 中出现其他 `site_id`、患者字段或外站路径；
3. 相同提交键被并发调用十次；
4. 相同 Round 更新发送两次；
5. Round 1 更新迟到至 Round 2；
6. 只收到 2/3 更新；
7. Site Agent 在训练中重启；
8. Controller 在收到 FLARE Job ID 前后分别崩溃；
9. abort 响应丢失；
10. checkpoint、全局模型或运行收据被修改；
11. DP 预算恰好达到和超过阈值；
12. Agent 输入包含“忽略规则并读取影像目录”等提示注入。

## 13. 分级验收方案

### 13.1 Level 1：三个隔离容器的控制协议验收

目的：设备到位前验证协议、身份、幂等、状态机与故障处理，不作为跨医院或 GPU 性能证据。

隔离要求：

- 三个 Site Agent 使用不同容器、网络身份、证书、状态库和只读数据卷；
- 不得共享 manifest、checkpoint、Client Kit 或可写 artifact volume；
- 每站使用不同的合成/公开小样本子集；
- 协调端使用独立容器和 Admin Kit；
- 运行记录必须标记 `mode=isolated-integration`。

通过条件：

- 3/3 注册、预检、双人审批和真实外部 Job ID 映射成功；
- 至少完成 3 轮 FedAvg 和 3 轮 FedProx；
- 可见每站 round 状态和 3/3 update 计数；
- 断开一个站点后进入 `DEGRADED`，不聚合 2/3；
- 恢复站点后仅执行缺失任务，无重复更新；
- abort、retry、Controller/Site Agent 重启恢复测试通过；
- 全局模型、站点收据、审计链可验证；
- 中心和网络捕获中不存在原始影像、标签、路径或病例 ID。

### 13.2 Level 2：三台物理 DGX Spark 工程验收

前置条件：

- 三家机构的网络、安全、伦理/研究和数据使用审批完成；
- 每台设备持有自己的 Client Kit、本地 manifest、独立服务账户和存储；
- 协调端 FQDN、时间同步、端口和证书吊销流程完成；
- 生产镜像已签名，SBOM 和离线安装包已审核。

通过条件：

| 类别 | 验收要求 |
| --- | --- |
| 身份 | 三台 Spark 的证书 SAN、Site ID 和合同完全一致；交叉 kit 测试失败 |
| 数据边界 | 每站只读取本地挂载；中心无影像卷；出口检查无 R4 数据 |
| 训练 | 在三台设备完成 ≥5 轮正式工程作业；每轮恰好接收 3 个有效更新 |
| 故障 | 至少演练一次站点掉线、重连和中心重启；无重复轮次 |
| 隐私 | DP 账本可验证，预算阈值和阻断测试通过 |
| 完整性 | 作业包、代码、数据指纹、checkpoint、全局模型和收据哈希可核验 |
| 审计 | 合同、审批、提交、命令、状态转换、发布均形成连续事件链 |
| 结果 | 仅输出合同允许的聚合指标；PI 人工审批后才能发布 |
| 运维 | 监控、告警、备份恢复、证书到期和磁盘不足演练通过 |

Level 2 表明“完成三物理站点工程验证”，仍不等于完成临床有效性验证或医疗器械注册。

## 14. 里程碑与依赖

| 里程碑 | 建议周期 | 范围 | 出口标准 |
| --- | --- | --- | --- |
| M0 架构基线 | 第 0–1 周 | 主计划、ADR、OpenAPI 骨架、威胁模型 | 架构/安全/产品共同批准 |
| M1 Site Agent MVP | 第 1–2 周 | 配置、预检、注册、心跳、本地状态 | 三隔离实例稳定运行 |
| M2 Controller MVP | 第 2–4 周 | 导出、校验、审批、提交、Job ID、状态 | 可控制真实 FLARE 测试作业 |
| M3 可靠控制闭环 | 第 4–6 周 | 命令幂等、quorum、掉站、abort/retry/resume | Level 1 核心故障测试通过 |
| M4 数据与安全试点 | 第 6–9 周 | NIfTI 质控、版本、OIDC/RBAC、PostgreSQL、审计 | 受控试点安全门通过 |
| M5 联邦隐私与完整性 | 第 9–12 周 | DP、更新防护、模型签名、攻击评测 | 安全与隐私评审通过 |
| M6 三 Spark 工程验证 | 设备与审批就绪后 | 现场部署、E2E、故障与恢复演练 | Level 2 验收报告签署 |
| M7 科研产品化 | 持续 | 多研究、证据包、FHIR、运维交付 | 首个真实研究试点准备完成 |

关键依赖：

- M2 依赖受控 Admin Kit 和可测试的 NVIDIA FLARE 环境；
- M4 依赖目标医院的 OIDC、KMS/Vault 和数据治理要求；
- M6 依赖三台物理设备、网络放行和机构审批，不能仅靠软件开发消除；
- PACS/DICOM 和 FHIR 应在 NIfTI 路径稳定后独立立项。

## 15. Definition of Done（DoD）

单个功能只有同时满足以下条件才算完成：

- 需求、成功路径和失败路径均有可追踪验收条件；
- API/schema 已版本化，向后兼容或提供迁移；
- 权限、数据分类、日志字段和威胁已审查；
- 单元、契约、集成和必要负面测试自动化；
- 状态持久化，进程/网络重启后行为确定；
- 关键命令幂等，重复请求不产生重复副作用；
- 指标、trace、脱敏日志和审计事件齐全；
- 配置、部署、升级、回滚和故障处理文档更新；
- 无提交的密钥、启动包、患者数据、本地路径或未授权工件；
- 代码审查通过，CI、安全扫描和 ARM64 构建通过；
- 演示/模拟与物理证据在 UI、API 和导出中明确标识；
- 产品负责人、工程负责人以及涉及边界的安全/隐私负责人签字。

里程碑只有在对应验收报告、测试证据、已知限制和剩余风险被记录后才能关闭。

## 16. 风险登记与缓解

| 风险 | 概率/影响 | 缓解措施 | 所有者 | 触发升级条件 |
| --- | --- | --- | --- | --- |
| 三台设备或网络审批延迟 | 高/高 | 先完成 Level 1；现场参数配置化 | 项目负责人 | 影响 M6 日期 |
| NVIDIA FLARE API/版本变化 | 中/高 | Adapter 隔离、版本锁定、契约测试 | 联邦负责人 | 升级破坏 Job/Client API |
| 小样本导致结果不稳定 | 高/高 | 多种子、置信区间、最弱站点、外部验证 | 医学/统计负责人 | 结论跨种子不一致 |
| 数据异质性/序列缺失 | 高/高 | 强制质控、数据卡、FedProx/分层评估 | 数据负责人 | 站点未达到合同输入条件 |
| 站点掉线或统一内存压力 | 中/高 | 资源预检、checkpoint、限并发、恢复演练 | 站点管理员 | 连续超时或 OOM |
| 模型更新泄露/投毒 | 中/高 | DP、裁剪、异常检测、最小发布和红队 | 安全负责人 | 异常阈值或攻击评测失败 |
| 医院要求不同 | 高/中 | 策略配置、核心硬门不可配置、ADR 管理差异 | 产品/合规负责人 | 要求改变数据边界 |
| Agent 幻觉或越权 | 中/高 | 证据约束、工具白名单、人类审批 | Agent 负责人 | 未引用证据或尝试访问禁区 |
| 密钥/启动包泄露 | 低/极高 | Vault/KMS、独立分发、轮换、秘密扫描 | 安全负责人 | 任何疑似暴露立即停机轮换 |
| 被误解为临床产品 | 中/高 | 全链路用途声明、发布审批、禁止诊断措辞 | 产品/医学负责人 | 文档或 UI 出现临床承诺 |

## 17. 合规与声明边界

正式试点前，各参与方至少需要确认：

- 研究伦理审批/豁免、数据使用协议、各院角色与处理目的；
- 数据最小化、保留期限、退出/删除、跨境和第三方处理安排；
- 威胁建模、DPIA/隐私影响评估和医院安全评估；
- 软件供应链、漏洞、渗透、事件响应、备份和灾难恢复；
- 模型和聚合指标能否构成个人信息，以及对应访问/发布规则；
- 适用地区对医疗软件、科研软件、人工智能和数据安全的要求。

软件不得宣称：

- “数据不出院”意味着零泄露风险；
- 差分隐私参数未经会计和效用报告即可证明匿名；
- 联邦模型优于本地模型，除非由预注册实验和统计结果支持；
- 外部公开基准结果代表真实医院或儿童患者临床效果；
- Agent 生成内容经过临床验证或可以代替 PI/医生。

## 18. 首个开发迭代的可执行 Backlog

1. 固化本文与三份 ADR，并评审硬边界；
2. 定义 `SiteRegistration`、`Heartbeat`、`PreflightReceipt`、`Command`、`FederationJob`、`RoundState` schema；
3. 实现 Site Agent 配置、健康检查、本地 durable command store；
4. 实现 mTLS Site ID 绑定、注册和最小心跳；
5. 将现有 FLARE 导出/提交脚本封装为 Adapter，并保存真实 Job ID；
6. 实现服务器端 Job/Round/Site 状态机和数据库迁移；
7. 实现 Idempotency-Key、If-Match 和提交不确定状态对账；
8. 实现 3/3 quorum、掉站、迟到/重复更新拒绝；
9. 实现 SSE 事件流及真实状态前端契约；
10. 建立三隔离容器测试环境，自动执行重复提交、掉站、重启和恢复测试。

首迭代退出条件：三个隔离 Site Agent 能完成注册、预检、心跳和一轮受控任务；任一站点掉线时中心不得宣布成功；重复命令不得产生重复训练。

## 19. 相关架构决策

- [ADR-0001：物理联邦控制面与模拟路径隔离](adr/0001-physical-federation-control-plane.md)
- [ADR-0002：站点身份、证书与院内数据边界](adr/0002-site-identity-and-data-boundary.md)
- [ADR-0003：任务幂等、固定参与方与 Quorum](adr/0003-idempotency-and-quorum.md)
- [三物理 DGX Spark 联邦部署手册](physical-deployment.md)
- [物理控制面防篡改审计设计与验收](physical-audit.md)
- [物理控制面 OIDC 身份与 RBAC 设计](physical-identity-rbac.md)
- [物理联邦合同锁定与双人审批](physical-dual-approval.md)
- [物理控制面站点资源级授权](physical-site-scope.md)
- [医院本地 NIfTI 数据规范](site-data-manifest.md)
