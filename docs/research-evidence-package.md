# RareLink Research Evidence Package v2

**产品定位：** 将一次联邦研究运行封装成可携带、可签名、可离线复核的研究证据发布物。

**格式：** 有界 ZIP、canonical JSON、双层 Ed25519 签名和内嵌离线验证器。

**安全边界：** 不打包影像、标签、模型权重、单站模型更新、患者字段、病例 ID、
本地路径、访问令牌、API 密钥或私钥。

## 1. 交付结构

```text
RareLink-Research-Evidence-Package.zip
├── study-contract.json
├── approvals.json
├── site-data-cards/
│   ├── hospital-a.json
│   ├── hospital-b.json
│   └── hospital-c.json
├── site-receipts/
│   ├── hospital-a.json
│   ├── hospital-b.json
│   └── hospital-c.json
├── model-card.json
├── run-card.json
├── privacy-ledger.json
├── security-assessment.json
├── aggregate-metrics.json
├── global-model-manifest.json
├── audit-chain.json
├── report.md
├── verify-evidence-package
├── model-release-public-key.pem
├── manifest.json
├── signature.json
└── signer-public-key.pem
```

前 13 类内容是科研证据；最后五项是离线验证所需的发布基础设施。
`model-card.json`、`run-card.json`、`report.md` 和内嵌验证器由生成器产生，不能由
调用方覆盖。每个站点拥有独立 Data Card 与 Receipt，避免把一份模糊的“三站汇总”
误当成三个站点分别完成。

## 2. 强制生成门

输入必须通过 `rarelink-evidence-source-v2`。生成器默认拒绝而不是降级：

| 门 | 必须满足 |
| --- | --- |
| 合同绑定 | Study、Job、Bundle、代码、三站身份、3/3 quorum 和轮次均被锁定 |
| 双人审批 | `study-release` 与 `independent-review` 两种审批齐全，审批人 ID 不同，均绑定同一合同 |
| 数据证明 | 三个 Data Card 均包含 manifest 摘要、数据指纹、病例数量、四模态质控通过声明 |
| 三站完成 | 三个 Receipt 均为 `COMPLETED`，完成轮次等于合同总轮次，Job/合同/代码/数据指纹完全一致 |
| 指标复算 | 从三站 Dice 与 HD95 重新计算平均值、最弱站点和站点标准差 |
| DP 预算 | `budget_exceeded=false`；启用 DP 时三站 epsilon 均不超过合同上限 |
| 安全评测 | Agent 红队、ART 成员推断、ART 模型反演和更新防护四道门全部通过 |
| 审计链 | 事件不截断、数量一致、previous/head 链接完整，且协调端验证声明为真 |
| 模型发布 | 全局模型 manifest 绑定 Job、合同和模型摘要，并通过独立 Ed25519 发布签名 |
| 内容安全 | 任一 JSON 中出现患者字段、病例 ID、DICOM UID、密钥、Token、私钥或本地绝对路径立即阻断 |

`L2` 隔离仿真不能生成 v2 的“严格研究发布包”。v2 只接受 `L3` 或 `L4` 输入，
但证据等级仍由真实部署条件和人工治理决定；生成 ZIP 本身不会把 L3 自动提升为 L4。

## 3. 哈希与签名模型

证据包包含两条相互独立的签名链：

1. **模型发布签名。** 模型发布公钥验证
   `Job ID + NVFLARE Job ID + 合同 SHA-256 + 模型 SHA-256 + 安全文件名 + 批准时间`。
2. **证据包签名。** 包发布公钥验证 canonical Manifest；Manifest 固定每个证据文件
   的路径、大小与 SHA-256，因此任一 Data Card、Receipt、报告或验证器被修改都会失败。

公开密钥随包携带只能用于验签，不能自证可信。审阅者必须通过独立渠道获得预期的
证据包签名公钥指纹，例如治理系统、线下交接单或医院 KMS 公告。

代码、站点数据和模型本体不会进入包，因此离线验证针对的是：

