"""
infra-metrics
=============
Unified Prometheus observability for Python services.

Tracks per-request:
  • request count + error rate
  • latency histogram
  • CPU % and RSS memory
  • GPU utilisation and VRAM delta  (requires pynvml, gracefully skipped otherwise)

Quickstart
----------
    from infra_metrics import configure, track
    from infra_metrics.server import start_metrics_server

    configure(service="my-service", env="prod")
    start_metrics_server(port=8000)

    @track()
    async def predict(payload):
        ...

    @track(endpoint="health")
    def health_check():
        ...
"""

from .config import configure, get_config
from .decorator import track
from ._gpu import (
    NVML_AVAILABLE,
    GPUProfiler,
    gpu_before,
    gpu_after,
    gpu_profile,
)
from ._system import record_system_metrics
from ._metrics import REQUEST_COUNT, REQUEST_LATENCY, ERROR_COUNT

__all__ = [
    # config
    "configure",
    "get_config",
    # decorator (main entrypoint)
    "track",
    # gpu
    "NVML_AVAILABLE",
    "GPUProfiler",
    "gpu_before",
    "gpu_after",
    "gpu_profile",
    # system
    "record_system_metrics",
    # raw prometheus objects (advanced use)
    "REQUEST_COUNT",
    "REQUEST_LATENCY",
    "ERROR_COUNT",
]
