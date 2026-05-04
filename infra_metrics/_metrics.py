"""
Request-level Prometheus metrics: count, latency, and error rate.
"""

from prometheus_client import Counter, Gauge, Histogram

ACTIVE_AGENTS = Gauge(
    "active_agents_total",
    "Number of agents currently executing (in-flight requests)",
    ["service", "endpoint"],
)

REQUEST_COUNT = Counter(
    "service_requests_total",
    "Total requests",
    ["service", "endpoint", "status"],  # status = "ok" | "error"
)

REQUEST_LATENCY = Histogram(
    "service_request_latency_seconds",
    "End-to-end request latency (s)",
    ["service", "endpoint"],
    # Buckets tuned for ML inference workloads (ms → tens of seconds)
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30],
)

ERROR_COUNT = Counter(
    "service_errors_total",
    "Total unhandled exceptions per endpoint",
    ["service", "endpoint", "exception_type"],
)
