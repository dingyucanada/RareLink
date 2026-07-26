# RareLink P0/P1 实施与自动验收报告

**版本日期：** 2026-07-26

**适用范围：** Physical Federation Control Plane、RareLink Site Agent、医院本地数据层、生产身份与联邦安全

**证据等级：** 软件实现与隔离集成验收；不代表三家医院、三台物理 DGX Spark 或临床试点已经完成

## 1. 本轮目标与结论

本轮将 P0/P1 从“接口和部署方案”推进为可执行的软件基线，重点消除单机 Demo 中最危险的假设：控制器重启后重复提交、站点掉线后状态倒退、证书或资源异常仍启动训练、OIDC 公钥轮换失败时继续放行、DP 只显示参数而不执行预算阻断、模型只计算哈希而不签名。

当前结论：

- P0 控制协议、Site Agent、作业对账、固定三站 quorum、掉站恢复、数据版本失效和结果哈希已经形成闭环；
- P1 的 OIDC/RBAC、动态 JWKS、PostgreSQL/Alembic、双人审批、审计链、物理 DP-SGD 合同、持久隐私预算、真实 FLARE 更新防护 Filter、ART 工程探针和 Ed25519 模型发布签名已经实现；
- 所有可在当前开发环境安全验证的路径均进入自动验收；
- 真实三设备 Admin Kit、医院 IdP/Vault、证书吊销服务、PACS/DICOM 和医院网络仍属于外部基础设施验收，代码不会把隔离测试表述为现场证据。

## 2. P0 实施结果

| 能力 | 实现 | 失败关闭条件 | 自动证据 |
| --- | --- | --- | --- |
| 独立 Site Agent | 每站独立 FastAPI、SQLite 0600 状态库、任务状态机、checkpoint 与签名收据 | 数据、证书、GPU、温度、CPU、内存、磁盘、依赖或 startup kit 任一异常即禁止 start/recover | Site Agent 正反例、重启和幂等测试 |
| 证书预检 | 校验 notBefore/notAfter、临期阈值、身份、CA 链、离线 CRL、批准目录、软链接和可写权限 | 未生效、过期、临期、错身份、链不可信、吊销、越界或可写均拒绝 | PKI 和路径负面矩阵 |
| 心跳可靠性 | 严格字段白名单、SQLite outbox、同 ID 重试、指数退避、409 去重确认 | 超过重放窗口换新签名包；从不持久化 Token/HMAC Key | 断线、响应丢失、进程重启测试 |
| 中心提交幂等 | 提交前持久化 token 摘要、attempt 和“结果未知”状态 | 相同 token 不得跨作业复用；崩溃后不自动再次 submit | 提交崩溃窗口和 token 冲突测试 |
| 外部 Job ID 对账 | 使用 NVFLARE list/meta 与 bundle SHA 对账 | 0 个匹配保持未知；多个匹配立即失败关闭 | 重启恢复与伪造 CLI 响应测试 |
| 状态单调性 | 严格解析轮次、站点身份、更新数和终态 | 状态回退、轮次越界、ID 错配、重复/未知站点、计数不一致均拒绝 | 对账状态矩阵 |
| 掉站与 quorum | 掉站进入 WAITING_FOR_SITES，恢复后继续；终态必须明确 3/3 | 2/3、模糊站点或非最终轮不得完成 | 掉站/恢复/3-of-3 测试 |
| 数据版本合同 | 作业锁定三个站点的数据指纹 | 心跳出现新指纹立即使旧合同失败，禁止 retry/resume | 数据变更 API 测试 |
| 结果核验 | 受控下载归档；完成态、最终轮、3/3 后才能绑定全局模型 SHA-256 和严格三站指标 | 文件缺失、软链接、摘要不符、指标模糊或 quorum 不足均拒绝 | 模型篡改和归档负面对照 |
| 实时前端 | 物理 submit/sync/abort/retry/resume、归档、签名、评审门与 SSE 断点续传 | 操作使用稳定幂等键；物理模式不调用 SimEnv | API/前端生产构建和 SSE 测试 |

## 3. P1 实施结果

### 3.1 身份、数据库与审批

| 能力 | 已实现 | 仍需现场完成 |
| --- | --- | --- |
| OIDC/RBAC | RS256/ES256、issuer/audience/time/sub、五角色权限、站点 scope、物理模式拒绝 legacy token | 医院 IdP 客户端注册、MFA/会话吊销策略 |
| 动态 JWKS | 固定 HTTPS URI 精确 allowlist、同源、TLS 校验、禁止重定向、字节上限、TTL、未知 kid 单次刷新、旧 key 短宽限、启动 preload 和 readiness 硬门 | 医院代理、CA、DNS 与出口策略联调 |
| PostgreSQL/Alembic | 物理模式拒绝 SQLite、版本不一致拒绝启动、审计链 PostgreSQL 串行化、迁移往返 | 医院 HA、PITR、备份恢复和容量压测 |
| 双人审批 | 不同 OIDC subject、合同摘要、有效期、不可变撤销、提交/重试/恢复重新核验 | 提交和模型发布的独立第二次操作审批 |
| HTTP 边界 | HTTPS 精确 CORS、no-store、CSP、HSTS、安全响应头 | API Gateway/WAF、分布式限流和渗透测试 |

### 3.2 联邦隐私与模型安全

