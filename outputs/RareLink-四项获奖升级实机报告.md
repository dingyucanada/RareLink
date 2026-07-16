# RareLink 四项获奖升级：DGX Spark 实机报告

验证日期：2026-07-16  
数据边界：全部训练和预览数据均为程序生成的非临床合成 NIfTI；不包含患者数据。  
声明边界：结果用于黑客松工程稳定性证明，不是临床有效性证据。

## 1. 结论

六天冲刺计划中的四项高价值升级已经形成可运行闭环：

1. 三个随机种子的 Local、FedAvg、FedProx、FedAvg+SVT 共 12 个对齐试验全部完成；
2. NVIDIA FLARE Server 与 Site A/B/C 使用独立证书启动，三个客户端完成 mTLS 注册；
3. NVIDIA FLARE `SVTPrivacy` 模型更新过滤器完成实际训练与隐私—效用对照；
4. T1、T1CE、T2、FLAIR 四模态合成 MRI 与标签叠加由 Spark 本地 API 生成并在浏览器 Canvas 展示；像素数据不进入 Step 3.7。

标准演示研究还通过控制平面完成了 Local、FedAvg、FedProx 三项真实任务，全局模型、指标和日志均回写数据库，研究状态进入 `RESULTS_REVIEW`。证据叙事 Agent 使用 12 次重复实验的聚合摘要生成稳定性结论。

## 2. 多随机种子稳定性实验

合同配置：随机种子 `2026/2027/2028`、三个逻辑站点、每种策略 1 个联邦轮次、每站点 1 个本地 epoch、相同 SegResNet 和数据清单。共完成 12 个策略—种子组合。

| 策略 | Mean Dice，均值±标准差 | Worst-site Dice，均值±标准差 | HD95 均值 | 最弱站点胜率 | 平均耗时 | 峰值 GPU 内存 |
|---|---:|---:|---:|---:|---:|---:|
| Local | 0.034033 ± 0.003490 | 0.010714 ± 0.002490 | 16.623686 | 0% | 1.58 s | 25.81 MB |
| FedAvg | 0.018193 ± 0.006839 | 0.015082 ± 0.005266 | 15.859248 | 0% | 33.57 s | 22.59 MB |
| FedProx | 0.067265 ± 0.050893 | 0.061712 ± 0.046029 | 17.016439 | 66.7% | 33.87 s | 23.01 MB |
| FedAvg + SVT | 0.058791 ± 0.069742 | 0.056088 ± 0.069499 | 15.157358 | 33.3% | 33.85 s | 22.59 MB |

FedAvg、FedProx 和 FedAvg+SVT 相比 Local 分别在 3/3、3/3、2/3 个种子上改善最弱站点 Dice。但由于数据极小、只有单轮训练，区间很宽，不能据此宣称 FedProx 或隐私策略具有医学优越性。这个实验的价值是证明：RareLink 能执行对齐重复试验、暴露不稳定性，并阻止 Agent 用单次最好结果下结论。

证据叙事 Agent 给出的当前工程候选为 FedProx，依据为 3 次重复、Mean Dice 0.0673、Worst-site Dice 0.0617、最弱站点胜率 66.7%；同时明确输出“非临床验证”“三种子区间较宽”“SVT 不等于端到端样本级 DP”。

## 3. FLARE mTLS 安全通信演练

使用 NVIDIA FLARE 2.7.2 Provision 工具生成：

- 一个 Root CA；
- FLARE Server 身份证书和私钥；
- Site A、Site B、Site C 各自独立的客户端证书和私钥；
- 每个 startup kit 的签名文件；
- 独立组织标识 `hospital_a`、`hospital_b`、`hospital_c`。

Spark 运行态启动一个 Server 和三个 Client 进程，三个站点均记录 `Successfully registered client`。脱敏证据文件只保存站点 ID、注册时间和 mTLS 状态，不保存运行令牌、会话 ID 或私钥。证书私钥仅保留在 Spark 的忽略目录中，不进入 Git，也不经 SSH 导出。

准确表述：**已在单台 DGX Spark 上完成三个隔离站点的 mTLS 安全注册演练；尚未完成真实医院网络部署。**

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
| 每客户端调用次数 | 1 |

该策略确实运行了 FLARE 客户端输出过滤器，而不是只在报告中模拟噪声。当前安装的 NVIDIA FLARE 2.7.2 过滤器暴露 SVT 参数，但本项目没有把它包装成完整的样本级 DP-SGD 会计。因此界面和 JSON 均写明：`accounting_scope=filter_configuration_only`、`end_to_end_sample_dp_claimed=false`。

下一阶段若要形成患者级 `(epsilon, delta)` 保证，应接入基于 Opacus 的 DP-SGD、逐样本梯度裁剪、采样率和跨轮次隐私会计。

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

Local、FedAvg、FedProx 三个后台任务均为 `COMPLETED`；FedAvg 与 FedProx 均生成 `FL_global_model.pt`。Agent 稳定性解读、三随机种子证据、mTLS 注册和隐私配置均可由 `/api/system/evidence` 返回。

本轮回归结果：18 项 Python 测试通过，前端测试通过，TypeScript 与 Vite 生产构建通过。

## 7. 仍然保留的限制

- 三个站点仍在同一台 Spark 上，不是三家真实医院；
- 使用合成数据，不是儿童胶质瘤临床效果验证；
- SVT 是更新过滤器配置级证据，不是完整患者级 DP-SGD 会计；
- 三个随机种子和单轮训练只能说明工程稳定性，不能支撑医学统计推断；
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

正式稳定性矩阵配置已升级为 5 个随机种子、5 种策略、3 个联邦轮次，共 25 项。当前 Spark 已持久化前 9 项；第 10 项暴露并促成了 Poisson 空批次修复。完整矩阵必须在断点续跑结束并生成 `complete=true` 的汇总后，才能替换本报告第 2 节的旧三种子数据。
