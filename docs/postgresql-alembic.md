# RareLink PostgreSQL 与 Alembic 生产数据库规范

**状态：** Production Boundary Defined  
**适用范围：** RareLink 中心控制面、审批、物理作业、审计和研究证据元数据  
**生产目标：** PostgreSQL + Alembic  
**非生产路径：** SQLite 仅用于演示、测试和单机开发

> 本文定义数据库进入真实医院试点前必须满足的工程与运维条件。仓库中的 SQLite 默认配置便于本地体验，不代表生产数据库能力。即使 PostgreSQL schema 与 Alembic 迁移在自动测试中通过，也不能替代目标医院的容量测试、高可用、备份恢复和灾难恢复演练。

## 1. 数据库边界

### 1.1 PostgreSQL 生产职责

中心 PostgreSQL 保存：

- 研究、实验合同和状态机元数据；
- 三物理站点的脱敏状态、数据指纹和心跳摘要；
- NVIDIA FLARE 外部 Job ID、轮次和聚合结果引用；
- OIDC 主体的最小持久化引用和 RBAC 审批记录；
- contract v1 摘要、第二审批和审批 note 摘要；
- 防篡改物理控制事件链；
- 模型、报告和证据工件的引用与 SHA-256。

PostgreSQL 不应保存：

- DICOM、NIfTI、标签或病例级指标；
- 原始 manifest、医院本地绝对路径或本地 checkpoint；
- OIDC JWT、refresh token、raw claims 或 Authorization header；
- FLARE Client/Admin 私钥、Admin Kit、API Key 或 submit token 明文；
- 审批 note 明文；
- 大模型 prompt/completion 原文中的敏感研究内容。

数据库不是影像仓库、密钥仓库或日志汇聚系统。上述边界必须同时由 schema、API、审计 payload allow-list、日志脱敏和部署网络落实。

### 1.2 SQLite 限定用途

SQLite 只允许：

- 本地开发和单进程测试；
- 赛事/产品演示；
- 单机、单 worker 的工程试验；
- Site Agent 本地幂等状态试点，在明确单写入者和本地磁盘边界下使用。

SQLite 不允许作为真实多医院中心控制面生产数据库，原因包括：

- 多 worker 写入和事件链追加缺少所需的并发序列化能力；
- 不提供目标生产级 HA、流复制、PITR 和集中运维；
- 当前 additive SQLite migration 只解决既有演示数据库的向前兼容；
- 本地数据库文件易被误复制、覆盖或与应用工件混放；
- SQLite 成功不能证明 PostgreSQL 的锁、事务、索引和迁移行为。

不得把 SQLite 数据库文件直接复制到生产主机并称为迁移。需要保留试点元数据时，必须经过受审计的导出、字段映射、数据边界检查、导入和逐项核验。

## 2. Alembic 是生产 schema 唯一变更入口

生产 PostgreSQL 的 schema 变更必须通过版本化 Alembic revision：

- revision 文件进入代码审查；
- 明确 `upgrade()` 和可行时的 `downgrade()`；
- revision ID、父 revision 和预期 head 唯一；
- 禁止运维人员直接手工执行未登记 DDL；
- 禁止依赖应用启动时的 `create_all()` 推断生产 schema；
- 禁止生产服务实例并发“自动迁移”；
- 应由独立 migration job、受控发布步骤或授权运维会话执行；
- 迁移凭据与应用运行凭据分离，应用账户原则上不持有 DDL 权限。

如果发布包含多个 Alembic head，必须在发布前合并；不能让生产环境自行选择分支。

### 2.1 当前实现检查点

仓库当前已经提供：

- `alembic.ini`、`alembic/env.py` 和初始 revision `0001_initial_schema`；
- Alembic 从 `RARELINK_DATABASE_URL` 读取迁移目标，不把 URL 固化在配置文件；
- 应用运行仍从 `DATABASE_URL` 读取连接；
- `postgres://` / `postgresql://` 在运行时明确归一化为 psycopg 3 dialect；
- `RARELINK_PHYSICAL_MODE=physical` 使用 SQLite 时启动失败；
- 非 SQLite 运行时不会调用 `SQLModel.metadata.create_all()` 或 additive SQLite migration；
- PostgreSQL 应用启动前检查 `alembic_version`，数据库未托管、revision 落后或存在非预期 head 时失败关闭；
- `/api/health/live` 只证明进程存活；`/api/health/ready` 执行数据库查询并再次
  核对 Alembic head。物理协调端容器只使用 readiness 作为流量健康门；
