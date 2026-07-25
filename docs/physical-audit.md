# RareLink 物理控制面防篡改审计设计与验收

**文档状态：** P0 Pilot Implemented  
**适用范围：** `/api/physical/*` 物理联邦控制面  
**实现位置：** `rarelink/services/physical_audit.py`、`PhysicalControlEvent`、物理控制 API  
**安全定位：** 可检测篡改（tamper-evident），不是 WORM、可信时间戳或不可抵赖审计系统

> **研究用途边界：** 审计链证明的是已记录控制事件的顺序和内容完整性，不证明医学结论正确、原始数据匿名、系统从未遭入侵，也不替代医院审计平台、SIEM、WORM 存储、密钥托管和合规评估。

## 1. 目标与非目标

### 1.1 当前目标

物理控制面审计用于回答：

- 哪个逻辑主体对哪个物理站点或联邦作业执行了什么已接受操作；
- 事件发生时的作业状态、轮次、quorum、数据指纹和模型摘要是什么；
- 已持久化的历史事件是否被修改、删除、插入或重新排序；
- 当前运行使用无密钥 SHA-256 历史链，还是由托管密钥保护的 HMAC-SHA256 链；
- 前端和公开观察者能否只读取无演员、无事件明细的安全摘要；
- 授权操作员能否读取受保护事件进行工程审计。

### 1.2 非目标

当前实现不提供：

- 数据库管理员无法绕过的 WORM 或外部公证；
- 对系统未记录操作的证明；
- 用户级数字签名或法律意义上的不可抵赖性；
- 可信硬件时间戳、第三方时间戳或全局有序分布式日志；
- 患者数据匿名化、模型隐私或临床有效性保证；
- 旧 HMAC 密钥的在线 key-ring 验证和自动轮换；
- SQLite 多 worker 下严格串行的并发事件追加。

## 2. 事件模型

每条 `PhysicalControlEvent` 持久化以下字段：

| 字段 | 说明 | 数据边界 |
| --- | --- | --- |
| `event_id` | 不透明唯一事件 ID | 不由患者、路径或秘密构造 |
| `action` | 规范化动作，例如 `site.register` | 固定词汇 |
| `actor` | 站点 ID 或物理操作员标识 | 仅受保护 API 返回 |
| `resource_type` / `resource_id` | 物理站点或物理作业引用 | 不使用病例 ID |
| `outcome` | `accepted`、`failed`、`approval-pending` 等结果 | 不写原始异常 |
| `payload_json` | 经过边界检查的最小事件载荷 | 禁止患者、秘密和本地敏感路径字段 |
| `previous_hash` | 前一事件的摘要；首条为 64 个 `0` | 形成前向哈希链 |
| `event_hash` | 当前规范化事件的 SHA256/HMAC-SHA256 | 受保护 API 返回；摘要 API只返回链头 |
| `algorithm` | `SHA256` 或 `HMAC-SHA256` | 明确验证算法 |
| `key_id` | HMAC 密钥摘要的前 16 个十六进制字符 | 不是密钥，仅用于识别当前 key |
| `created_at` | UTC 时间 | 当前是应用时间，不是可信时间戳 |

当前已记录的主要成功/状态事件包括：

| 动作 | 记录时机 | 关键非敏感字段 |
| --- | --- | --- |
| `site.register` | 操作员登记预期站点 | organization、expected |
| `site.heartbeat-accepted` | 签名心跳通过 | heartbeat ID、站点状态、数据指纹、回执摘要、轮次 |
| `job.dataset-version-invalidated` | 运行绑定的数据版本变化 | 站点、旧/新指纹、错误码 |
| `job.contract-created` | 物理作业合同建立 | 策略、bundle 摘要、三站、轮次、3/3 quorum |
| `job.contract-second-approved` | 不同 OIDC 主体完成合同第二审批 | approval ID、contract SHA-256、固定 attestation、approval count |
| `job.submitted` | NVIDIA FLARE 返回真实外部 Job ID | 外部 ID、attempt、bundle 摘要 |
| `job.status-synchronized` | 控制面与 FLARE 对账 | 状态、轮次、收到的更新数、错误码 |
| `job.aborted` | FLARE 中止已确认 | 外部 ID、状态、attempt |
| `job.retried` | 受控重试已建立 | 外部 ID、状态、attempt |
| `job.resumed` | 受控恢复已建立 | 外部 ID、状态、attempt |
| `job.global-model-verified` | 完成模型哈希通过 | 文件名、模型 SHA-256、核验结论 |

