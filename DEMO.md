# RareLink 评审一键复现包

本包的目标是让评审在**不下载医学影像、模型权重、证书或密钥**的前提下，启动控制台并核对已经记录的 DGX Spark 工程证据。

## 一条命令启动

在 DGX Spark 仓库根目录执行：

```bash
sudo docker compose -f deploy/compose.spark.yml up --build -d
```

启动后访问赛事分配的 8888 公网映射端口；节点内地址为 `http://127.0.0.1:8888`。API 文档在节点内 `http://127.0.0.1:9000/docs`。

停止服务：

```bash
sudo docker compose -f deploy/compose.spark.yml down
```

## 一条命令核验四项证据

```bash
sudo docker compose -f deploy/compose.spark.yml exec api python3 scripts/verify_demo_evidence.py \
  --artifact-root artifacts --write
```

在已配置项目虚拟环境的本地开发机上，可不用 `make` 直接运行：

```bash
bash scripts/review_demo.sh
```

成功时会输出四个 `true`：25 项五种子实验、样本级 DP-SGD 会计、两物理设备 mTLS 负面对照、26 条 Agent 红队用例。结果会写到被 Git 忽略的 `artifacts/demo-evidence/verification.json`。

如 Spark 上已按部署手册完成本地 TensorRT-LLM 的真实运行、探针和本地网关红队，可额外核验
这条**不参与四项必过项**的实机证据：

```bash
sudo docker compose -f deploy/compose.spark.yml exec api python3 \
  scripts/verify_spark_local_inference_evidence.py --artifact-root artifacts --write
```

该核验要求同时存在真实 GPU 快照、内容哈希而非提示词/回复正文，以及 26/26 本地门控测试；它
不会 seed 证据，也不会因为未部署本地模型而影响前述一键复现包的通过状态。

首次启动时，API 只会在缺少运行证据时写入 `fixtures/competition-evidence/` 中的**脱敏快照**。快照带 `evidence_snapshot=true`，不会覆盖 Spark 上已有的实时产物，也不是新跑出的实验。

## 评审阅读顺序

1. 在“评审证据驾驶舱”查看四张核心卡片与最弱站点 Dice 对比；
2. 确认 FedAvg 是当前工程候选，而不是医疗最优结论；
3. 查看 DP-SGD 的 `ε=6.076881, δ=1e-5` 与“仅覆盖本地训练步骤”的边界；
4. 查看 Spark–Mac mTLS 的首次注册、重连和错误身份拒绝；
5. 查看 Agent 输入脱敏与输出临床越权门禁的 26/26 固定用例结果；
6. 如公开 MSD 数据已由 Spark 直连下载，驾驶舱会额外显示 Public NIfTI Intake 的验证状态。

## 可选：重新运行工程实验

以下命令会生成新的本地合成数据并消耗 Spark GPU 时间；它们不是“秒级评审演示”的前置条件。

```bash
sudo docker compose -f deploy/compose.spark.yml exec api python3 scripts/prepare_demo_data.py --output data/runtime/synthetic-demo-v1
sudo docker compose -f deploy/compose.spark.yml exec api python3 scripts/run_repeated_benchmark.py \
  --manifest data/runtime/synthetic-demo-v1/manifest.json \
  --seeds 2026 2027 2028 2029 2030 \
  --strategies local fedavg fedprox fedavg_svt fedavg_dpsgd \
  --rounds 3 --local-epochs 1 --resume --workspace artifacts/repeated-benchmark
```

## 不在一键包中执行的动作

- 不下载或复制任何患者影像、公开数据集大文件或模型权重；
- 不创建/导出私钥、FLARE session token 或 Step API Key；
- 不声称临床有效性、真实医院部署或端到端隐私保证。

详细部署与公开基准操作见 [部署手册](docs/deployment.md)，实验事实与限制见 [DGX Spark 正式报告](outputs/RareLink-2026-07-17-DGX-Spark系统移植与实机实验正式报告.md)。