- 初始 schema 的 upgrade/downgrade、表列/外键/唯一索引和离线 SQL 秘密不泄露测试。
- revision `0002_serialize_physical_audit_chain` 为审计链前序摘要增加唯一索引；
  应用在 PostgreSQL 事务内取得固定 advisory lock 后再读取链头并追加事件，避免
  多 worker 同时从同一链头分叉。已有分叉会使迁移失败并进入人工调查，不会被
  自动覆盖。
- revision `0003_expire_physical_approvals` 持久化 job 与 approval record 的
  第二审批到期时间。旧审批保持空值并在执行门失败，不通过迁移伪造有效期。

当前自动化主要在临时 SQLite 上验证 Alembic schema 语义和前序唯一约束，并生成 PostgreSQL
offline SQL 检查秘密边界；这不等于真实 PostgreSQL 实例的锁、事务、并发和性能
验证。真实 PostgreSQL 集成测试与现场验收仍是发布门。

Readiness 失败只返回 `database=unavailable_or_stale`，不把数据库 URL、主机、用户、
revision 差异或底层异常暴露给未认证探针。详细错误应进入脱敏后的内部运维日志。

## 3. 连接与权限

应用生产连接使用 `DATABASE_URL`，例如：

```text
postgresql+psycopg://rarelink_app@db.internal.example/rarelink
```

执行 Alembic 时，将同一受控连接通过 `RARELINK_DATABASE_URL` 注入。两个变量的
值必须由部署系统从同一批准配置生成，避免应用与 migrator 指向不同数据库。

真实密码、客户端证书和连接参数由 Vault/KMS、Kubernetes Secret 或医院认可的密钥系统注入，不写入仓库、镜像、命令历史、截图或审计事件。

建议至少划分：

| 身份 | 权限 |
| --- | --- |
| `rarelink_app` | 对应用 schema 的最小 DML；无建库、角色和常规 DDL 权限 |
| `rarelink_migrator` | 在维护窗口执行批准的 Alembic revision |
| `rarelink_backup` | 执行备份所需最小只读/复制权限 |
| `rarelink_observer` | 受限监控视图，不读取敏感业务字段 |

连接要求：

- TLS 加密并验证服务器证书；
- 数据库不直接暴露公网；
- 只允许 API/迁移/备份运行域按最小网络策略访问；
- 连接池、statement timeout、idle transaction timeout 和最大连接数需按容量测试配置；
- 应用与数据库使用受监控的时间同步；
- PostgreSQL 日志不得记录完整参数、JWT、秘密或患者信息。

## 4. Revision 设计规则

每个 revision 必须记录：

- 变更目的、影响表和数据规模假设；
- 是否需要表锁、预计锁时长和超时策略；
- 是否向后兼容旧应用版本；
- 是否包含数据回填，以及回填能否重入和断点恢复；
- downgrade 是否安全；若不可逆，明确恢复方案；
- 对审计链、合同摘要、审批和幂等约束的影响；
- 迁移前后验证查询；
- 监控、停止条件和回滚决策人。

生产推荐 expand/contract：

1. **Expand：** 添加 nullable 字段、新表或兼容索引；
2. **Deploy：** 应用同时兼容旧/新 schema；
3. **Backfill：** 小批次、可重入、可观测地填充；
4. **Enforce：** 验证完成后增加约束；
5. **Contract：** 在旧版本完全退出后删除旧字段。

禁止在高流量窗口直接执行未经评估的全表重写、长事务回填、无 `CONCURRENTLY` 评估的大索引或不可恢复删除。

## 5. 开发与 CI 验证

每个 schema 变更至少通过以下路径：

