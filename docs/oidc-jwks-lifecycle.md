# RareLink OIDC JWKS 受控生命周期

## 1. 文档目的

本文定义 RareLink 物理联邦控制面的 OIDC 签名公钥获取、缓存、轮换和故障处理边界。目标是在不把访问令牌、私钥或任意外部地址带入网络请求和日志的前提下，为医院身份提供方的公钥轮换建立可测试、可审计、默认拒绝的安全组件。

当前实现位于：

- `rarelink/security/jwks.py`：固定地址策略、无重定向 HTTPS transport、受控刷新器、内存缓存和公钥轮换；
- `rarelink/security/oidc.py`：从静态 JWKS 或受信 JWKS Provider 验证 JWT；
- `rarelink/config.py`：生命周期所需的最小、有界配置；
- `tests/test_jwks_lifecycle.py`：完全离线的网络、缓存、轮换和故障测试。

## 2. 已实现的安全不变量

### 2.1 固定信任边界

1. `issuer` 和 `jwks_uri` 必须是固定 HTTPS URL；
2. URL 禁止用户名、密码、查询参数和片段；
3. `jwks_uri` 必须与显式 allowlist 中的一项完全相同；
4. allowlist 中每个地址必须与 issuer 同协议、同主机、同端口；
5. 不解析在线 OIDC Discovery，不从令牌或 JWT Claim 构造网络地址；
6. 默认 transport 使用标准库 `HTTPSConnection` 直接建立 TLS 连接，不实现重定向；
7. transport 和底层连接工厂均可依赖注入，专项测试不会访问网络。

因此，攻击者不能通过 `iss`、`kid`、Header 或 Claim 引导 RareLink 访问任意地址。默认 transport 对 3xx 直接失败，不会读取 Location 或发起第二次请求。若医院因出口代理等原因替换 transport，替代实现必须保持相同的不重定向约束。

### 2.2 有界网络和解析

刷新请求携带以下边界：

- 请求超时：0.1–30 秒；
- 响应上限：1 KiB–4 MiB；
- 接受的成功状态：仅 HTTP 200；
- 接受的媒体类型：仅 `application/json` 或 `application/jwk-set+json`，默认 transport 对缺失媒体类型直接拒绝；
- JWKS 最多 100 个公钥；
- 仅接受明确的 RS256/RSA 或 ES256/EC 验签公钥；
- 拒绝重复、空白或超长 `kid`；
- 拒绝私钥参数以及对称密钥参数 `k`；
- 拒绝未包含 `verify` 的 `key_ops` 和非签名用途的 `use`。

transport 必须在读取响应流时执行字节上限，不能先无界下载再截断。`JWKSHTTPResponse.body` 的二次长度检查只是纵深防御。

### 2.3 缓存和轮换

启动阶段调用 `TrustedJWKSCache.preload()`。预加载失败时，OIDC 保护的服务不得进入就绪状态。

运行阶段遵循以下规则：

1. 当前缓存未过 TTL 且 `kid` 已知：直接使用内存中的公钥；
2. 缓存为空或 TTL 到期：刷新成功后继续，刷新失败则拒绝令牌；
3. `kid` 未知：只执行一次受控刷新；
4. 刷新后 `kid` 仍未知，或刷新失败：拒绝令牌；
5. 成功轮换中被移除的已知旧公钥：只在配置的短宽限窗口内继续可用；
6. 未曾成功加载的未知公钥不会进入宽限；
7. 相同 `kid` 被替换时，旧材料不会进入宽限，避免同一 `kid` 对应两个公钥；
8. 旧公钥宽限到期后，缓存会尝试一次刷新，仍未知则拒绝。

旧公钥宽限是为处理身份提供方轮换传播延迟，不是无限期 stale-if-error。TTL 到期后刷新失败时，即使令牌引用先前已知的公钥也会失败闭锁。

## 3. 配置

| 环境变量 | 默认值 | 约束 | 用途 |
|---|---:|---:|---|
| `RARELINK_OIDC_ISSUER` | 空 | 固定 HTTPS URL | 令牌 issuer |
| `RARELINK_OIDC_JWKS_URI` | 空 | 固定 HTTPS URL | 当前受信公钥地址 |
| `RARELINK_OIDC_JWKS_ALLOWED_URIS_JSON` | `[]` | 唯一字符串 JSON 数组 | 精确地址 allowlist |
| `RARELINK_OIDC_JWKS_TIMEOUT_SECONDS` | `3.0` | 0.1–30 | 单次请求超时 |
| `RARELINK_OIDC_JWKS_MAX_RESPONSE_BYTES` | `262144` | 1024–4194304 | 流式响应上限 |
| `RARELINK_OIDC_JWKS_CACHE_TTL_SECONDS` | `300` | 1–86400 | 当前 JWKS 缓存 TTL |
| `RARELINK_OIDC_JWKS_OLD_KEY_GRACE_SECONDS` | `120` | 0–3600 | 已知旧公钥短宽限 |

`RARELINK_OIDC_JWKS_JSON` 仍保留给当前静态、离线部署方式。在线刷新模式不应同时依赖静态 JSON 作为隐式降级源；模式切换必须由部署配置明确完成。

