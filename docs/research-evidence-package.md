# RareLink 签名研究证据包

**定位：** 将联邦作业从“运行结束”升级为“证据可独立复核”

**格式：** 有界 ZIP + canonical JSON + Ed25519 签名

**边界：** 不打包模型本体、患者数据、病例 ID、本地路径、Token 或私钥

## 1. 包内容

```text
rarelink-evidence.zip
├── study-contract.json
├── site-receipts.json
├── aggregate-metrics.json
├── privacy-ledger.json
├── security-assessment.json
├── audit-chain.json
├── global-model-manifest.json
├── model-release-public-key.pem
├── data-card.json
├── model-card.json
├── run-card.json
├── report.md
├── manifest.json
├── signature.json
└── signer-public-key.pem
```

`data-card`、`model-card` 和 `run-card` 由经过校验的输入自动生成，不能手工覆盖。
Manifest 固定每个文件的名称、大小和 SHA-256，再使用协调端本地 Ed25519 私钥签名。

## 2. 输入合同

输入 JSON 必须通过 `rarelink-evidence-source-v1`：

- 固定 Study ID、Physical Job ID、合同、Job Bundle 和模型 SHA-256；
- 正好三个不同 Site ID 和三份签名站点收据；
- 三站聚合指标必须能重新计算 mean、worst-site 和标准差；
- 模型发布 manifest 必须绑定相同 Job、合同和模型；
- 必须包含隐私账本、安全评估、审计链和明确限制；
- 出现患者、病例、凭据、私钥、本地路径等字段立即阻断。

输入可以标记 `L2`、`L3` 或 `L4`，但生成器不会自行提升证据等级。

## 3. 构建

签名私钥必须是权限为 `0600` 或更严格的 Ed25519 PEM 文件：

```bash
.venv/bin/python scripts/build_research_evidence_package.py \
  --source reviewed-evidence-source.json \
  --private-key /secure/coordinator/evidence-private.pem \
  --output artifacts/releases/rarelink-evidence.zip
```

私钥路径和内容不会进入 ZIP 或构建收据。

## 4. 离线验证

公开密钥放在包内用于验签，但信任不能由包自己建立。审阅者必须从独立渠道取得
预期公钥指纹：

```bash
.venv/bin/python scripts/verify_research_evidence_package.py \
  --package artifacts/releases/rarelink-evidence.zip \
  --expected-key-fingerprint '<trusted-sha256>' \
  --output artifacts/releases/verification.json
```

验证器检查：

- ZIP 路径穿越、重复条目、符号链接、文件数量和尺寸；
- Manifest canonical JSON；
- 所有文件 SHA-256 和大小；
- 敏感字段和绝对路径；
- 研究证据包 Ed25519 签名与全局模型发布 Ed25519 签名；
- 外部信任指纹；
- 安全声明必须明确为 false。

修改任一指标、卡片、限制或 Manifest 都会导致验证失败。

## 5. 产品意义

证据包不是普通报告压缩包。它把研究合同、三站执行、隐私预算、模型发布和审计
历史绑定到同一个可验证发布物，使合作医院、PI、工程团队和审计人员能够在不访问
患者影像或控制面数据库的情况下复核本次研究运行。
