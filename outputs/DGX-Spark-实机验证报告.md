# RareLink DGX Spark 实机验证报告

验证日期：2026-07-16  
验证性质：黑客松工程验证，全部训练数据为程序生成的非临床合成数据。

> 本报告不记录公网 IP、SSH 端口、用户名、密码或 API Key。公开提交前应再次执行敏感信息扫描。

## 1. 验证结论

RareLink 已在真实 NVIDIA DGX Spark 上完成以下闭环：

1. ARM64、GB10、CUDA、Docker 与统一内存环境检查；
2. CUDA PyTorch GPU kernel 实际执行；
3. 三逻辑站点、四模态合成 NIfTI 数据生成；
4. MONAI 3D SegResNet 单站点 GPU 训练与模型持久化；
5. NVIDIA FLARE 2.7.2 三站点 FedAvg 聚合；
6. NVIDIA FLARE 2.7.2 三站点 FedProx 聚合；
7. FastAPI 控制平面发起后台训练任务并回写指标；
8. React 前端构建、API 代理和赛事公网端口访问。

本次验证证明了项目的工程链路真实可运行，但不证明临床有效性，也不等同于三家医院的真实部署。

## 2. 实机环境

| 项目 | 实测结果 |
| --- | --- |
| 硬件型号 | NVIDIA DGX Spark |
| GPU | NVIDIA GB10 |
| 架构 | `aarch64` / ARM64 |
| 操作系统 | Ubuntu 24.04.3 LTS |
| Kernel | `6.11.0-1014-nvidia` |
| NVIDIA Driver | `580.82.09` |
| CUDA Toolkit | 13.0，`nvcc 13.0.88` |
| 系统内存 | 119 GiB 可见，验证前约 116 GiB available |
| 系统盘 | 3.7 TB，总可用空间约 2.4 TB |
| Docker | 29.2.1，ARM64，overlay2 |
| Python | 容器内 Python 3.12.12 |
| PyTorch | 2.10.0+cu130 |
| MONAI | 1.6.0 |
| NVIDIA FLARE | 2.7.2 |

当前赛事账号未加入 Docker 用户组，验证使用 `sudo docker`，未修改宿主机用户组或 daemon 权限。

## 3. CUDA 验证

容器内结果：

```text
architecture=aarch64
torch=2.10.0+cu130
cuda_available=True
gpu=NVIDIA GB10
device_capability=(12, 1)
```

除 `torch.cuda.is_available()` 外，还执行了 4096×4096 CUDA 矩阵乘法，kernel 正常完成。

当前缓存容器内的 PyTorch 报告其正式支持范围上限为 compute capability 12.0，而 GB10 返回 12.1；矩阵乘法、MONAI 训练和 NVFLARE 客户端训练均已实际运行成功，但该警告不能被忽略。正式交付应在 Docker 网络恢复后改用 NVIDIA 为 DGX Spark 推荐的最新 NGC PyTorch 镜像，并重新执行完整回归。

## 4. MONAI 单站点 GPU 冒烟

配置：

- 站点：`site-a`；
- 输入：4 个合成病例，3 个训练、1 个验证；
- 影像：四模态 32×32×32 NIfTI；
- 模型：MONAI 3D SegResNet；
- 轮次：1 epoch；
- 设备：CUDA。

结果：

| 指标 | 结果 |
| --- | ---: |
| Epoch loss | 1.844093 |
| Mean foreground Dice | 0.037142 |
| HD95 | 14.123105 |
| 模型产物 | 已生成 `.pt` 文件 |

这些指标只证明数据管道、模型、损失、评估和 GPU 路径完整。极小合成数据和单轮训练的数值不能解释为医学性能。

## 5. NVIDIA FLARE FedAvg

配置：三个逻辑站点、1 个联邦轮次、每站点 1 个本地 epoch、统一内存保护下串行训练。

FLARE 日志确认：

```text
Sampled clients: ['site-a', 'site-b', 'site-c']
Aggregated 1/3 results
Aggregated 2/3 results
Aggregated 3/3 results
Finished FedAvg
```

结果：

| 指标 | 结果 |
| --- | ---: |
| Mean Dice | 0.074098 |
| Worst-site Dice | 0.064549 |
| Site Dice std | 0.013415 |
| Mean HD95 | 18.097708 |
| 全局模型 | `FL_global_model.pt` 已生成 |

