# RareLink 物理联邦合同锁定与双人审批

**状态：** P1 Increment Implemented  
**范围：** `physical` 模式的联邦作业合同、第二审批、提交、重试和恢复  
**实现：** `rarelink/services/physical_approval.py`、`PhysicalJobApprovalRecord`、物理控制 API  
**定位：** 持久化合同双人审批；尚不等于所有高风险动作均已双人批准

> 双人审批保证两个不同的已验证 OIDC 主体对同一份锁定合同分别承担“提议”和“第二复核”责任。它不能证明审批人实际完成了医学、伦理或安全审查，也不替代 IRB、数据使用协议、医院变更管理和结果发布审批。

## 1. 解决的问题

物理联邦作业包含站点、数据版本、策略、轮数和 quorum 等安全关键参数。如果第二审批只确认一个可变数据库行，审批后修改轮数、替换数据指纹或减少参与站点就可能绕过原意。若提议人与审批人是同一 OIDC `sub`，多角色也不能形成职责分离。

本增量因此实现：

- 对严格的 contract v1 规范化投影计算 SHA-256；
- 创建作业时锁定合同摘要和提议人最小身份；
- 要求不同 `sub` 的授权主体提交固定 attestation；
- 将第二审批持久化并绑定到合同摘要；
- 持久化审批有效期，默认 24 小时，可配置 5 分钟至 7 天；
- 允许获授权主体以独立、不可变记录撤销尚未执行的第二审批；
- submit、retry、resume 前重新计算摘要并核对审批记录与有效期；
- 公开作业视图只展示审批计数、状态和合同摘要，不展示审批主体。

## 2. Contract v1 规范化摘要

### 2.1 覆盖字段

`rarelink-physical-contract-v1` 包含：

| 字段 | 规范化规则 |
| --- | --- |
| `study_id` | 可为空；非空时 trim，最长 255 字符 |
| `strategy` | 小写；只允许 `fedavg` 或 `fedprox` |
| `bundle_sha256` | 64 位小写 SHA-256 |
| `expected_sites` | 必须恰好三个唯一 Site ID，并按字典序排序 |
| `dataset_fingerprints` | key 必须与排序后三站完全一致；每站一个 64 位小写 SHA-256 |
| `rounds` | 正整数；来自 job 的 `rounds`/`total_rounds` |
| `local_epochs` | 正整数 |
| `quorum` | 必须为 3，即固定 3-of-3 |

合同不会包含患者 ID、manifest 原文、本地路径、Admin Kit、submit token、审批 note 或 OIDC token。

### 2.2 Canonical JSON

```json
{
  "schema_version": "rarelink-physical-contract-v1",
  "study_id": "opaque-study-id-or-null",
  "strategy": "fedavg",
  "bundle_sha256": "…",
  "expected_sites": ["hospital-a", "hospital-b", "hospital-c"],
  "dataset_fingerprints": {
    "hospital-a": "…",
    "hospital-b": "…",
    "hospital-c": "…"
  },
  "rounds": 5,
  "local_epochs": 1,
  "quorum": 3
}
```

JSON 使用 UTF-8、object key 排序、紧凑 separators；最终：

```text
contract_sha256 = SHA256(canonical_json(contract_v1))
```

站点输入顺序和 fingerprint object 的原始 key 顺序不会改变摘要；任何受覆盖语义变化都会产生新摘要。比较使用 constant-time digest comparison。

SHA-256 是完整性绑定，不是签名。可信性来自 OIDC 主体、RBAC、持久化审批、审计链和数据库边界的组合。

## 3. 提议人与第二审批人

### 3.1 提议人

在 `physical` 模式创建作业时：

1. 请求主体必须通过 OIDC；
2. 必须拥有 `physical.contract.create`；
3. 系统从已验证 Principal 保存 `proposed_by=sub` 和角色集合；
4. 计算并保存 `contract_sha256`；
5. 作业进入 `APPROVAL_PENDING`；
6. `job.contract-created` 审计事件记录合同摘要和非敏感合同字段。

请求 body 中的显示名或 `approved_by` 字段不是身份来源；OIDC `sub` 才是权威主体。

### 3.2 第二审批人

第二审批人必须：

- 通过 OIDC；
- 拥有 `physical.contract.approve`；
- `sub` 与提议人不同；
- 审批时合同摘要与创建时完全一致；
- 提交固定 attestation：

```text
CONTRACT_DATA_AND_SECURITY_REVIEWED
```

具有多个角色的同一 `sub` 仍是同一个人，不能自批。允许承担第二审批的角色由 RBAC 矩阵决定，当前包括具备 `contract.approve` 的 research lead、data steward、reviewer 和 security admin。

## 4. 第二审批 API

### 4.1 请求

```http
POST /api/physical/jobs/{job_id}:approve
Authorization: Bearer <OIDC JWT>
Content-Type: application/json
```