当前表格不代表所有拒绝路径已经进入审计链，具体局限见第 9 节。

## 3. 规范化与链式摘要

事件在计算摘要前被编码为 UTF-8 JSON：

- 字段集合固定；
- object key 按字典序排序；
- 不写额外空格；
- 时间归一化为 UTC RFC 3339；
- payload 使用相同的递归安全检查；
- `previous_hash`、`algorithm` 和 `key_id` 本身也参与摘要。

概念计算如下：

```text
canonical_event = canonical_json(
  event_id, action, actor, resource_type, resource_id, outcome,
  payload, previous_hash, algorithm, key_id, created_at
)

SHA256 mode:
  event_hash = SHA256(canonical_event)

HMAC mode:
  event_hash = HMAC-SHA256(audit_key, canonical_event)
```

下一条事件的 `previous_hash` 等于当前 `event_hash`。验证时从固定 genesis 值开始，逐条检查：

1. payload 能被解析并通过敏感字段规则；
2. `previous_hash` 与预期链头一致；
3. 算法和 key ID 可由当前验证上下文支持；
4. 重新计算的摘要与持久化值使用 constant-time comparison 相等。

修改事件正文会使当前摘要失败；删除、插入或重排会使后续 `previous_hash` 断裂。

## 4. SHA-256 与 HMAC-SHA256 的安全语义

### 4.1 SHA-256 历史

未配置审计密钥时，事件使用 `SHA256`。它能发现偶然损坏，并能在攻击者只修改事件行而不重算整条链时发现篡改；但具有数据库写权限的攻击者可以重算后续摘要。因此 SHA-256 链不能单独对抗有意的数据库管理员篡改。

系统允许在启用 HMAC 前验证历史 SHA-256 事件，以支持试点升级；这些历史事件不会因此获得 HMAC 的安全属性。

### 4.2 HMAC-SHA256

配置 `RARELINK_AUDIT_HMAC_KEY` 后，新事件使用 HMAC-SHA256。只控制数据库、但不知道 HMAC 密钥的攻击者无法有效重算被修改的链。

`key_id = SHA256(key)[0:16]` 仅用于识别验证密钥，不泄露密钥原文。密钥必须：

- 由医院/协调方认可的密钥系统生成和托管；
- 与数据库、备份和应用日志分离；
- 不提交 Git、不进入 API、不写审计事件；
- 至少具有 32 个字符；生产环境还应保证足够随机熵，而不只满足长度；
- 限制读取主体并建立轮换、吊销、备份和灾难恢复流程。

### 4.3 物理模式密钥硬门

当 `RARELINK_PHYSICAL_MODE=physical` 时，如果 `RARELINK_AUDIT_HMAC_KEY` 少于 32 个字符，所有调用 `require_physical_enabled` 的受保护物理写操作返回 `503`。未配置物理操作员身份时，写操作同样失败关闭。

这个硬门保证正式物理模式不会继续追加无密钥 SHA-256 事件；它不检查密钥随机性，也不替代 Vault/KMS。公开只读摘要仍可用于显示已有链状态。

## 5. API 暴露边界

### 5.1 公开摘要

`GET /api/physical/audit-summary`

用于前端证据驾驶舱和只读健康观察，返回：

- `verified`、`event_count`；
- `head_event_hash`、`head_algorithm`、最后更新时间；
- `events_exported=false`、`actors_exported=false`；
- 患者、秘密、本地路径未导出的边界声明。

