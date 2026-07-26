# RareLink 研究运营平面

**文档状态：** v1 实现说明

**适用范围：** 多研究、多站点、模型版本和签名研究证据的正式生命周期管理

**安全定位：** 控制与治理元数据平面；不保存患者影像、病例标识、本地路径、模型二进制或签名私钥

## 1. 为什么需要研究运营平面

联邦训练能够解决“原始数据不集中”的一部分问题，但不能独自回答：

- 一个医院当前是否仍被授权参与某项研究；
- 当前模型由哪一份合同、哪一个外部 NVIDIA FLARE Job 和哪一份证据包产生；
- 证据是否达到三物理站点或医院生产级别；
- 谁完成了统计、安全、证据和发布审批；
- 某份证据被撤销后，哪些已发布模型必须同时失效；
- 同一套平台如何并行管理多个疾病、研究和模型版本。

RareLink 研究运营平面将这些关系变为受约束的数据模型和失败关闭的状态机，使
“一次联邦实验”可以进入长期可运营、可查询、可撤销的科研治理流程。

## 2. 核心对象

| 对象 | 作用 | 明确不保存 |
| --- | --- | --- |
| `Study` | 研究名称、组织、创建者、参与站点和研究状态 | 患者名单、病例字段、原始影像 |
| `StudySiteMembership` | 站点邀请、准入、暂停和退出，以及 DUA/证书/数据指纹门 | 文件名、本地路径、病例 ID、证书私钥 |
| `ModelVersion` | 模型名称、语义版本、工件摘要、来源 Job、指标和发布状态 | 模型二进制、训练样本、签名私钥 |
| `EvidencePackageRecord` | 证据包、Manifest、模型摘要和治理门状态 | 证据 ZIP 本体、签名明文、患者数据 |

所有对外视图都明确返回 `contains_patient_data=false`，且只输出签名是否存在和
签名密钥指纹，不输出签名值或私钥。

## 3. 四级证据模型

| 等级 | 定义 | 能否正式发布模型/证据 |
| --- | --- | --- |
| `L1_CODE` | 代码实现与单元测试 | 否 |
| `L2_ISOLATED` | 独立进程/容器的隔离集成 | 否 |
| `L3_PHYSICAL` | 三台独立物理设备与正式联邦身份完成演练 | 是，需全部治理门通过 |
| `L4_HOSPITAL` | 医院身份、数据授权、安全与科研治理正式批准 | 是，需全部治理门通过 |

系统拒绝把单机三个逻辑站点、Fake CLI、SimEnv 或合成数据注册成可发布的
`L3_PHYSICAL` / `L4_HOSPITAL` 证据。等级来自受控部署和验收流程，而不是页面选项。

## 4. 生命周期与失败关闭条件

### 4.1 站点成员

```text
INVITED → ACTIVE → PAUSED → ACTIVE
    └────────────→ WITHDRAWN
ACTIVE / PAUSED ─→ WITHDRAWN
```

站点只有同时具备以下条件才可进入 `ACTIVE`：

1. 数据使用协议或研究授权已批准；
2. 站点证书身份已经绑定；
3. 已提供不含病例标识和路径的数据集指纹。

退出是终态；重新加入必须建立新的成员记录和治理证据，不能悄悄恢复旧授权。

### 4.2 研究证据包

```text
REGISTERED → VERIFIED → RELEASED → REVOKED
       └──────────────→ REVOKED
```

从 `REGISTERED` 进入 `VERIFIED` 必须同时满足：

- 等级为 `L3_PHYSICAL` 或 `L4_HOSPITAL`；
- 参与站点数精确满足合同 quorum，例如 `3/3`；
- DP 隐私门、安全评测门和双人审批门全部通过；
- 扫描确认不含敏感数据；
- 证据包签名和可信密钥指纹存在；
- 注册人与验证人不是同一主体。

从 `VERIFIED` 进入 `RELEASED` 时，验证人与发布批准人也必须不同。

### 4.3 模型版本

```text
CANDIDATE
  → STATISTICAL_REVIEW
  → SECURITY_REVIEW
  → APPROVED
  → RELEASED
  → REVOKED
```

