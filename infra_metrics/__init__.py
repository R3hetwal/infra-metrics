"""
infra_metrics/__init__.py

Public API:
  @track()          — decorator; one line per endpoint, handles everything
  gpu_before()      — manual GPU snapshot before (for streaming endpoints)
  gpu_after()       — manual GPU snapshot after  (for streaming endpoints)
  get_config()      — access resolved ServiceConfig
  set_config()      — override config programmatically

@track() auto-tracks:
  ✓ Active agents + peak agents (concurrent requests in-flight)
  ✓ Request count
  ✓ Error count
  ✓ Request latency (histogram)
  ✓ Process CPU % + RSS RAM
  ✓ GPU util % snapshot before/after   ← only if device_index set in services.yaml
  ✓ VRAM used before/after
  ✓ VRAM delta (after − before)
  ✓ Background true GPU util % + power watts polled every 2 s

STREAMING ENDPOINTS (StreamingResponse / generator):
  @track() wraps the *construction* of the response, not the stream lifetime.
  Use the manual pattern (see docs/streaming.md) so GPU/agent metrics
  stay accurate for the full stream duration — exactly as in xtts.
"""

from __future__ import annotations

import functools
import os
import time
from typing import Any, Callable

import psutil

from infra_metrics._gpu import gpu_after, gpu_before, start_gpu_background
from infra_metrics._metrics import (
    ACTIVE_AGENTS,
    CPU_USAGE,
    ERROR_COUNT,
    PEAK_ACTIVE_AGENTS,
    RAM_USAGE,
    REQUEST_COUNT,
    REQUEST_LATENCY,
)
from infra_metrics.config import get_config, load_config, set_config  # re-export

__all__ = [
    "track",
    "gpu_before",
    "gpu_after",
    "get_config",
    "set_config",
    "load_config",
]

_proc = psutil.Process(os.getpid())
_peak: dict[str, int] = {}           # key → peak agent count seen


def _record_sys(service: str) -> None:
    CPU_USAGE.labels(service=service).set(_proc.cpu_percent(interval=None))
    RAM_USAGE.labels(service=service).set(_proc.memory_info().rss / 1024 / 1024)


def _update_peak(service: str, endpoint: str) -> None:
    key = f"{service}:{endpoint}"
    cur = int(ACTIVE_AGENTS.labels(service=service, endpoint=endpoint)._value.get())
    if cur > _peak.get(key, 0):
        _peak[key] = cur
        PEAK_ACTIVE_AGENTS.labels(service=service, endpoint=endpoint).set(cur)


def track() -> Callable:
    """
    FastAPI endpoint decorator.  Zero config — reads device_index from
    services.yaml via get_config().

    Usage:
        @app.post("/infer")
        @track()
        async def infer(request: Request, text: str):
            ...

    For streaming endpoints keep using the manual gpu_before/gpu_after
    pattern inside the generator body (see xtts example / docs/streaming.md).
    """

    def decorator(fn: Callable) -> Callable:
        _gpu_started = False  # start bg thread only once per decorated fn

        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            nonlocal _gpu_started

            cfg = get_config()
            svc = cfg.service
            ep  = fn.__name__
            dev = cfg.device_index

            # Start background GPU thread once, lazily
            if dev is not None and not _gpu_started:
                start_gpu_background(svc, dev)
                _gpu_started = True

            # ── Enter ──────────────────────────────────────────────────────
            ACTIVE_AGENTS.labels(service=svc, endpoint=ep).inc()
            _update_peak(svc, ep)
            REQUEST_COUNT.labels(service=svc, endpoint=ep).inc()
            _record_sys(svc)

            before_mem = gpu_before(svc, ep, dev) if dev is not None else None
            t0 = time.perf_counter()

            # ── Execute ────────────────────────────────────────────────────
            try:
                result = await fn(*args, **kwargs)
                return result
            except Exception:
                ERROR_COUNT.labels(service=svc, endpoint=ep).inc()
                raise
            finally:
                # ── Exit ───────────────────────────────────────────────────
                elapsed = time.perf_counter() - t0
                REQUEST_LATENCY.labels(service=svc, endpoint=ep).observe(elapsed)
                ACTIVE_AGENTS.labels(service=svc, endpoint=ep).dec()
                _record_sys(svc)
                if dev is not None:
                    gpu_after(svc, ep, before_mem, dev)

        return wrapper

    return decorator