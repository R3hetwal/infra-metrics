"""
infra_metrics/_gpu.py

GPU helpers built on pynvml.
  - gpu_before() / gpu_after()  — per-request VRAM + util snapshots
  - start_gpu_background()      — background thread: true GPU util % + power watts
                                  polled every 2 s, exposed as per-service metrics

All functions are safe to call when pynvml is unavailable or when
device_index is None — they simply become no-ops / return None.
"""

from __future__ import annotations

import threading
import time
from typing import Optional

try:
    import pynvml

    pynvml.nvmlInit()
    _NVML_OK = True
except Exception:
    _NVML_OK = False

from infra_metrics._metrics import (
    GPU_MEM_DELTA,
    GPU_MEM_USED,
    GPU_POWER,
    GPU_UTIL,
    GPU_UTIL_TRUE,
)

# ── Internal state ──────────────────────────────────────────────────────────
_bg_threads: dict[tuple, threading.Thread] = {}
_bg_stop: dict[tuple, threading.Event] = {}


# ── Low-level nvml helpers ──────────────────────────────────────────────────

def _handle(device_index: int):
    if not _NVML_OK:
        return None
    try:
        return pynvml.nvmlDeviceGetHandleByIndex(device_index)
    except Exception:
        return None


def _read_mem_mb(device_index: int) -> Optional[float]:
    h = _handle(device_index)
    if h is None:
        return None
    try:
        info = pynvml.nvmlDeviceGetMemoryInfo(h)
        return info.used / 1024 / 1024
    except Exception:
        return None


def _read_util_pct(device_index: int) -> Optional[float]:
    h = _handle(device_index)
    if h is None:
        return None
    try:
        rates = pynvml.nvmlDeviceGetUtilizationRates(h)
        return float(rates.gpu)
    except Exception:
        return None


def _read_power_w(device_index: int) -> Optional[float]:
    h = _handle(device_index)
    if h is None:
        return None
    try:
        return pynvml.nvmlDeviceGetPowerUsage(h) / 1000.0  # mW → W
    except Exception:
        return None


# ── Background polling thread ───────────────────────────────────────────────

def _bg_poll(service: str, device_index: int, stop: threading.Event) -> None:
    """
    Polls GPU every 2 s and updates:
      true_gpu_utilization_percent{service=X}
      gpu_power_watts{service=X}

    These give the dashboard a continuous read of true GPU load even when
    no request is actively in-flight.
    """
    while not stop.wait(2.0):
        util = _read_util_pct(device_index)
        power = _read_power_w(device_index)
        if util is not None:
            GPU_UTIL_TRUE.labels(service=service).set(util)
        if power is not None:
            GPU_POWER.labels(service=service).set(power)


def start_gpu_background(service: str, device_index: int) -> None:
    """Start (or restart) the background GPU polling thread for a service."""
    key = (service, device_index)
    existing = _bg_threads.get(key)
    if existing and existing.is_alive():
        return
    stop = threading.Event()
    _bg_stop[key] = stop
    t = threading.Thread(
        target=_bg_poll,
        args=(service, device_index, stop),
        daemon=True,
        name=f"gpu-bg-{service}-dev{device_index}",
    )
    t.start()
    _bg_threads[key] = t


def stop_gpu_background(service: str, device_index: int) -> None:
    """Signal the background thread to stop (usually not needed — daemon thread)."""
    key = (service, device_index)
    if key in _bg_stop:
        _bg_stop[key].set()


# ── Per-request helpers (used by @track and manual wrapping) ─────────────────

def gpu_before(
    service: str,
    endpoint: str,
    device_index: int,
) -> Optional[float]:
    """
    Call just before the work begins.
    Records VRAM used + GPU util at the 'before' stage.
    Returns current VRAM in MB (pass to gpu_after as before_mem_mb).
    """
    mem = _read_mem_mb(device_index)
    util = _read_util_pct(device_index)
    if mem is not None:
        GPU_MEM_USED.labels(service=service, endpoint=endpoint, stage="before").set(mem)
    if util is not None:
        GPU_UTIL.labels(service=service, endpoint=endpoint, stage="before").set(util)
    return mem


def gpu_after(
    service: str,
    endpoint: str,
    before_mem_mb: Optional[float],
    device_index: int,
) -> None:
    """
    Call just after the work finishes (or in a finally block).
    Records VRAM used + GPU util at 'after' stage, and VRAM delta.

    Note for streaming endpoints: call this inside the generator's finally
    block (after the last chunk), not after StreamingResponse() construction.
    """
    mem = _read_mem_mb(device_index)
    util = _read_util_pct(device_index)
    if mem is not None:
        GPU_MEM_USED.labels(service=service, endpoint=endpoint, stage="after").set(mem)
    if util is not None:
        GPU_UTIL.labels(service=service, endpoint=endpoint, stage="after").set(util)
    if mem is not None and before_mem_mb is not None:
        GPU_MEM_DELTA.labels(service=service, endpoint=endpoint).set(
            mem - before_mem_mb
        )