1. **物理 DP-SGD 合同。** `fedavg_dpsgd` 导出包把 Opacus 的 `noise_multiplier`、`max_grad_norm`、`delta` 和 `accountant=rdp` 传入真实 NVFLARE Client 参数。隐私合同进入作业包摘要；审批后改动任一值都会改变 bundle SHA 并被拒绝。
2. **持久隐私预算。** 每个物理作业只能锁定一个预算。每站上报累计 RDP epsilon、delta、轮次和优化步数；全局消耗采用保守的“最大累计站点 epsilon”。重复、乱序、epsilon 下降、delta 不符或超预算均失败关闭，超预算后状态变为 `EXHAUSTED`。
3. **更新防护。** `RareLinkUpdateGuardFilter` 已进入导出的 NVIDIA FLARE Server 作业；对 mTLS 站点身份、作业、轮次和持久 nonce 进行合同/重放检查，拒绝 NaN、Infinity、零范数、超大参数量和方向异常，在聚合前执行 L2 范数裁剪，只输出不含张量的安全收据。
4. **模型发布签名。** 已核验全局模型在签名前再次计算 SHA-256；Ed25519 私钥只从协调端本地受控文件读取。签名绑定 Job ID、外部 NVFLARE Job ID、合同摘要、模型摘要、文件名和批准时间，数据库只保存签名、公钥指纹和 manifest 摘要。
5. **声明边界。** DP 结论只覆盖医院本地优化步骤；不自动提供用户级、医院级、通信层、模型发布或临床隐私保证。`secure_rng=false` 的工程限制保留在合同和文档中。
6. **安全聚合选型。** P1-S06 已选择 NVIDIA FLARE `FedAvgHERecipe` + TenSEAL 作为候选并完成威胁模型。当前 TenSEAL 未安装，且 HE 与服务器明文更新检查不能同时成立，因此保持禁用；只有把裁剪移至签名客户端边界并通过三设备性能、掉站和密钥治理验收后才能启用。
7. **隐私攻击工程探针。** ART 成员推断和 MIFace 只返回聚合指标，不保存成员级判断、原始输入或重建图像。合成 smoke 只证明工具链可运行，不是医学模型隐私结论。

## 4. 自动验收

执行：

```bash
make p0-p1-acceptance
```

验收器按顺序执行，任一失败即停止并返回非零退出码：

1. 全量 **382 项** Python 单元、API、迁移和隔离集成测试；
2. Ruff 静态检查；
3. React/TypeScript/Vite 生产构建；
4. 三个独立 OS 进程的控制协议演练；
5. 网络、重启、资源和更新安全七场景故障注入矩阵；
6. PostgreSQL 生产 Compose 安全配置校验；
7. Alembic 空库升级和降级往返。

新增的三物理设备现场验收工具采用只读采集，凭据只从环境读取，输出只包含
endpoint 摘要和签名运行证据。它在没有设备时不会降级生成 L3；现场结果首先标记
为 `L3-candidate`，必须由部署负责人核实三台设备、证书、网络和外部 Job ID。

签名研究证据包把合同、三站收据、聚合指标、隐私账本、安全评估、审计链和模型
发布绑定到 canonical Manifest，并自动生成 Data Card、Model Card 和 Run Card。
离线验证必须匹配独立渠道取得的 Ed25519 公钥指纹，包内公钥不能自证信任。

收据默认写入 `artifacts/acceptance/p0-p1-receipt.json`，只记录命令、退出码、耗时和输出摘要，不打包终端原文、令牌、密钥、影像、患者数据或本地数据路径。

## 5. 威胁—控制—测试映射

| 威胁 | 控制 | 主要测试 |
| --- | --- | --- |
| 控制器崩溃导致重复外部作业 | 提交前 token 摘要持久化、list/meta 对账 | 崩溃窗口、0/1/多匹配 |
| 旧快照覆盖新状态 | 单调状态机、迟到轮忽略、同轮合并 | 轮次回退、终态回退 |
| 掉站仍错误完成 | 固定站点身份、最终轮 3/3 quorum | 2/3、未知/重复站点 |
| 不安全站点启动训练 | 七项本地 preflight、503 和失败收据 | 证书/GPU/磁盘/数据负例 |
| JWT 新 kid 绕过信任 | 固定 JWKS 地址、一次刷新、未知仍拒绝 | 未知 kid、刷新失败、恶意 JWKS |
| DP 预算只展示不执行 | 持久 ledger 和 EXHAUSTED 状态 | 重放、乱序、delta、超预算 |
| 恶意或损坏更新进入聚合 | 有限值、范数、方向、轮次和 nonce 门 | NaN/Inf/零范数/重放/反向 |
| 模型文件在核验后被替换 | 发布前重算摘要、Ed25519 manifest 签名 | 摘要篡改、签名篡改、错误 key |
| 审计记录被修改或并发分叉 | HMAC 哈希链、PostgreSQL advisory lock | 历史篡改、敏感字段、并发写入 |

## 6. 未完成项与外部依赖

以下不是“少写了一段代码”，而是需要设备、医院系统或治理授权后才能产生真实证据：

- 三台物理 DGX Spark、独立网络和正式 NVFLARE Admin/Client Kit 的端到端运行；
- 医院 OIDC、MFA、人员离职/会话吊销和 Vault/KMS 实际接入；
- 正式证书 CA、CRL/OCSP、紧急吊销和轮换演练；
- DICOM-to-NIfTI/配准/像素烧录文字检查、PACS/FHIR、伦理审批、数据使用协议和医院安全评估；
- PostgreSQL HA、PITR、灾备、网关限流/WAF 和外部渗透测试；
- 安全聚合三设备运行、医院级隐私威胁评审和真实模型投毒红队；
- 真实 BraTS-PEDs 或其他获授权队列的重复实验与外部临床统计评审。

设备到位后的 Level 2 验收必须保留每台设备的身份、证书链、Job ID、轮次、3/3 更新、模型签名和审计链证据；任何单机逻辑站点、Fake CLI、容器或 SimEnv 结果都不得替代。
