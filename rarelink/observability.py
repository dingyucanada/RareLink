"""Low-cardinality Prometheus metrics and privacy-bounded OpenTelemetry traces."""

from __future__ import annotations

import secrets
import time
from contextlib import nullcontext
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse

from rarelink import __version__
from rarelink.config import Settings


class ObservabilityConfigurationError(RuntimeError):
    """Production observability was enabled without its reviewed runtime."""


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    value = getattr(route, "path", None)
    if isinstance(value, str) and value.startswith("/"):
        return value
    return "unmatched"


def _authorized(request: Request, expected_token: str) -> bool:
    header = request.headers.get("Authorization", "")
    scheme, separator, token = header.partition(" ")
    return bool(
        separator
        and scheme.lower() == "bearer"
        and secrets.compare_digest(token, expected_token)
    )


def configure_observability(app: FastAPI, settings: Settings) -> None:
    """Attach one internal metrics endpoint and optional OTLP trace exporter."""
    if not settings.rarelink_observability_enabled:
        app.state.rarelink_observability_enabled = False
        return
    try:
        from prometheus_client import (
            CollectorRegistry,
            Counter,
            Gauge,
            Histogram,
            generate_latest,
        )
    except ImportError as exc:
        raise ObservabilityConfigurationError(
            "prometheus-client is required when observability is enabled"
        ) from exc

    registry = CollectorRegistry()
    requests = Counter(
        "rarelink_http_requests_total",
        "Completed HTTP requests.",
        ("method", "route", "status_class"),
        registry=registry,
    )
    duration = Histogram(
        "rarelink_http_request_duration_seconds",
        "HTTP request duration without raw URL labels.",
        ("method", "route"),
        registry=registry,
        buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
    )
    in_progress = Gauge(
        "rarelink_http_requests_in_progress",
        "HTTP requests currently executing.",
        registry=registry,
    )

    tracer: Any = None
    provider: Any = None
    if settings.rarelink_otel_enabled:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
        except ImportError as exc:
            raise ObservabilityConfigurationError(
                "OpenTelemetry SDK and OTLP HTTP exporter are required"
            ) from exc
        provider = TracerProvider(
            resource=Resource.create(
                {
                    "service.name": settings.rarelink_otel_service_name,
                    "service.version": __version__,
                    "deployment.environment": settings.app_env,
                }
            )
        )
        provider.add_span_processor(
            BatchSpanProcessor(
                OTLPSpanExporter(endpoint=settings.rarelink_otel_endpoint),
            )
        )
        tracer = provider.get_tracer("rarelink.http", __version__)

    @app.middleware("http")
    async def observe_request(request: Request, call_next):  # type: ignore[no-untyped-def]
        if request.url.path == settings.rarelink_metrics_path:
            return await call_next(request)
        started = time.perf_counter()
        in_progress.inc()
        span_context = (
            tracer.start_as_current_span("rarelink.http.request")
            if tracer is not None
            else nullcontext()
        )
        status_code = 500
        try:
            with span_context as span:
                response = await call_next(request)
                status_code = response.status_code
                route = _route_template(request)
                if span is not None:
                    span.update_name(f"{request.method} {route}")
                    span.set_attribute("http.request.method", request.method)
                    span.set_attribute("http.route", route)
                    span.set_attribute("http.response.status_code", status_code)
                return response
        finally:
            route = _route_template(request)
            requests.labels(
                request.method,
                route,
                f"{status_code // 100}xx",
            ).inc()
            duration.labels(request.method, route).observe(
                time.perf_counter() - started
            )
            in_progress.dec()

    async def metrics_endpoint(request: Request) -> PlainTextResponse:
        if not _authorized(request, settings.rarelink_metrics_bearer_token):
            return PlainTextResponse(
                "metrics authentication required\n",
                status_code=401,
                headers={"Cache-Control": "no-store"},
            )
        return PlainTextResponse(
            generate_latest(registry),
            media_type="text/plain; version=0.0.4; charset=utf-8",
            headers={"Cache-Control": "no-store"},
        )

    app.add_api_route(
        settings.rarelink_metrics_path,
        metrics_endpoint,
        methods=["GET"],
        include_in_schema=False,
    )
    app.state.rarelink_observability_enabled = True
    app.state.rarelink_metrics_registry = registry
    app.state.rarelink_tracer_provider = provider


def shutdown_observability(app: FastAPI) -> None:
    provider = getattr(app.state, "rarelink_tracer_provider", None)
    if provider is not None:
        provider.shutdown()
