# RareLink 物理联邦控制面对账与故障恢复

## 1. 文档范围

本文说明 RareLink 中心控制面如何处理 NVIDIA FLARE 外部作业状态、中心进程重启、
重复提交、迟到状态快照、站点掉线和固定三站 quorum。

当前自动化测试使用注入式 Fake CLI 和独立进程/数据库状态验证控制协议。它没有连接
三台真实 DGX Spark，也不构成跨医院运行、临床有效性或真实网络可靠性证据。

## 2. 一致性边界

RareLink PostgreSQL 记录控制意图、幂等摘要、外部 Job ID、attempt、轮次和已确认站点；
NVFLARE 是外部执行状态来源。前端状态、HTTP 是否超时以及进程内缓存都不是恢复依据。

中心提交采用两阶段顺序：

1. 先持久化 `submit_token_sha256`、attempt 和 `SUBMIT_OUTCOME_UNKNOWN`；
2. 再调用 `nvflare job submit`；
3. 只有解析出真实外部 Job ID 后，才写入 `external_job_id` 并清除未知标记。

如果步骤 2 后中心崩溃，重启后的相同提交只返回“需要对账”，不会再次调用 submit。
提交 Token 不进入 NVFLARE 命令、公开回执或日志，同一 Token 也不能绑定两个 RareLink
作业。

## 3. 外部提交对账

对账通过只读 `nvflare job list` 执行，并使用导出作业包的 SHA-256 查找候选项：

| 结果 | RareLink 行为 |
| --- | --- |
| 唯一候选且存在外部 Job ID | 绑定外部 Job ID，恢复为 `SUBMITTED` |
| 没有候选 | 保留 `SUBMIT_OUTCOME_UNKNOWN`，禁止自动重投 |
| 多个候选 | 失败关闭，要求人工调查重复外部作业 |
| 列表结构非法 | 失败关闭，不解析或转发原始 CLI 内容 |

“列表中暂时没有”可能来自分页或最终一致性，因此不被当作外部作业不存在的充分证明。

## 4. 状态对账规则

每次 `job meta` 响应先经过严格结构验证，再更新本地记录：

- 未知状态、非对象响应、缺失运行轮次、越界轮次全部失败关闭；
- 外部 Job ID 与本地绑定不一致时失败关闭；
- 终态不能回退，`RUNNING → SUBMITTED` 等同轮次回退视为非法；
- 旧轮次快照不修改当前轮次、站点或 quorum；
- 同轮次的旧快照与已确认站点做单调合并，不撤销既有更新；
- 更新站点必须属于合同锁定的三个站点，且不得重复；
- 更新数量必须与明确站点身份数量一致，单纯声称“收到 3 个”不能满足 quorum；
- `COMPLETED` 必须位于最终轮，且三个预期站点身份全部出现；
- 可恢复的 `RECONCILIATION_*` 错误允许后续有效快照修复，其他失败不得被远端活动状态静默覆盖。

公开对账回执只包含 allow-list 状态、错误代码和哈希，不包含 Admin Kit 路径、CLI 原始
输出、Token、患者信息或影像路径。

## 5. 掉站与 Quorum

当前物理试点合同固定为三个明确站点和 `3/3` quorum。

当 NVFLARE 明确返回 `connected_clients` 且缺少任一预期站点时，RareLink 将作业置为
`WAITING_FOR_SITES`，错误代码为 `EXPECTED_SITE_OFFLINE`。系统不会将 2/3 静默解释为
成功，也不会自动修改合同。站点重新连接并返回有效快照后，可以恢复 `RUNNING`。

最终完成要求：

- 当前轮等于合同总轮数；
- `received_from` 包含三个不同的预期站点；
- `received_updates` 与三个站点身份一致；
- 后续全局模型 SHA-256 校验通过。

## 6. 迟到与重复状态

控制面对状态快照使用以下语义：

- `remote_round < persisted_round`：标记为迟到并忽略；
- 同轮次站点集合是已确认集合的子集：作为旧快照单调合并；
- 新轮次：重置为新轮的站点更新集合；
- 重复的完全相同快照：幂等更新，不产生新的外部动作；
- 非预期站点、重复站点或数量不匹配：失败关闭。

这部分处理的是中心读取到的元数据快照。训练更新本身仍必须在 NVFLARE/Site Agent
侧绑定 `job_id + attempt + round_id + site_id + base_model_hash` 并验证签名。

## 7. 重启恢复

`recover_after_restart` 遍历持久化的非终态作业：

- 已有外部 Job ID：调用只读 `job meta` 对账；
- 有提交摘要但没有外部 Job ID：调用只读 `job list` 做提交对账；
- 没有提交意图的已验证草案：不访问外部系统；
- 外部查询失败：记录安全错误代码，不输出 CLI 原文。

恢复回执始终声明 `external_submit_performed=false` 和
`evidence_scope=control-protocol-only`。恢复过程不得以 UI 缓存推测作业状态。

## 8. 当前仍需完成

- PostgreSQL 上的并发提交唯一约束和行级锁压力测试；
- NVFLARE 实际版本返回结构的现场契约测试；
- Site Agent 训练更新级幂等 Inbox；
- abort 超时的 `ABORT_UNKNOWN` 持久状态；
- 心跳超时策略和自动中止审批；
- 三台物理 Spark 的断网、重启和 checkpoint 恢复演练。
