# RareLink 正式发布工程

**适用版本：** Research Evidence Package v2 与 Research Operations Plane 之后的产品发布

**目标：** 让一个 Git tag 能够产生经过测试、扫描、签名、可追溯、支持 ARM64
且可离线交付的 RareLink 发布物。

## 1. 发布流水线

| 能力 | 实现 | 自动门 |
| --- | --- | --- |
| GitHub Actions CI | Python 3.11/3.12、Ruff、全仓测试、Web 测试/构建、生产镜像构建 | PR 与 main/codex 分支 push |
| 依赖漏洞扫描 | `pip-audit`、`npm audit --audit-level=high` | 高风险依赖导致 CI 失败 |
| 自动 Release | 语义版本 tag `v*.*.*` 触发 | tag 必须存在且格式正确 |
| 多架构容器 | Coordinator 与 Web 构建 `linux/amd64,linux/arm64` | 任一平台构建失败则不发布 |
| SBOM | Syft 生成 Source、Coordinator、Web 三份 SPDX JSON | SBOM 作为 Release 资产 |
| 镜像漏洞扫描 | Trivy 扫描源码及两个签名镜像 | HIGH/CRITICAL 使 Release 失败 |
| 容器签名 | Cosign GitHub OIDC keyless 签名不可变 digest | 不签名不进入 Release |
| Provenance | GitHub build provenance attestation | 镜像与离线包均生成证明 |
| ARM64 离线包 | ARM64 镜像归档、wheel、sdist、SBOM、漏洞报告、部署模板 | 缺一项即拒绝打包 |
| DGX Spark 原生镜像 | 独立 `workflow_dispatch`，要求原生 ARM64 DGX Spark Runner | QEMU 结果不能算 Spark 实机证据 |

CI 定义：

- [`.github/workflows/ci.yml`](../.github/workflows/ci.yml)
- [`.github/workflows/release.yml`](../.github/workflows/release.yml)
- [`.github/workflows/spark-arm64.yml`](../.github/workflows/spark-arm64.yml)
- [ARM64 构建合同](../deploy/release/arm64-build-contract.json)

## 2. Release 资产

正式 tag 发布应至少包含：

```text
rarelink-<version>-py3-none-any.whl
rarelink-<version>.tar.gz
source.spdx.json
coordinator.spdx.json
web.spdx.json
trivy-source.sarif
trivy-coordinator.json
trivy-web.json
rarelink-coordinator-arm64.tar
rarelink-web-arm64.tar
rarelink-<version>-linux-arm64-offline.tar.gz
SHA256SUMS.release
```

容器镜像发布至 GHCR，但部署清单应固定 `image@sha256:...`，不能只依赖可变 tag。
Cosign 公钥不随包自建信任；keyless 验证应固定 GitHub repository、workflow identity
和 OIDC issuer。

示例：

```bash
cosign verify \
  --certificate-identity-regexp \
  '^https://github.com/dingyucanada/RareLink/.github/workflows/release.yml@refs/tags/v' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  ghcr.io/dingyucanada/rarelink-coordinator@sha256:<digest>
```

## 3. ARM64 与 DGX Spark 边界

Coordinator 与 Web 不需要 GPU，使用 GitHub Buildx/QEMU 验证 AMD64 与 ARM64。
Spark 训练镜像依赖 NVIDIA NGC、CUDA、驱动和 GB10 运行时；它只能在原生 DGX
Spark ARM64 Runner 上关闭“Spark 镜像实机发布”门。

因此：

- GitHub hosted ARM64/QEMU 构建可以证明通用控制面镜像可构建；
- 不能用 QEMU 构建声称 CUDA、NVFLARE 或 MONAI 已在 DGX Spark 运行；
- 原生工作流首先检查 `uname -m=aarch64`，再构建、推送、签名和生成 SBOM；
- 自托管 Runner 只接受人工 `workflow_dispatch`，不执行来自 PR 的不受信代码。

## 4. 离线安装包

离线包生成器要求八类 reviewed artifacts 齐全：

```bash
python scripts/build_offline_release_bundle.py \
  --version v0.2.0 \
  --artifact python-wheel=dist/rarelink-0.2.0-py3-none-any.whl \
  --artifact python-sdist=dist/rarelink-0.2.0.tar.gz \
  --artifact coordinator-arm64-image=dist/rarelink-coordinator-arm64.tar \
  --artifact web-arm64-image=dist/rarelink-web-arm64.tar \
  --artifact source-sbom=dist/source.spdx.json \
  --artifact coordinator-sbom=dist/coordinator.spdx.json \
  --artifact web-sbom=dist/web.spdx.json \
  --artifact vulnerability-report=dist/vulnerability-reports.tar.gz \
  --output rarelink-v0.2.0-linux-arm64-offline.tar.gz
```

包内含 `release-manifest.json` 与 `SHA256SUMS`，不含医院配置、证书、密钥、患者数据
或已填写的环境文件。安装前必须先在联网发布环境验证 Cosign 身份与 digest，再导出
镜像归档。大体积离线包应通过组织方允许的网盘、对象存储或专用传输介质交付，不使用
共享 Spark 的 SSH 链路上传。

## 5. 当前已验证与尚未形成的证据

已完成：

- 发布合同静态验证及负向测试；
- 离线包确定性生成、缺件与符号链接阻断测试；
- PostgreSQL 备份恢复执行器的隔离工具测试；
- Prometheus 鉴权、低基数标签和敏感 ID 不泄露测试；
- 全仓软件回归；
- 2026-07-26 的 [GitHub Actions CI run 30187556875](https://github.com/dingyucanada/RareLink/actions/runs/30187556875)
  已通过全部 5 个作业，包括 Python 3.11/3.12、Web、依赖/发布合同和
  `linux/amd64` / `linux/arm64` 通用生产镜像构建。

仍需外部运行：

- 创建真实 release tag 后的 GHCR push、Cosign 签名、SBOM 和 Trivy 收据；
- 原生 DGX Spark self-hosted Runner 构建；
- 目标医院 PostgreSQL 的真实备份恢复演练；
- 目标 Prometheus 与 OTLP Collector 的网络、TLS、容量和保留策略验收。

当前已知发布阻断：

- 截至本次实现时，NVIDIA FLARE `2.8.1` 仍在包元数据中严格依赖 Flask `3.0.2`；
  漏洞数据库将其标记为需要升级到 Flask `3.1.3`，但直接覆盖会造成依赖合同不一致。
- 通用 Coordinator/Web 镜像不安装 NVFLARE，因此不受该问题影响；
- 原生 DGX Spark 镜像的 Trivy 门保持 HIGH/CRITICAL 失败关闭，不设置 ignore；
- 只有 NVIDIA 上游解除固定、或经独立审批的补丁 wheel 完成兼容/安全复核后，才能
  发布新的签名 Spark 生产镜像。历史 NVFLARE `2.7.2` 实机证据保持原样，不被改写。

这些外部项没有运行收据前，仓库只声称“发布工程已实现并通过本地合同测试”，不声称
正式生产 Release 已发布。
