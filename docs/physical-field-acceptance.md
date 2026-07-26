# RareLink 三物理设备现场验收工具包

**状态：** 软件完成；等待三台独立 DGX Spark 和正式 NVIDIA FLARE Kit 执行

**模式：** 只读证据采集

**默认声明：** `L3-candidate`，必须由部署负责人复核签字后才能升级为 L3

## 1. 目标

现场验收工具解决的是“设备终于可用时不再临时写脚本”。它从三个独立 Site
Agent 和协调端读取：

- GPU、内存、磁盘、证书、依赖和数据证明；
- 本地任务状态、轮次和签名收据摘要；
- 协调端三站注册、真实 NVIDIA FLARE Job ID、合同、轮次和 `3/3` quorum；
- Client Registry、模型哈希、发布签名、统计评审门和审计链摘要。

工具不执行提交、停止、恢复或故障注入，不会因为一次验收命令改变真实训练状态。

## 2. 安全边界

- Plan 只允许服务 origin，不允许 URL 用户名、密码、query 或 fragment；
- L3 候选必须使用 HTTPS、三个不同站点 endpoint 和三个不同设备证明摘要；
- OIDC Bearer Token 和每站 Token 只从进程环境读取；
- 输出不包含 URL、Token、本地路径、患者数据、Admin Kit 或私钥；
- HTTP 响应必须为有界 JSON，不跟随重定向；
- 任何站点缺少健康检查、协调端不是 physical 模式、合同不匹配或审计链失败，
  验收立即失败。

## 3. 准备

复制非秘密 Plan：

```bash
cp deploy/physical/field-acceptance.example.yml \
  deploy/physical/field-acceptance.yml
```

在受控终端中设置凭据：

```bash
export RARELINK_FIELD_COORDINATOR_BEARER_TOKEN='<short-lived-oidc-token>'
export RARELINK_FIELD_SITE_TOKEN_HOSPITAL_A='<site-a-token>'
export RARELINK_FIELD_SITE_TOKEN_HOSPITAL_B='<site-b-token>'
export RARELINK_FIELD_SITE_TOKEN_HOSPITAL_C='<site-c-token>'
```

Plan 和输出不得包含上述值。环境变量应由医院密钥系统或短期会话注入。

## 4. 执行

```bash
.venv/bin/python scripts/accept_three_physical_sites.py \
  --plan deploy/physical/field-acceptance.yml \
  --output artifacts/acceptance/physical-field.json
```

完成态验收要求：

- 三站 Site Agent 全部 ready；
- GPU、内存、磁盘、证书、依赖和数据检查全部通过；
- 协调端只出现三个预期站点；
- Job ID、合同 SHA、轮次和 `3/3` quorum 与 Plan 一致；
- 真实外部 NVFLARE Job ID 存在；
- 全局模型 SHA 与 Plan 一致并已发布签名；
- 统计评审门通过；
- 审计链验证通过。

## 5. L3 关闭条件

`L3-candidate` 收据仍需要现场负责人确认：

1. 三个设备证明摘要确实来自三台独立 DGX Spark；
2. 三站证书、Client Kit 和私钥分别托管；
3. endpoint 分属真实部署网络，而不是单机端口映射；
4. 外部 Job ID 对应本次多轮训练；
5. 故障演练由真实断网/进程停止/证书吊销/磁盘阈值触发；
6. 收据签名并进入研究证据包。

未完成这些确认时，GitHub、演示和报告只能写“L3 候选现场采集工具已完成”。
