# RareLink 获奖证据升级：DGX Spark 实机报告

验证日期：2026-07-16  
数据边界：全部训练和预览数据均为程序生成的非临床合成 NIfTI；不包含患者数据。  
声明边界：结果用于黑客松工程稳定性证明，不是临床有效性证据。

## 1. 结论

六天冲刺计划中的高价值升级已经形成可运行闭环：

1. 五个随机种子的 Local、FedAvg、FedProx、FedAvg+SVT、FedAvg+DP-SGD 共 25 个三轮对齐试验全部完成；
2. Local 使用 3 epochs，与联邦客户端的 3 轮 × 1 epoch 对齐本地训练机会；
3. NVIDIA FLARE Server 与 Site A/B/C 使用独立证书启动，并完成 Spark–Mac 双物理设备 mTLS、掉线重连和错误身份拒绝；
4. Opacus DP-SGD 完成逐样本裁剪、加噪以及跨轮 RDP `(epsilon, delta)` 会计；
5. 26 条 Agent 输入/输出红队用例在 Spark 上全部通过；
6. T1、T1CE、T2、FLAIR 四模态合成 MRI 与标签叠加由 Spark 本地 API 生成并在浏览器 Canvas 展示，像素数据不进入 Step 3.7。

标准演示研究还通过控制平面完成了真实任务，全局模型、指标和日志均回写数据库，研究状态进入 `RESULTS_REVIEW`。证据叙事 Agent 使用 25 次重复实验的聚合摘要生成稳定性结论。

## 2. 多随机种子稳定性实验

合同配置：随机种子 `2026/2027/2028/2029/2030`、三个逻辑站点、每种联邦策略 3 轮、每轮每站点 1 个本地 epoch、Local 3 epochs、相同 SegResNet 和数据清单。共完成 25 个策略—种子组合。

| 策略 | Mean Dice，均值±标准差 | Worst-site Dice，均值±标准差 | HD95 均值 | 最弱站点胜率 | 平均耗时 | 峰值 GPU 内存 |
|---|---:|---:|---:|---:|---:|---:|
| Local | 0.049025 ± 0.013654 | 0.023893 ± 0.011558 | 14.514729 | 20% | 1.52 s | 24.38 MB |
| FedAvg | 0.080087 ± 0.080502 | 0.072276 ± 0.075325 | 14.390605 | 40% | 73.05 s | 20.73 MB |
| FedProx | 0.073442 ± 0.035380 | 0.051055 ± 0.030026 | 13.879725 | 20% | 72.68 s | 21.59 MB |
| FedAvg + SVT | 0.000000 ± 0.000000 | 0.000000 ± 0.000000 | 0.000000 | 0% | 73.21 s | 20.73 MB |
| FedAvg + DP-SGD | 0.041315 ± 0.052110 | 0.037724 ± 0.048620 | 18.970487 | 20% | 73.59 s | 55.78 MB |

FedAvg、FedProx、DP-SGD 和 SVT 相比 Local 分别在 3/5、4/5、2/5、0/5 个种子上改善最弱站点 Dice。FedAvg 最弱站点胜率为 40%，但其 95% t 区间仍很宽；不能据此宣称任何医学优越性。SVT 在“仅共享 1% 更新”的严格配置下五次均退化为 0，清楚展示了隐私过滤强度与可用性的冲突，而不是被隐藏的失败结果。

证据叙事 Agent 给出的当前工程候选为 FedAvg，依据为 5 次重复、Mean Dice 0.0801、Worst-site Dice 0.0723、最弱站点胜率 40%；同时明确输出“合成工程证据”“五种子区间仍宽”“DP-SGD 只覆盖本地训练步骤”。

## 3. FLARE mTLS 安全通信演练

使用 NVIDIA FLARE 2.7.2 Provision 工具生成：

- 一个 Root CA；
- FLARE Server 身份证书和私钥；
- Site A、Site B、Site C 各自独立的客户端证书和私钥；
- 每个 startup kit 的签名文件；
- 独立组织标识 `hospital_a`、`hospital_b`、`hospital_c`。

第一阶段在 Spark 运行一个 Server 和三个 Client，三个站点均完成安全注册。第二阶段在 Spark 运行 Server，在 Mac 运行 Site C，通过 SSH 隧道承载 FLARE mTLS 控制流量：首次注册成功、主动结束客户端后再次注册成功；将 Site B 证书替换进声明为 Site C 的临时启动包时，FLARE 启动签名校验以非零状态拒绝。

脱敏证据只保存设备平台、哈希化设备指纹、注册/重连布尔值和拒绝类别，不保存运行令牌、会话 ID、私钥或原始日志。临时启动包只通过加密 SSH 进入 Mac 的 `/private/tmp`，不进入 Git，证据固化后删除。

准确表述：**已完成 DGX Spark–Mac 两物理设备的 mTLS 注册、掉线重连与错误身份负面对照；尚未完成医院 WAN、可用性压力或生产身份系统验证。**

复现：

```bash
python3 scripts/provision_secure_federation.py \
  --workspace artifacts/nvflare-secure-provision

bash artifacts/nvflare-secure-provision/rarelink_secure_rehearsal/prod_00/start_all.sh

python3 scripts/capture_mtls_runtime_evidence.py \
  --workspace artifacts/nvflare-secure-provision
```

