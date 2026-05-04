"""
System-level metrics: CPU and RAM, captured per request.
"""

import psutil
from prometheus_client import Gauge

CPU_USAGE = Gauge(
    "cpu_usage_percent",
    "Process CPU usage (%)",
    ["service", "endpoint"],
)
RAM_USAGE = Gauge(
    "ram_usage_mb",
    "Process RSS memory usage (MB)",
    ["service", "endpoint"],
)


def record_system_metrics(service: str, endpoint: str) -> None:
    """
    Push current CPU% and RSS memory to Prometheus.

    Uses process-level RSS (via psutil.Process) rather than system-wide
    virtual_memory so per-service numbers are accurate when multiple
    services run on the same host.
    """
    proc = psutil.Process()
    CPU_USAGE.labels(service, endpoint).set(proc.cpu_percent(interval=None))
    RAM_USAGE.labels(service, endpoint).set(proc.memory_info().rss / 1024 / 1024)
