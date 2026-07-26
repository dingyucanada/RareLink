# RareLink 物理联邦 DP-SGD 作业合同

## 1. 范围与证据边界

RareLink 的 `fedavg_dpsgd` 物理作业使用每家医院本地的 Opacus 样本级 DP-SGD。
作业导出器、客户端命令参数和提交前验证器共享同一份不可变隐私配置：

- `noise_multiplier`
- `max_grad_norm`
- `delta`
- `accountant=rdp`
- `poisson_sampling=true`
- `grad_sample_mode=ew`
- `secure_rng=false`

当前自动化测试证明的是隐私参数被正确锁定、传播、校验并纳入作业包 SHA-256。
它没有在三台真实 DGX Spark 上执行训练，也没有形成真实医院数据的 epsilon 结果。

## 2. 导出命令

```bash
python scripts/export_physical_nvflare_job.py \
  --topology configs/physical/topology.example.yml \
  --strategy fedavg_dpsgd \
  --rounds 5 \
  --local-epochs 1 \
  --dp-noise-multiplier 1.2 \
  --dp-max-grad-norm 1.0 \
  --dp-delta 0.00001 \
  --dp-accountant rdp \
  --output-dir artifacts/physical-jobs/fedavg-dpsgd
```

导出器把同一组数值写入：

1. NVFLARE Client 的 `--dp-sgd` 和 Opacus 参数；
2. `rarelink-job-receipt.json` 的 `privacy` 合同；
3. 整个导出目录的确定性 Bundle SHA-256。

改变任一隐私字段都会改变 Bundle SHA-256，并进一步改变双人审批锁定的合同摘要。

## 3. 隐私收据

`privacy` 对象使用严格字段集合。缺字段、未知字段、未知 accountant、非有限数字、
非正噪声或裁剪阈值、过大 delta，以及伪造的隐私声明都会在提交 NVFLARE 前被拒绝。

关键边界：

- `accounting_scope=sample_level_local_training`
- `epsilon_budget_mode=measured_post_training_per_site`
- `federation_budget_rule=max_cumulative_site_epsilon`
- `site_epsilon_receipt_required=true`
- `end_to_end_sample_dp_claimed=false`

epsilon 不是由噪声乘数单独预先决定的。它还取决于每站样本量、采样率和累计优化步骤，
因此由各站 Opacus RDP Accountant 在训练时计算，再按最大累计站点 epsilon 汇总。

## 4. 不允许的声明

本合同不能单独证明：

- 用户级或医院级差分隐私；
- 安全聚合；
- 传输层安全；
- 全局模型发布后的隐私安全；
- 成员推断或模型反演风险已经消除；
- 临床安全性、有效性或合规认证。

当前 `secure_rng=false` 与既有工程验证路径一致，不能作为高保证密码学随机源证据。
正式医院试点前必须评估 Opacus `secure_mode`、随机源依赖和性能影响。

## 5. 启动与恢复约束

DP-SGD 作业从 SQL Store 恢复时会重新验证导出目录，并比较 Bundle SHA-256。隐私收据
或训练参数在审批后被修改，恢复会失败关闭，不会继续提交或训练。

非 DP 的 `fedavg` 和 `fedprox` 必须声明隐私机制关闭；它们不能携带 DP 配置并同时
声称样本级隐私。

## 6. 后续工程

- 将 DP 合同字段加入正式 Physical Job API Schema；
- 为每站 epsilon 收据增加签名、轮次和数据指纹绑定；
- 在预算账本中设置经统计/隐私负责人批准的最大 epsilon；
- 超预算时中止后续轮次并记录不可篡改审计事件；
- 在三台物理 Spark 上执行多轮重复试验和效用—隐私对照；
- 加入成员推断、模型反演与异常更新安全评测。
