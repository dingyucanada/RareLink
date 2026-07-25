# ADR-0001：物理联邦控制面与模拟路径隔离

- **状态：** Accepted
- **日期：** 2026-07-26
- **决策人：** RareLink 工程、产品与安全负责人
- **影响范围：** API、数据库、前端、NVIDIA FLARE Adapter、证据导出

## 背景

RareLink 的竞赛原型能够在单台 DGX Spark 上通过 NVIDIA FLARE SimEnv 运行多个逻辑站点。该路径适合开发、性能初测和演示，但它不具备独立医院身份、物理网络边界、独立证书、本地数据治理和跨设备故障语义。

正式工程需要在三家医院的三台 Spark 上运行独立 FLARE Client 和 Site Agent，并由独立协调端控制真实 NVIDIA FLARE Job。如果复用模拟状态或让 API 根据本地进程推断物理状态，系统会产生错误证据、无法恢复的状态以及“网页已完成但外部作业仍运行”等一致性问题。

## 决策

1. 建立独立的 Physical Federation Control Plane：
   - Site Agent 负责本站预检、心跳、本地命令和收据；
   - Federation Controller 通过受控 Admin Kit 与 FLARE Server 交互；
   - PostgreSQL 是控制面状态事实源，FLARE 与 Site Agent 状态通过持续对账收敛；
   - 前端仅调用 Control API，不直接调用 FLARE、Site Agent 或操作 Docker。
2. 所有作业强制标记运行模式：
   - `simulation`：单进程/SimEnv；
   - `isolated-integration`：多个隔离容器或 VM；
   - `physical`：经批准的独立物理站点。
3. 三种模式的数据库记录、指标、证据目录和 UI 标识互相隔离。
4. 只有 `physical` 作业可进入“三物理站点工程验证”证据包。
5. FLARE 访问封装在 Adapter 中；业务状态机不得依赖某一 CLI 输出文本。
6. 提交、停止和恢复均是异步命令；Control API 不以 HTTP 请求持续时间代表训练生命周期。
7. UI 的“运行实验”在物理研究中必须创建并审批真实联邦作业，不能回退到 SimEnv。

## 方案比较

| 方案 | 优点 | 缺点 | 结论 |
| --- | --- | --- | --- |
| 继续复用 SimEnv | 开发快、代码少 | 无独立身份/故障/数据边界，证据不真实 | 拒绝 |
| API 直接调用 FLARE CLI | 实现简单 | CLI 耦合、难对账、难测试、权限过大 | 拒绝 |
| 独立 Controller + Adapter + Site Agent | 边界清晰、可恢复、可测试 | 组件和状态机复杂度增加 | 采用 |
| 各站点直接暴露训练 API 给 UI | 低延迟 | 扩大攻击面、绕过中心审批 | 拒绝 |

## 后果

正面：

- 设备到位前可用三个隔离实例验证同一控制协议；
- 物理环境只需替换证书、地址和本地配置；
- 模拟结果不会被误用为真实跨院证据；
- 能可靠处理外部 Job ID、掉站、重启和提交不确定状态。

成本：

- 需要 PostgreSQL、Site Agent、状态对账和事件流；
- 前端必须从“按钮触发脚本”升级为异步作业控制台；
- 测试需要 FLARE Adapter fake、三容器环境和真实设备 E2E。

## 约束与验证

- `mode` 为必填且创建后不可变；
- 任何证据导出必须包含 `mode`、合同哈希、拓扑哈希和外部 Job ID；
- CI 必须验证 simulation/isolated-integration 不能进入 physical 证据包；
- Level 1 与 Level 2 的验收分别遵循主开发计划；
- 物理作业的“成功”需要 FLARE 状态、3/3 站点收据和模型完整性三方一致。

## 何时重新评审

- NVIDIA FLARE 提供稳定的远程管理 API，足以替代现有 Adapter；
- 部署拓扑从单一协调端变为多协调端/层级联邦；
- 需要支持超出当前医院信任模型的多租户平台。