1. 在空 PostgreSQL 数据库执行 `alembic upgrade head`；
2. 从上一个发布版本数据库快照升级到 head；
3. 执行 `alembic current`，确认只有预期 head；
4. 执行 Alembic schema drift/check；
5. 运行全量后端测试；
6. 运行物理控制面关键流程：站点、合同、双人审批、scope、提交、审计；
7. 检查唯一约束和并发冲突；
8. 验证回滚或前滚恢复方案；
9. 从备份恢复到新数据库并再次运行核验。

标准命令示意：

```bash
alembic current
alembic heads
alembic upgrade head
alembic check
```

命令必须在指向临时或目标环境的受控 `RARELINK_DATABASE_URL` 下执行。运行前应打印目标数据库的非敏感标识并由操作员确认，不能打印凭据。

生成 revision 后不得只凭 autogenerate 输出合并：

```bash
alembic revision --autogenerate -m "describe schema change"
```

开发者必须人工检查类型、server default、nullable、index、constraint、外键、枚举和 downgrade。Autogenerate 不是数据迁移设计器。

## 6. 发布迁移流程

### 6.1 发布前

| 步骤 | 验证 |
| --- | --- |
| 冻结版本 | 应用镜像、revision head、SBOM 和配置版本唯一 |
| 检查拓扑 | 确认目标环境、主库/副本、数据库名和当前 revision |
| 容量评估 | 表大小、索引空间、WAL 增量、锁和维护窗口 |
| 备份 | 完成加密逻辑备份；生产还需确认物理备份/WAL 归档健康 |
| 恢复验证 | 在隔离数据库恢复最近备份并通过结构/关键计数核验 |
| 审批 | 工程、数据库、产品/研究运维按变更等级批准 |
| 观察窗口 | 暂停不必要写入，建立告警和停止阈值 |

### 6.2 执行

1. 将应用置于与 revision 兼容的维护/降写状态；
2. 确保只有一个 migrator；
3. 记录当前 revision、备份 ID、应用版本和变更单；
4. 执行 `alembic upgrade <approved_revision>`；
5. 观察锁等待、错误、连接、WAL、CPU、磁盘和复制延迟；
6. 达到停止阈值时停止后续步骤，不盲目重试；
7. 完成后核对 current/head、表/列/索引/约束；
8. 运行只读 smoke，再恢复写入；
9. 运行物理控制面最小 smoke；
10. 保存不含秘密的迁移回执。

不要把多个生产 revision 隐式串在应用启动中执行。操作员必须知道本次发布会运行哪些 revision。

### 6.3 迁移回执

回执至少包含：

- 环境和数据库的非敏感 ID；
- 旧/新 revision；
- 应用版本和镜像摘要；
- 开始/结束 UTC 时间；
- 执行主体和变更单引用；
- 备份/恢复验证引用；
- 验证项与结果；
- 是否发生锁超时、重试或人工干预；
- 不含数据库密码、连接 URL、患者信息和业务行原文。

## 7. 回滚与恢复

### 7.1 优先前滚

数据库变更通常优先修复并前滚，因为 downgrade 可能丢失新版本已写入的数据。只有满足以下条件才执行 Alembic downgrade：

- downgrade 在等价数据量的预生产环境演练；
- revision 明确可逆；
- 回滚后的应用版本与 schema 兼容；
- 新写入数据的处理方式已经批准；
- 已验证备份可恢复；
- 数据库负责人授权。

### 7.2 不可逆迁移

删除列、收窄类型、重写数据或合并语义等不可逆操作必须：

- 在 revision 与发布计划中明确标注；
- 使用 expand/contract 延迟物理删除；
- 在删除前完成归档、验证和保留期审批；
- 把“恢复备份到新数据库并切换”作为灾难恢复方案；
- 不伪造空 `downgrade()` 为“支持回滚”。

### 7.3 恢复原则

- 不在故障现场直接覆盖唯一生产数据库；
- 优先恢复到新实例/新数据库；
- 验证 revision、关键表计数、外键、合同/审批/审计链完整性；
- 核对外部 NVIDIA FLARE Job 与数据库状态，避免重复提交；
- 切换前记录 RPO 数据缺口和需要人工对账的时间窗口；
- 恢复后轮换可能暴露的凭据并完成事件审查。

## 8. 备份与灾难恢复

### 8.1 最低备份要求