该接口不返回 actor、resource ID、payload、单条事件或历史链。链头摘要可用于记录某一时点的状态，但没有外部签名/公证时，公开链头本身不是不可抵赖证明。
空链返回 `verified=false`，前端显示“待核验”，避免把尚无任何控制事件误报为审计通过。

### 5.2 受保护事件 API

`GET /api/physical/events`

该接口需要 `X-RareLink-Operator-Token`，并受物理控制面启用状态约束。它返回：

- 整链验证结论和总事件数；
- 最近最多 200 条事件；
- actor、resource、payload、previous/event hash、algorithm、key ID 和时间；
- `truncated` 标记，防止把最近 200 条误认为完整导出。

P0 的操作员 token 是过渡身份，不是医院级 OIDC/RBAC。生产阶段必须迁移到医院统一身份、细粒度角色、短期会话和双人复核。

### 5.3 API 使用原则

- 公共 UI 只调用摘要接口；
- 事件接口只用于受控运维/安全审查，不嵌入公开页面；
- 不把 operator token 写入浏览器静态资源、URL、截图或日志；
- 不把 `/events` 响应作为长期审计归档；归档应使用专用、签名、分页和访问审计流程；
- `verified=false` 必须触发告警并阻断正式结果发布。

## 6. 数据边界

物理审计 payload 对以下递归字段名失败关闭：

`admin_kit`、`api_key`、`case_id`、`dataset_manifest`、`job_directory`、`label`、`model_path`、`password`、`patient_id`、`patient_name`、`private_key`、`secret`、`submit_token`。

设计要求：

- 记录摘要、状态码、轮次和不透明 ID，不记录原始值；
- 本地模型只记录安全文件名和核验 SHA-256，不公开协调端绝对路径；
- submit token 只保存不可逆摘要，事件不保存 token；
- 第二审批事件只记录 approval ID、合同摘要、固定 attestation 和审批计数，
  不记录审批 note 明文或 note SHA-256；
- Site Agent 心跳只包含患者信息为零的资源、数据指纹和任务状态；
- 原始影像、标签、病例级指标、manifest、Client/Admin Kit 和私钥永不进入审计表；
- Agent Gateway 不读取受保护事件 API。

字段名拒绝是纵深防御，不是完整 DLP：调用方仍必须使用固定事件 schema，日志/trace/导出还需独立敏感信息测试。

## 7. 运维核验

### 7.1 配置前检查

1. 确认物理模式、操作员身份和站点 HMAC 分别使用独立秘密；
2. 从密钥系统注入 `RARELINK_AUDIT_HMAC_KEY`，不写入镜像或仓库；
3. 核对应用数据库备份和审计密钥备份由不同权限控制；
4. 确认公开代理只暴露摘要接口，受保护事件接口需要内部认证；
5. 启动前运行配置测试和秘密扫描。

### 7.2 正常运行检查

```bash
curl --fail http://127.0.0.1:9000/api/physical/audit-summary
```

预期：

- `verified=true`；
- 物理模式新增事件的 `head_algorithm=HMAC-SHA256`；
- `events_exported=false`、`actors_exported=false`；
- 响应不包含 actor、payload、路径或 token。

授权人员可在受控终端请求事件 API。token 应通过环境或安全代理传递，不应进入 shell 历史；本文故意不提供含明文 token 的命令示例。

### 7.3 异常处理

若 `verified=false`：

1. 暂停正式作业提交、模型发布和研究报告导出；
2. 保全数据库、应用版本、密钥 ID 和最小必要运行日志；
3. 不直接“修复”事件行或重建链；
4. 与最近一次外部保存的链头和备份对比，确定修改/删除范围；
5. 按医院安全事件流程处理；
6. 只有经书面审查和重新建立可信基线后才恢复。

## 8. 自动与现场验收

