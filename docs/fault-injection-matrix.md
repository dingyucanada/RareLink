# RareLink 故障注入矩阵

**当前等级：** L2 隔离组件故障注入

**用途：** 自动验证失败关闭、持久化、幂等和恢复语义

**禁止声明：** 当前结果不是三台物理 Spark 的拔线、断电或磁盘耗尽演练

## 1. 自动场景

| 场景 | 注入方式 | 必须结果 |
| --- | --- | --- |
| 网络中断与重连 | 心跳发送失败并重建 outbox | 同一签名 envelope 持久化、退避，只在确认后清除 |
| Agent 重启 | 保留 SQLite，重建 TaskService，执行器不再运行 | 状态失败关闭，只允许一次 recover，不重复 start |
| GPU 异常 | 健康探针返回 GPU failure | executor 调用次数为 0，任务写入 FAILED |
| 磁盘不足 | 健康探针返回 disk failure | executor 调用次数为 0，任务写入 FAILED |
| 证书异常 | 健康探针返回 certificate failure | executor 调用次数为 0，任务写入 FAILED |
| 重复更新 | 重建 SQLite replay registry 后提交相同 nonce | 第二次更新拒绝 |
| 迟到更新 | 提交旧 Round ID | 聚合前拒绝 |

## 2. 执行

```bash
make fault-injection-matrix
```

或保存收据：

```bash
.venv/bin/python scripts/run_fault_injection_matrix.py \
  --output artifacts/acceptance/fault-matrix.json
```

收据只记录场景、预期、观察结果和摘要，不包含数据库路径、HMAC Key、Token、张量
或患者数据。

## 3. 物理设备阶段

三台设备可用后，需要使用现场变更单追加：

1. 断开 Hospital C 网络并观察 quorum；
2. 强制停止一个 FLARE Client 后安全恢复；
3. 使用正式 CRL 吊销测试证书；
4. 将磁盘可用空间降至批准阈值以下；
5. 协调端重启和 PostgreSQL 恢复；
6. SSE 反向代理断连和 `Last-Event-ID` 恢复；
7. HE 模式下验证缺站不能静默降级。

物理场景必须保留三站设备证明、证书身份、外部 Job ID、操作时间、状态转换和
最终模型签名，并由部署负责人签署。自动组件矩阵不能替代这些证据。