```json
{
  "attestation": "CONTRACT_DATA_AND_SECURITY_REVIEWED",
  "note": "内部复核说明，可为空"
}
```

`attestation` 是 schema 固定 literal，不能由客户端改成弱化表述。`note` 最长 1000 字符，不作为合同字段。

### 4.2 成功语义

成功后：

- 创建一条 `PhysicalJobApprovalRecord`；
- 一个 job 只允许一条 second approval 记录；
- 保存 `contract_sha256`、approver `sub`、审批时角色、固定 attestation；
- `note` 只保存 trim 后内容的 SHA-256；
- job 保存第二审批主体、note SHA-256、批准时间和到期时间；
- approval record 与 job 保存完全相同的 `expires_at`；两者不一致时失败关闭；
- 审计追加 `job.contract-second-approved`。

审批 note 明文不保存在第二审批记录、job 的第二审批字段或审计事件中。摘要只能用于一致性对照，不能恢复 note；需要保留审批说明原文时，应由医院批准的文档系统单独管理。

### 4.3 幂等与竞争

若已存在审批：

- 同一 approver `sub`、同一合同摘要、同一固定 attestation：返回当前 job view，HTTP 200，不追加第二条事件；
- 不同 approver、不同合同摘要或不同 attestation：HTTP 409；
- 即使重试 note 文本不同，只要上述三项相同仍视为幂等，第一次 note 摘要保持不变。

数据库对 `approval.job_id` 设置唯一约束。并发审批中只有一个可成功提交；唯一约束冲突回滚并返回 409，而不是覆盖已有审批。

### 4.4 失败场景

| 场景 | 结果 |
| --- | --- |
| job 不存在 | 404 |
| job 不在 `APPROVAL_PENDING` | 409 |
| 旧 job 无 `contract_sha256` | 409，必须重建 |
| 提议人与审批人 `sub` 相同 | 409 |
| 提议人无 create 或审批人无 approve | 403 |
| 合同字段在审批前已变化 | 409，必须新建/重批 |
| 已有竞争审批 | 409 |
| 审批缺少有效期、记录与 job 到期时间不一致或已过期 | 409，必须重建并重新审批 |
| 已存在撤销记录 | 409，合同必须重建；历史审批和撤销均不覆盖 |
| 固定 attestation 不匹配 | 422 schema error |

### 4.5 审批撤销

`POST /api/physical/jobs/{job_id}:revoke-approval` 要求
`physical.contract.revoke`、完整三站 scope 和固定 attestation
`REVOKE_PHYSICAL_CONTRACT_APPROVAL`。当前仅 `research_lead`、`data_steward`
和 `security_admin` 拥有该权限。

撤销只允许发生在 `APPROVAL_PENDING`；作业已提交或运行时必须使用 abort，避免把
“撤销批准”误写成“训练已停止”。系统创建唯一的
`PhysicalJobApprovalRevocation`，保存合同/审批引用、撤销主体、固定 attestation、
理由 SHA-256 和时间。理由明文不进入数据库、响应或审计。重复的同主体同
attestation 请求幂等返回；不同撤销竞争返回 409。

## 5. 提交、重试与恢复硬门

`physical` 模式下，submit、retry 和 resume 在调用 NVIDIA FLARE 前都会：

1. 重新计算 contract v1 SHA-256；
2. 与锁定 `contract_sha256` 比较；
3. 查询持久化 second approval；
4. 检查 approval 的摘要等于当前合同摘要；
5. 检查 approval approver 等于 job 的第二审批主体；
6. 检查第二审批主体与提议人不同。
7. 检查 approval 与 job 的到期时间一致且晚于当前 UTC 时间。
8. 确认不存在 revocation 记录，且 job 未绑定撤销 ID。

任一步失败均返回 409，不进入 FLARE。submit 还会重新检查三站 READY、心跳新鲜和数据指纹未变化。数据版本变化要求创建并重新审批新合同；旧合同不能通过 retry/resume 复活。

这实现的是“合同双人审批”。当前 submit/retry/resume 操作本身仍由一个具有对应 action permission 的主体发起，并没有第二个独立的“执行批准”记录；双人提交、双人恢复仍是生产待办。

提议人、第二审批人和 submit/retry/resume 执行者还必须分别通过同一合同三站的
OIDC `site_ids` 子集检查；任一主体缺少一个目标站点都会在审批记录或 NVIDIA
FLARE 调用前返回不枚举缺失站点的 403。规则见
[站点资源级授权](physical-site-scope.md)。

## 6. 公开视图与审计边界

### 6.1 公开 job view

公开作业视图与审批有关的字段只有：

- `contract_sha256`；
- `approval_count`；
- `approval_required`；
- `approval_state`；
- `approval_valid`；
- `approval_expires_at`。

`physical` 中：

