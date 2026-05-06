"""
GPU metrics via NVML.

- Safe to import on CPU-only machines (NVML_AVAILABLE = False → all calls are no-ops)
- Merges gpu_metrics.py + gpu_profiler.py into one coherent module
- Exposes both a functional API (gpu_before / gpu_after) and a context-manager (GPUProfiler)
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Generator

from prometheus_client import Gauge

logger = logging.getLogger(__name__)

# ── NVML init (safe) ─────────────────────────────────────────────────────────

try:
    import pynvml  # optional dependency

    pynvml.nvmlInit()
    NVML_AVAILABLE = True
except Exception:  # ImportError OR NVMLError
    NVML_AVAILABLE = False
    logger.debug("pynvml not available – GPU metrics disabled")

# ── Prometheus gauges ─────────────────────────────────────────────────────────

_LABEL_NAMES = ["service", "endpoint", "stage"]

GPU_UTIL = Gauge(
    "gpu_utilization_percent",
    "GPU utilisation (%)",
    _LABEL_NAMES,
)
GPU_MEM = Gauge(
    "gpu_memory_used_mb",
    "GPU memory used (MB)",
    _LABEL_NAMES,
)
GPU_MEM_DELTA = Gauge(
    "gpu_memory_delta_mb",
    "GPU VRAM delta for a single request (MB)",
    ["service", "endpoint"],
)
GPU_POWER_WATTS = Gauge(
    "gpu_power_watts",
    "GPU power draw (W) via NVML — 0 if unsupported",
    ["service"],
)

# ── Internal snapshot ─────────────────────────────────────────────────────────


def _snapshot(device_index: int) -> tuple[float, float, float]:
    """Return (utilisation_pct, vram_used_mb, power_watts) or (0, 0, 0) if NVML unavailable."""
    if not NVML_AVAILABLE:
        return 0.0, 0.0, 0.0
    try:
        handle = pynvml.nvmlDeviceGetHandleByIndex(device_index)
        util = pynvml.nvmlDeviceGetUtilizationRates(handle).gpu
        mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
        try:
            power_w = pynvml.nvmlDeviceGetPowerUsage(handle) / 1000.0  # mW → W
        except Exception:
            power_w = 0.0
        return float(util), mem_info.used / 1024 / 1024, power_w
    except Exception as exc:  # device disappeared, driver error, etc.
        logger.warning("GPU snapshot failed: %s", exc)
        return 0.0, 0.0, 0.0


def _record(service: str, endpoint: str, stage: str, device_index: int) -> float:
    """Snapshot + push to Prometheus. Returns vram_mb for delta arithmetic."""
    util, mem, power_w = _snapshot(device_index)
    GPU_UTIL.labels(service, endpoint, stage).set(util)
    GPU_MEM.labels(service, endpoint, stage).set(mem)
    # Record power at every "after" snapshot (one reading per completed request)
    if stage == "after" and power_w > 0:
        GPU_POWER_WATTS.labels(service).set(power_w)
    return mem


# ── Public functional API ─────────────────────────────────────────────────────


def gpu_before(service: str, endpoint: str, device_index: int = 0) -> float:
    """Record pre-request GPU state. Returns VRAM (MB) for delta calculation."""
    return _record(service, endpoint, "before", device_index)


def gpu_after(service: str, endpoint: str, before_mem_mb: float, device_index: int = 0) -> None:
    """Record post-request GPU state and push VRAM delta."""
    after_mem = _record(service, endpoint, "after", device_index)
    GPU_MEM_DELTA.labels(service, endpoint).set(after_mem - before_mem_mb)


# ── Context-manager / class API ───────────────────────────────────────────────


class GPUProfiler:
    """
    Wraps a block of code with before/after GPU recording.

    Usage (manual):
        profiler = GPUProfiler(service="svc", endpoint="predict")
        profiler.start()
        ...
        profiler.stop()

    Usage (context manager):
        with GPUProfiler(service="svc", endpoint="predict"):
            ...

    Usage (decorator helper — prefer @track() instead):
        @GPUProfiler.decorator(service="svc")
        def predict(...): ...
    """

    def __init__(self, service: str, endpoint: str, device_index: int = 0) -> None:
        self.service = service
        self.endpoint = endpoint
        self.device_index = device_index
        self._before_mem: float = 0.0

    def start(self) -> None:
        self._before_mem = gpu_before(self.service, self.endpoint, self.device_index)

    def stop(self) -> None:
        gpu_after(self.service, self.endpoint, self._before_mem, self.device_index)

    # context-manager support
    def __enter__(self) -> "GPUProfiler":
        self.start()
        return self

    def __exit__(self, *_) -> None:
        self.stop()


@contextmanager
def gpu_profile(service: str, endpoint: str, device_index: int = 0) -> Generator:
    """Functional context manager alias for GPUProfiler."""
    p = GPUProfiler(service, endpoint, device_index)
    p.start()
    try:
        yield p
    finally:
        p.stop()