| 验收项 | 方法 | 通过条件 |
| --- | --- | --- |
| HMAC 链 | 追加两条事件并完整验证 | `verified=true`，后项指向前项 |
| 正文篡改 | 修改历史 payload | `verified=false` |
| 顺序/删除篡改 | 删除或交换事件 | 链验证失败 |
| 敏感字段 | payload 嵌套加入禁用字段 | 追加操作失败 |
| SHA 历史升级 | SHA 事件后启用 HMAC | 当前 key 可验证混合历史 |
| 物理硬门 | physical 模式不配置/短 key | 受保护物理写操作返回 503 |
| 摘要最小化 | 匿名读取 summary | 无 actor、payload、路径、秘密 |
| 事件访问保护 | 无/错误 operator token 读取 events | 返回 401/503 |
| 截断语义 | 事件超过 200 | 总数准确、`truncated=true` |
| 数据边界 | 检查响应、日志和 trace | 无患者、秘密和本地路径 |

自动测试入口：

```bash
pytest -q tests/test_physical_audit.py tests/test_physical_api.py
```

三容器和三 Spark 验收还必须执行：

- 每站事件 actor 和 Site ID 对应正确；
- 3/3 心跳、合同、提交、同步和模型核验形成连续事件；
- 掉站、数据版本变化、retry/resume/abort 可追溯；
- 修改备份副本中的任一历史事件能够被发现；
- 公共反向代理不能访问 `/api/physical/events`；
- 链头定期写入独立受保护存储，形成跨系统对照点。

## 9. 当前明确局限与生产升级

| 当前局限 | 影响 | 生产升级要求 |
| --- | --- | --- |
| SQLite pilot 不是 WORM | 数据库管理员仍可删除整库；持有 key 时可重建链 | PostgreSQL + 串行事件追加 + WORM/远端签名锚点 + 独立备份 |
| 尚未记录全部拒绝操作 | 认证失败、schema 422、策略拒绝等可能没有物理事件 | 建立不含攻击原文的拒绝事件 taxonomy，并避免认证洪泛污染主链 |
| 没有旧 HMAC key-ring 轮换 | 更换 key 后无法仅用当前 key 验证多个历史 HMAC key ID | Vault/KMS key-ring、版本化 key ID、轮换仪式和历史验证服务 |
| 多 worker PostgreSQL 追加已串行化 | 事务级 advisory lock 串行化“读取链头→追加”，唯一 `previous_hash` 索引阻止分叉 | 尚需真实 PostgreSQL 高并发、锁超时、进程崩溃和恢复演练 |
| legacy 操作员 token 仍保留在隔离验收模式 | 该路径无用户级身份且不能作为双人审批证据 | `physical` 已强制 OIDC/RBAC；继续补 MFA、会话吊销和资源级作用域 |
| 应用时间不是可信时间 | 有主机权限者可影响事件时间 | NTP 监控、可信时间源、外部时间戳/签名锚定 |
| 禁用字段基于 key 名 | 良性字段名下仍可能误放敏感值 | 固定 Pydantic 事件 schema、DLP 测试、代码审查和出口扫描 |
| 最近 200 条不是完整导出 | 不能作为长期审计证据包 | 受保护分页/流式导出、签名清单和保留策略 |
| HMAC 不是数字签名 | 共享 key 持有者都能生成事件 | 如需不可抵赖性，采用非对称签名/HSM 和独立审计方 |

在完成以上升级、医院安全评估、真实三设备演练和正式运维签字前，只能称为“P0 可检测篡改审计试点”，不能称为生产级不可篡改审计。

## 10. 相关文档

- [正式工程开发计划](engineering-development-plan.md)
- [三物理 DGX Spark 联邦部署手册](physical-deployment.md)
- [ADR-0001：物理联邦控制面与模拟路径隔离](adr/0001-physical-federation-control-plane.md)
- [ADR-0002：站点身份、证书与院内数据边界](adr/0002-site-identity-and-data-boundary.md)
- [ADR-0003：任务幂等、固定参与方与 Quorum](adr/0003-idempotency-and-quorum.md)
