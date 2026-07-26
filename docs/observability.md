# Prometheus 与 OpenTelemetry

RareLink 可观测性默认关闭。启用时必须提供独立 Metrics Bearer Token；OTLP 非
loopback endpoint 必须使用 HTTPS，且 URL 不得包含账号、密码、query 或 fragment。

## 1. 配置

```env
RARELINK_OBSERVABILITY_ENABLED=true
RARELINK_METRICS_PATH=/internal/metrics
RARELINK_METRICS_BEARER_TOKEN=<至少32字符，由Secret Manager注入>
RARELINK_OTEL_ENABLED=true
RARELINK_OTEL_ENDPOINT=https://otel-gateway.example.org/v1/traces
RARELINK_OTEL_SERVICE_NAME=rarelink-coordinator
```

Prometheus 使用受保护文件读取 Token，示例见
[`deploy/observability/prometheus.yml`](../deploy/observability/prometheus.yml)。
Collector 示例见
[`deploy/observability/otel-collector.yml`](../deploy/observability/otel-collector.yml)。

## 2. 数据最小化

Prometheus 标签只包含：

- HTTP method；
- FastAPI 路由模板，例如 `/api/physical/jobs/{job_id}`；
- HTTP 状态码类别。

指标和 Span 不记录：

- 原始 URL 或 query；
- 实际 Study/Job/Site ID；
- Authorization、Cookie、Token；
- 请求体、响应体；
- 患者字段、数据路径或模型内容。

OpenTelemetry Span 只记录 service name/version/environment、method、路由模板和状态码。
OTLP 使用 BatchSpanProcessor，不因 Collector 暂时不可用阻塞主请求。

## 3. 运行指标

```text
rarelink_http_requests_total
rarelink_http_request_duration_seconds
rarelink_http_requests_in_progress
```

Metrics endpoint 不进入 OpenAPI，并返回 `Cache-Control: no-store`。认证失败返回 401，
不会回显 Token。

## 4. 正式验收边界

自动测试已证明鉴权、路由模板低基数和实际 Job ID 不进入 Prometheus 输出。生产前
仍需完成 Collector TLS、出口 allowlist、采样率、队列上限、告警、Dashboard、存储
保留和访问权限验收。可观测性不能收集患者级或影像级信息。