- 仅提议时：`1/2`、`SECOND_APPROVAL_PENDING`；
- 第二审批后：`2/2`、`SECOND_APPROVAL_RECORDED`。
- 第二审批过期：历史计数仍为 `2/2`，但状态为 `SECOND_APPROVAL_EXPIRED`，
  `approval_valid=false`，不能提交、重试或恢复。
- 第二审批撤销：历史计数仍保留，状态为 `SECOND_APPROVAL_REVOKED`，
  `approval_valid=false` 并显示撤销时间。

视图不返回 `proposed_by`、`second_approved_by`、审批角色、审批 note 或 note SHA-256。作业视图仍会按既有数据边界返回策略、轮次、站点和数据指纹等运行元数据；是否公开这些元数据由部署网关策略决定。

### 6.2 审计事件

受保护审计链记录：

```text
action = job.contract-second-approved
actor = verified second approver sub
payload = approval_id, contract_sha256, fixed attestation, approval_count=2, expires_at
```

撤销另记 `job.contract-approval-revoked`，包含 approval/revocation ID、合同摘要、
固定 attestation 和撤销时间；不包含理由明文或其摘要。

事件不包含：

- 审批 note 或 note SHA-256；
- OIDC token/raw claims；
- submit token；
- 患者数据、manifest 或本地路径。

actor 仅通过受 RBAC 保护的事件 API可见，公开审计摘要不显示主体。

## 7. Isolated integration 兼容边界

`isolated-integration` 保留 legacy 单请求路径，用于设备到位前的控制协议测试：

- `approval_required=1`；
- `approval_state=LEGACY_SINGLE_REQUEST`；
- 不要求独立 second approval；
- legacy operator 映射为测试专用全角色主体。

该路径不算双人审批证据，不能用于真实医院或 `physical` 声明。测试/演示材料必须同时展示 deployment mode 与 approval state，避免把 legacy 单请求误写为职责分离。

## 8. 测试与验收

自动测试至少覆盖：

- 站点输入顺序不影响 canonical SHA-256；
- study/strategy/bundle/任一站点 fingerprint/rounds/local epochs/quorum 的变化改变摘要；
- 非三站、非 3/3、非法摘要、未知策略失败；
- 提议人与第二审批人不同且权限正确；
- 同主体多角色自批失败；
- 固定 attestation schema；
- note 只保存 SHA-256，明文不进数据库响应和审计；
- 同审批幂等不重复写事件；
- 不同审批竞争返回 409；
- 不同审批竞争返回 409；真实并发冲突仍需 PostgreSQL 现场演练；
- submit 前缺审批、合同变化、数据变化均失败；
- submit/retry/resume 重新核验；
- 缺失、篡改和过期的审批有效期在 NVFLARE 调用前失败；
- 撤销权限、幂等、竞争、理由明文边界和执行阻断；
- job view 不泄露主体；
- isolated integration 明确显示 legacy single request。

```bash
pytest -q \
  tests/test_physical_approval.py \
  tests/test_physical_dual_approval_api.py \
  tests/test_physical_rbac.py
```

当前全量回归基线为 **221 项测试通过**；审批子集不能替代全仓回归。

物理现场还需验证：

- 两个真实 IdP 用户分别提议和批准；
- 账户禁用或角色撤销后的行为；
- 合同修改后审批失效；
- 站点数据版本变化后不可提交/恢复；
- 并发审批与数据库故障恢复；
- 审计链、公开视图和日志中无 note/token；
- 三台 Spark 只接收与已批准摘要一致的任务。

## 9. 当前局限与下一步

| 当前局限 | 影响 | 生产升级 |
| --- | --- | --- |
| 无替补审批人流程 | 人员离职/停权后缺少治理路径 | replacement workflow，不覆盖历史记录 |
| submit/retry/resume 无双人执行审批 | 合同虽双审，执行动作仍是单主体 | 高风险 action approval/intent token |
| SQLite 并发能力有限 | 多 worker 依赖唯一约束兜底，串行语义不足 | PostgreSQL 事务、行锁/序列化和重试 |
| 读取与跨组织 scope 尚不完整 | 控制操作已要求三站子集，但列表/audit 和组织/研究维度未覆盖 | 读取过滤、组织/研究 policy、受治理的协调方 scope |
| 无审批理由原文治理 | 只保存摘要，无法在 RareLink 内复核原文 | 受控文档系统引用和签名摘要 |
| 无外部签名/公证 | 数据库和应用密钥同时失陷时保护有限 | HSM/非对称签名、WORM 和外部锚定 |

## 10. 相关文档

- [物理控制面 OIDC 身份与 RBAC](physical-identity-rbac.md)
- [物理控制面防篡改审计](physical-audit.md)
- [三物理 DGX Spark 联邦部署](physical-deployment.md)
- [正式工程开发计划](engineering-development-plan.md)
- [物理控制面站点资源级授权](physical-site-scope.md)