- 摘要格式正确；
- 同一摘要在合同、站点收据、Run Card 与发布清单中交叉一致；
- 相关签名和包完整性成立。

若要重新计算代码、数据或模型本体摘要，必须在其所属受控环境执行；证据包不会以
“导出敏感本体”换取表面上的可验证性。

## 4. 构建

证据包私钥必须是权限 `0600` 或更严格的 Ed25519 PEM 文件。私钥路径和内容不会
进入 ZIP 或构建收据：

```bash
.venv/bin/python scripts/build_research_evidence_package.py \
  --source reviewed-evidence-source-v2.json \
  --private-key /secure/coordinator/evidence-private.pem \
  --output artifacts/releases/rarelink-research-evidence.zip
```

构建前应由协调端从已锁定合同、审批记录、三站签名收据、隐私账本、安全评测与模型
发布记录生成 reviewed source；不要从前端自由文本直接拼装。

## 5. 离线验证

### 仓库中的独立验证器

```bash
.venv/bin/python scripts/verify_research_evidence_package.py \
  --package artifacts/releases/rarelink-research-evidence.zip \
  --expected-key-fingerprint '<trusted-sha256>' \
  --output artifacts/releases/verification.json
```

### 包内可携带验证器

先从 ZIP 解出 `verify-evidence-package`，再执行：

```bash
python3 verify-evidence-package \
  --package rarelink-research-evidence.zip \
  --expected-key-fingerprint '<trusted-sha256>'
```

内嵌脚本不导入 RareLink 应用，只依赖 Python 标准库和 `cryptography`。它自身也被
Manifest 固定并由包签名保护。高保障审计仍建议使用从独立可信渠道取得的验证器副本，
以避免完全依赖被审材料中携带的工具。

验证器离线检查：

- ZIP 路径穿越、重复条目、符号链接、文件集合、大小和可执行位；
- Manifest canonical JSON、所有文件大小与 SHA-256；
- 外部信任指纹与证据包 Ed25519 签名；
- 合同、Bundle、代码、三站数据指纹和模型摘要的跨文件绑定；
- 两位不同审批人、三站 `3/3` 完成和最终轮次；
- DP 预算与三站会计收据；
- Agent 红队、ART 成员推断、ART 模型反演、更新防护四道门；
- 审计事件数量、未截断声明、previous/head 链接；
- 全局模型发布 Ed25519 签名；
- 患者字段、病例 ID、DICOM UID、凭据、私钥和本地路径扫描。

任意一项失败，验证器返回非零退出码且不输出“部分通过”的发布结论。

## 6. 审计链的准确声明

审计事件使用协调端密钥产生 HMAC 时，离线包**不能且不应**包含 HMAC 密钥。因此：

- 离线验证可以检查事件未截断声明、数量、顺序、前序摘要链接和最终 head；
- 证据包 Ed25519 签名可以证明导出后未被修改；
- `verified_by_coordinator=true` 记录协调端在导出前完成过 HMAC 校验；
- 离线端不能在没有 HMAC 密钥时重新计算每个事件 HMAC。

如需第三方独立验证事件真实性，应使用 WORM/Object Lock、外部时间戳或医院 SIEM
锚定 audit head，而不是把 HMAC 密钥装进证据包。

## 7. 自动负向验收

专项测试覆盖：

- 内容被修改但 Manifest 未更新；
- 外部信任指纹不匹配；
- 两次审批由同一人完成；
- 任一站点只完成 4/5 轮或数据指纹错配；
- 合同与代码摘要不一致；
- 任一站点 epsilon 超预算；
- 四个安全门中的任一个失败；
- 审计链断裂或截断；
- 模型发布签名被替换；
- 患者字段、病例 ID、API Key、私钥或本地路径进入输入；
- 内嵌验证器在不导入 RareLink 的情况下完成验签。

```bash
.venv/bin/python -m pytest tests/test_evidence_package.py -q
```

这使 RareLink 的交付物不再只是“训练结束后的报告”，而成为一个具有明确证据边界、
密码学完整性和失败关闭验证规则的科研发布单元。
