"""
infra_metrics/_metrics.py
Centralised Prometheus metric definitions.
All metrics defined once; re-import safe (catches duplicate-registration ValueError).
"""

from prometheus_client import Counter, Gauge, Histogram, REGISTRY


def _g(name: str, doc: str, labels: list) -> Gauge:
    try:
        return Gauge(name, doc, labels)
    except ValueError:
        return REGISTRY._names_to_collectors.get(name)  # type: ignore[return-value]


def _c(name: str, doc: str, labels: list) -> Counter:
    try:
        return Counter(name, doc, labels)
    except ValueError:
        return REGISTRY._names_to_collectors.get(name)  # type: ignore[return-value]


def _h(name: str, doc: str, labels: list, buckets=None) -> Histogram:
    kw = {"buckets": buckets} if buckets else {}
    try:
        return Histogram(name, doc, labels, **kw)
    except ValueError:
        return REGISTRY._names_to_collectors.get(name)  # type: ignore[return-value]


# ── Per-service × endpoint ──────────────────────────────────────────────────
_SE = ["service", "endpoint"]

ACTIVE_AGENTS       = _g("active_agents_total",              "Currently active agents/requests",     _SE)
PEAK_ACTIVE_AGENTS  = _g("peak_active_agents_total",         "Peak concurrent agents ever seen",      _SE)
REQUEST_COUNT       = _c("service_requests_total",           "Total requests handled",                _SE)
ERROR_COUNT         = _c("service_errors_total",             "Total errors raised",                   _SE)
REQUEST_LATENCY     = _h(
    "service_request_latency_seconds", "Request latency in seconds", _SE,
    buckets=[.005, .01, .025, .05, .1, .25, .5, 1.0, 2.5, 5.0, 10.0],
)

# ── Per-service system resources ────────────────────────────────────────────
CPU_USAGE  = _g("cpu_usage_percent_service", "Process CPU usage percent",   ["service"])
RAM_USAGE  = _g("ram_usage_mb_service",      "Process RSS memory in MB",    ["service"])

# ── GPU metrics ─────────────────────────────────────────────────────────────
# Background-polled (true utilisation, not just before/after snapshot)
GPU_UTIL_TRUE = _g("true_gpu_utilization_percent", "GPU util % (background polled every 2 s)", ["service"])
GPU_POWER     = _g("gpu_power_watts",              "GPU power draw in watts (background polled)", ["service"])

# Per-request snapshots
GPU_UTIL      = _g("gpu_utilization_percent", "GPU util % at request stage", _SE + ["stage"])
GPU_MEM_USED  = _g("gpu_memory_used_mb",      "GPU VRAM used in MB at request stage", _SE + ["stage"])
GPU_MEM_DELTA = _g("gpu_memory_delta_mb",     "VRAM delta (after − before) per request", _SE)