- 进入安全评审前必须有结构化统计指标；
- 批准模型必须绑定同一研究中已验证或已发布的证据包；
- 模型摘要必须与证据包记录的模型摘要完全一致；
- 模型与证据的验证等级必须一致；
- 模型创建者不能批准自己的模型；
- 正式发布必须绑定已发布证据、达到 L3/L4、具有签名和可信密钥指纹；
- 模型批准人与发布人必须不同。

证据包被撤销时，所有绑定该证据的模型自动进入 `REVOKED`。这是服务层强制级联，
不是由前端提醒人工处理。

## 5. API

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/api/operations/summary` | 组织范围内研究、站点、模型、证据和待办总览 |
| `POST/GET` | `/api/studies/{study_id}/sites` | 注册和查询研究站点 |
| `POST` | `/api/studies/{study_id}/sites/{id}:transition` | 激活、暂停、恢复或退出站点 |
| `POST/GET` | `/api/studies/{study_id}/models` | 注册和查询模型版本 |
| `POST` | `/api/studies/{study_id}/models/{id}:transition` | 推进模型评审、发布或撤销 |
| `POST/GET` | `/api/studies/{study_id}/evidence-packages` | 注册和查询签名证据包 |
| `POST` | `/api/studies/{study_id}/evidence-packages/{id}:transition` | 验证、发布或撤销证据 |

物理部署模式下，这些接口沿用 RareLink 的 OIDC、RBAC 和组织范围约束。显式
`actor` 只用于隔离演示；真实模式以已校验 OIDC subject 为权威身份，不接受请求体
伪造操作者。

## 6. 前端

前端新增 `Research Operations Plane`：

- 顶部可在多个研究之间切换，不再固定读取第一项研究；
- 汇总研究数、活跃站点、模型版本、证据包和治理待办；
- 展示站点的 DUA、证书和数据指纹准入状态；
- 展示模型的状态、版本、签名、证据绑定和证据等级；
- 展示证据包的 `3/3` quorum、DP、安全、双人审批和签名状态；
- 没有 L3/L4 证据时显示诚实空态，不以 L2 或 Demo 收据补造正式发布。

## 7. 数据库与迁移

Alembic `0006_add_research_operations_registry.py`：

- 扩展 `study` 的组织、创建者、参与站点和修订字段；
- 新建 `studysitemembership`、`modelversion` 和
  `evidencepackagerecord`；
- 对站点成员、模型语义版本和证据摘要建立唯一性约束；
- 为研究、状态和来源 Job 查询建立索引；
- 提供完整 downgrade 顺序，避免外键依赖残留。

SQLite 仅用于开发和隔离验收；物理/生产模式仍要求 PostgreSQL 与 Alembic head
一致。

## 8. 自动验收

`tests/test_research_operations.py` 覆盖：

- 站点缺少 DUA/证书/数据指纹时无法激活；
- 完整证据与模型生命周期；
- 注册、验证、发布主体必须分离；
- L2 证据不能成为正式研究发布；
- 跨研究证据不能绑定模型；
- 撤销证据自动撤销关联模型；
- 组织级汇总不导出患者数据、秘密或本地路径。

全量验收还包括 Ruff、前端测试与生产构建、PostgreSQL 部署合同和 Alembic
迁移往返。

## 9. 当前边界与下一阶段

本轮完成的是可运行的 L1/L2 产品控制与治理能力。以下内容仍需要外部资产，不能由
代码仓库单独宣称完成：

- 三台独立 DGX Spark 的同一正式 NVIDIA FLARE Job；
- 医院 OIDC、CA/CRL、Vault/KMS、WORM/SIEM 和网络策略；
- 获授权真实队列上的正式 DP、隐私攻击和外部验证；
- 两位真实治理主体完成的生产审批；
- 模型与证据工件在医院对象存储中的保留、法律留置和销毁策略。

下一阶段应把物理控制器的真实外部 Job 完成事件自动送入模型候选注册表，并将已签名
Research Evidence Package v2 的离线验证结果自动登记为 `REGISTERED`；正式验证和
发布仍由不同授权主体完成。