## 6. NVIDIA FLARE FedProx

配置：三个逻辑站点、1 个联邦轮次、每站点 1 个本地 epoch、`mu=0.01`。

结果：

| 指标 | 结果 |
| --- | ---: |
| Mean Dice | 0.026749 |
| Worst-site Dice | 0.023887 |
| Site Dice std | 0.002032 |
| Mean HD95 | 15.575719 |
| 全局模型 | `FL_global_model.pt` 已生成 |

单轮随机初始化不能用于判断 FedAvg 与 FedProx 的优劣。比赛演示只应说明系统支持差异化策略以及最弱站点分析；正式比较需要固定随机种子、增加轮次并进行重复实验。

## 7. 控制平面端到端验证

验证不是直接运行训练脚本，而是通过 RareLink 控制平面完成：

```text
创建研究
→ 生成研究协议
→ 人工批准
→ 可行性检查
→ Agent 提出实验合同
→ 人工锁定合同
→ 创建 FedAvg 实验
→ 后台任务进入统一内存队列
→ NVFLARE 三站点训练与聚合
→ 指标回写
→ 研究进入 RESULTS_REVIEW
```

最终结果：

| 字段 | 结果 |
| --- | --- |
| Training job status | `COMPLETED` |
| Progress | 100% |
| Backend | `nvflare` |
| Study status | `RESULTS_REVIEW` |
| Mean Dice | 0.104327 |
| Worst-site Dice | 0.087986 |
| Site Dice std | 0.015517 |
| HD95 | 14.908172 |

该结果证明 API、数据库状态机、后台任务、训练子进程、模型产物和指标血缘已经打通。

## 8. 前后端服务验证

Spark 内网服务：

- React/Vite：8888；
- FastAPI：9000；
- API health：`/api/health`；
- Swagger：`/docs`。

赛事公网映射的前端首页返回 HTTP 200，公网 API health 返回：

```json
{"status":"ok","service":"rarelink"}
```

前端的 `/api` 代理也已验证通过。代理目标现由 `RARELINK_API_PROXY` 配置，本地默认 8000，Spark 演示使用 9000。

## 9. 节点问题与处理

### Docker 代理不可用

Docker daemon 被配置为使用 `127.0.0.1:7890` HTTP/HTTPS 代理，但该代理服务未运行，因此无法从 NGC 拉取新镜像。

本次处理：

- 不修改共享节点的 daemon 配置；
- 复用节点已有的 ARM64 CUDA 13 容器；
- 使用国内 Python 镜像下载开源依赖；
- 将通过验证的运行环境固化为节点本地镜像；
- 在仓库中增加 `deploy/Dockerfile.spark`，待代理恢复后使用官方 NGC PyTorch 基础镜像重建。

### Docker 权限

赛事账号只有 `sudo` 权限而无 Docker socket 权限。本次使用 `sudo docker`，未执行 `usermod`，避免影响共享机器。

## 10. 安全措施

- 仅上传 227KB 脱敏源码包；
- 排除 `.env`、虚拟环境、`node_modules`、数据库、数据、模型和训练产物；
- 未向 Spark 上传真实患者数据；
- 未将 SSH 密码或 Step API Key 写入文件；
- Spark 当前未配置 Step Key，Agent 使用确定性本地模板；
- API Key 只应通过节点 `.env` 注入，演示结束后移除并轮换；
- 数据库、NIfTI 和全局模型保留在 Spark，不提交 Git。

## 11. 尚未完成的验证

1. 两台或以上 DGX Spark 的真实跨节点 FLARE 通信；
2. 官方推荐 NGC PyTorch 镜像上的完整回归；
3. 多轮、固定种子、重复实验和资源占用基准；
4. 真实医院网络、身份、证书和安全策略；
5. DICOM/DICOMweb、FHIR 或 PACS 接入；
6. 正式授权数据上的科研有效性评估；
7. Step 3.7 在线 Agent 在 Spark 演示环境中的脱敏调用复验。

因此，当前最准确的表述是：

> RareLink 已在一台真实 DGX Spark 上完成三逻辑站点的 GPU 联邦科研闭环；它是可运行的比赛原型和科研基础设施验证，不是已完成临床验证的多医院生产系统。