- 加密的逻辑备份，用于 schema/对象级恢复；
- PostgreSQL 物理基础备份与持续 WAL 归档，用于 PITR；
- 备份与主库不同故障域；
- 密钥与备份分权管理；
- 明确保留期、删除审批和恢复授权；
- 自动监控备份新鲜度、大小、校验和 WAL 连续性；
- 定期恢复演练，而不是只检查“备份任务成功”。

逻辑备份示意：

```bash
pg_dump --format=custom --file=rarelink.backup --dbname=<managed-connection>
pg_restore --list rarelink.backup
```

生产命令应使用 `.pgpass`、service definition 或密钥注入，不在参数中写明文密码。备份文件不得放入 Git、普通对象桶或公共演示工件。

### 8.2 恢复验证

恢复到隔离 PostgreSQL 后至少检查：

- Alembic revision 与预期一致；
- 所有表、外键、唯一约束和索引存在；
- 研究、物理作业、approval record 和事件链关键计数合理；
- 审计链 verification 通过；
- contract SHA-256 可重新核验；
- submit token 和审批 note 仅以摘要存在；
- OIDC token/raw claims 和患者数据不存在；
- 应用只读 smoke 和受控写 smoke 通过。

### 8.3 RPO/RTO

工程计划中的初始 RPO/RTO 只是受控试点目标。真实数值必须由医院根据研究影响、基础设施和预算批准，并用定期演练证明。未演练的 RPO/RTO 不能作为承诺。

## 9. 生产验证矩阵

| 类别 | 必测场景 | 通过条件 |
| --- | --- | --- |
| 空库升级 | base → head | 单一 head，应用 smoke 通过 |
| 旧版升级 | 上一发布快照 → head | 数据/约束/审计完整 |
| 并发审批 | 两个 second approval 同时写 | 仅一个成功，另一个安全冲突 |
| 审计追加 | 多 worker 并发事件 | 无链分叉、丢失或重复 |
| 幂等提交 | 并发同 submit token | 一个外部 Job |
| 锁故障 | 长事务阻塞 migration | 超时/停止，业务不进入未知状态 |
| 副本延迟 | 大 revision / backfill | 告警并在阈值前停止 |
| 主库故障 | 写入中 failover | 状态可对账，无重复副作用 |
| PITR | 恢复到指定时间点 | 满足批准 RPO，证据链可核验 |
| 应用回滚 | 旧应用 + 兼容 schema | 行为与契约测试通过 |
| 秘密边界 | 日志/回执/备份检查 | 无连接秘密、JWT、患者数据 |

## 10. 当前明确局限

当前不能宣称：

- 已完成真实医院规模的 PostgreSQL 压测；
- 已验证三院真实 WAN、峰值心跳、长期事件链和多研究并发容量；
- 已部署同步/异步副本、自动故障转移或跨故障域 HA；
- 已完成医院级备份、PITR 和灾难恢复演练；
- 已证明所有 Alembic downgrade 对真实数据可逆；
- 已获得目标医院 DBA、安全和合规签字；
- SQLite 试验数据已经完成受控生产迁移。

进入真实试点前必须形成独立的 PostgreSQL 验收报告，包含数据量模型、压测脚本、结果、锁与连接参数、备份恢复证据、故障转移演练、RPO/RTO 实测和剩余风险。

## 11. Definition of Done

一个生产数据库增量只有同时满足以下条件才完成：

- Alembic revision 经人工审查并保持单一 head；
- 空库和上一发布快照升级通过；
- 全量自动回归和 PostgreSQL 专项测试通过；
- 迁移、回滚/前滚、备份和恢复方案已演练；
- schema 与应用至少满足发布窗口内的版本兼容；
- 权限、TLS、秘密注入和日志边界通过安全审查；
- 迁移回执不含秘密或患者数据；
- 监控、告警和停止阈值已配置；
- 真实医院压测、HA、灾备和恢复演练有签字证据；
- 已知限制进入发布说明和风险登记。

## 12. 相关文档

- [正式工程开发计划](engineering-development-plan.md)
- [物理控制面防篡改审计](physical-audit.md)
- [物理联邦合同锁定与双人审批](physical-dual-approval.md)
- [物理控制面站点资源级授权](physical-site-scope.md)