建议生产初始值：

```text
RARELINK_OIDC_JWKS_TIMEOUT_SECONDS=3
RARELINK_OIDC_JWKS_MAX_RESPONSE_BYTES=262144
RARELINK_OIDC_JWKS_CACHE_TTL_SECONDS=300
RARELINK_OIDC_JWKS_OLD_KEY_GRACE_SECONDS=120
```

具体 TTL 和宽限必须由医院 IdP 的轮换周期、令牌寿命和变更发布流程共同确定。

## 4. 启动接入合同

`rarelink/api/main.py` 已将动态 JWKS 接入 FastAPI 启动生命周期：仅在
`physical + oidc + jwks_uri` 模式构建 Provider，并在服务接受流量前执行
`preload()`。预加载失败会阻止进程启动；运行时鉴权使用同一 Provider，Ready Probe
只有在缓存已加载且仍新鲜时返回就绪。静态环境 JSON 仅保留为显式离线配置，不作为
动态刷新失败后的隐式降级源。

```python
provider = build_preloaded_jwks_provider(settings)
oidc = OfflineOIDCAdapter(claims_config, provider)
```

启动接线的验收条件：

1. 默认 transport 使用系统信任库验证证书链和主机名；
2. 如需医院 CA 或出口代理，应注入经过安全评审的 SSL Context/transport，并保持禁止重定向；
3. 响应流读取期间执行上限；
4. `preload()` 在服务变为 Ready 之前成功；
5. 预加载失败只上报安全错误类别，不输出地址、响应体、token、Claim 或 `kid`；
6. 多进程部署明确每个进程独立缓存，或另行实现受控共享缓存。

## 5. 密钥轮换运行手册

### 正常轮换

1. IdP 发布新公钥并保留旧公钥；
2. RareLink 在 TTL 到期或首次看见新 `kid` 时刷新；
3. 新公钥验证成功后开始签发新令牌；
4. 待旧令牌最大寿命结束后，IdP 移除旧公钥；
5. RareLink 对成功加载过、随后被移除的旧公钥仅保留短宽限；
6. 运维仅观察聚合状态和失败计数，不记录具体 `kid` 或令牌。

### 紧急吊销

短宽限不等同于吊销机制。若公钥对应私钥疑似泄露：

1. 停止相关 issuer 的 OIDC 入口或将宽限临时设为 0；
2. 由 IdP 吊销会话并停止签发；
3. 刷新 RareLink 进程以移除内存中的退休公钥；
4. 审查不含 token、Claim 和公钥材料的认证失败指标；
5. 完成安全审批后恢复服务。

正式生产还需引入 IdP 会话吊销或 token introspection 策略；当前离线 JWT 组件不能主动撤销一个尚未过期且签名仍有效的令牌。

## 6. 可观测性和秘密保护

`safe_status()` 只返回：

- 是否已加载；
- 是否仍在 TTL 内；
- 当前公钥数量；
- 宽限公钥数量；
- 明确的“未包含 JWK 材料”和“未包含 token”标志。

禁止记录：

- Authorization Header 或原始 JWT；
- JWT Header、Claim、subject、organization、site 列表；
- JWKS 响应体、公钥坐标和 `kid`；
- transport 异常原文；
- IdP 客户端秘密、私钥或刷新令牌。

生产指标建议只使用低基数类别，例如 `preload_failed`、`refresh_failed`、`unknown_key_rejected`、`cache_fresh`。

## 7. 离线验证

专项测试不访问网络：

```bash
python -m pytest tests/test_jwks_lifecycle.py tests/test_oidc.py tests/test_config.py
ruff check rarelink/security/jwks.py rarelink/security/oidc.py rarelink/config.py \
  tests/test_jwks_lifecycle.py tests/test_config.py
```

测试覆盖：

- HTTPS、同源和精确 allowlist；
- 默认 HTTPS transport 的证书验证、状态码、Content-Type、流式大小限制和 3xx 拒绝；
- 注入 transport 的超时和响应上限参数；
- Settings Builder、启动预加载与 TTL 刷新；
- 正常轮换和旧公钥短宽限；
- 未知 `kid` 的单次刷新；
- 刷新故障、缓存过期后的失败闭锁；
- 私钥、对称密钥、重复 key、错误媒体类型和超大响应拒绝；
- JWKS Provider 与 OIDC 验签端到端协作；
- 错误信息和日志不泄露 token、`kid` 或 transport 秘密。

## 8. 当前限制与后续任务

当前组件不是完整的生产 OIDC 接入，仍有以下明确限制：

1. 没有在线 Discovery；
2. 默认 transport 是直接 TLS 连接，医院代理和私有 CA 需要经过评审的显式适配；
3. 内存缓存不跨进程共享；
4. 没有令牌撤销、introspection 或连续访问评估；
5. 没有医院 IdP 联调和证书链演练；
6. 没有为刷新事件建立独立的低基数监控面板。

下一阶段应由安全评审批准医院出口策略并完成真实 IdP 轮换演练。未完成现场演练前，
只能声称动态 JWKS 软件路径和离线测试已经通过，不能声称医院生产身份系统已接入。