## 4. 差分隐私—效用对照

第四种策略在客户端训练结果离站前应用 NVIDIA FLARE `SVTPrivacy`：

| 参数 | 配置 |
|---|---:|
| `epsilon` 参数/调用 | 0.1 |
| 共享更新比例 | 1% |
| `noise_var` 参数 | 0.1 |
| 每客户端调用次数 | 3 |

该策略确实运行了 FLARE 客户端输出过滤器，而不是只在报告中模拟噪声。FLARE 2.7.2 的 SVT 结果仍只作过滤器配置级证据，不能冒充样本级 DP 会计。本次五种子实验的 Dice 全部为 0，说明该配置不可作为当前工程候选。

第五种策略使用 Opacus 1.6.0 DP-SGD：`noise_multiplier=1.2`、`max_grad_norm=1.0`、Poisson 采样率 `1/3`、每站点 3 轮共保守计入 9 个计划优化步。在 `delta=1e-5` 下，三站点和五次重复的累计 `epsilon` 均为 `6.076881`。准确边界是样本级本地训练会计，不是端到端系统、用户级、医院级或临床隐私保证。

## 5. 四模态 MRI 本地感知

新增接口只允许读取 `contains_patient_data=false` 的清单。它在 Spark 本地完成：

1. 读取四模态 NIfTI；
2. 自动选择标签前景最大的轴位切片；
3. 对每个模态执行 1%–99% 分位归一化；
4. 下采样成显示数组；
5. 返回 T1/T1CE/T2/FLAIR 与水肿/核心标签；
6. 前端 Canvas 完成本地灰度和颜色叠加。

接口不返回源文件路径，真实患者数据清单会直接收到 403。Spark 实测返回 `site-a-case-001`、32×32 合成切片、四个模态，并明确 `sent_to_llm=false`。

## 6. 控制平面与质量验证

标准研究状态：

```text
DRAFT → PROTOCOL_REVIEW → FEASIBILITY_RUNNING → FEASIBILITY_REVIEW
→ CONTRACT_LOCKED → TRAINING_RUNNING → RESULTS_REVIEW
```

Local、FedAvg、FedProx 和 DP-SGD 均已接入控制面；联邦策略生成 `FL_global_model.pt`。五随机种子稳定性、跨设备 mTLS、DP 会计和 Agent 红队证据均可由 `/api/system/evidence` 返回。

本轮回归结果：30 项 Python 测试通过，Ruff 通过，TypeScript 与 Vite 生产构建通过；Agent 红队 26/26 通过。

## 7. 仍然保留的限制

- 训练实验仍是在单台 Spark 上模拟三个逻辑站点，不是三家真实医院；跨设备 mTLS 只验证通信身份链路；
- 使用合成数据，不是儿童胶质瘤临床效果验证；
- SVT 是更新过滤器配置级证据；DP-SGD 是样本级本地训练会计，二者都不是完整临床隐私证明；
- 五个随机种子和三轮训练仍只能说明合成工程稳定性，不能支撑医学统计推断；
- 当前 PyTorch 对 GB10 compute capability 12.1 仍给出正式支持上限 12.0 的警告，尽管所有 CUDA 任务实际成功。

这些限制将在比赛界面、报告和视频中继续明确展示。

## 8. 后续实机升级记录：样本级 DP-SGD 与 Agent 红队

在上述四项基础上，RareLink 已继续完成以下升级：

1. 新增 `FedAvg + DP-SGD`，使用 Opacus 1.6.0 在各站点执行逐样本梯度裁剪、加噪与 Poisson 采样；
2. 使用 RDP Accountant 按站点采样率、噪声乘子和计划优化步数，在服务端跨 FLARE 轮次重新组合隐私预算；
3. 三轮 Spark 修复验证在 `noise_multiplier=1.2`、`max_grad_norm=1.0`、`delta=1e-5` 下得到保守预算 `epsilon=6.076881`；
4. 针对 Poisson 空抽样增加显式处理：空批次不进入 Conv3d、不更新模型，但仍按计划调用保守计费，避免低估预算；
5. 新增 26 条 Agent 红队用例，覆盖标识符、原始影像、DICOM UID、路径、联系方式、密钥、小样本、诊疗越权、临床夸大和合同提权；Spark 实跑 26/26 通过；
6. 新增跨物理设备 mTLS 证据工具，只有同时满足首次注册、掉线重连、错误身份拒绝、设备指纹不同且报告不含令牌时才生成通过证据。

样本级 DP 的准确声明是：**已对每家站点的本地训练步骤进行可复算的样本级 DP-SGD 会计；未宣称端到端系统、用户级、医院级或临床隐私保证。**

正式稳定性矩阵已经完成 5 个随机种子、5 种策略、3 个联邦轮次，共 25 项，并生成 `complete=true` 汇总。运行中暴露的两个 Opacus 边界——普通空 Poisson 批次与第一批即为空时的 MONAI 字典 dtype 推导——均已修复、增加回归测试并在原失败种子上复验通过。
