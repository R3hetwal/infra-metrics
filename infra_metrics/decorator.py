"""
@track() — single decorator that instruments any sync or async function with:
  - request count + error count
  - latency histogram
  - CPU / RAM snapshot
  - GPU before/after + VRAM delta  (skipped if GPU disabled in config)

Usage:
    from infra_metrics import configure, track

    configure(service="embedding-service", env="prod")

    @track()
    async def embed(text: str): ...

    @track(endpoint="custom-name", gpu=False)
    def preprocess(data): ...
"""

from __future__ import annotations

import inspect
import time
from functools import wraps
from typing import Callable, Optional

from .config import get_config
from ._gpu import NVML_AVAILABLE, gpu_before, gpu_after
from ._metrics import ACTIVE_AGENTS, ERROR_COUNT, REQUEST_COUNT, REQUEST_LATENCY
from ._system import record_system_metrics


def track(
    endpoint: Optional[str] = None,
    *,
    gpu: Optional[bool] = None,
    system: bool = True,
) -> Callable:
    """
    Decorator factory.

    Args:
        endpoint: Override the Prometheus endpoint label (default: function name).
        gpu:      Force GPU tracking on/off. Default: on if pynvml is available
                  AND config.gpu_device_index is not None.
        system:   Whether to record CPU/RAM. Default True.
    """

    def decorator(func: Callable) -> Callable:
        ep = endpoint or func.__name__

        def _resolve_gpu() -> bool:
            cfg = get_config()
            if gpu is not None:
                return gpu and NVML_AVAILABLE and cfg.gpu_device_index is not None
            return NVML_AVAILABLE and cfg.gpu_device_index is not None

        # ── async path ────────────────────────────────────────────────────────
        if inspect.iscoroutinefunction(func):

            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                cfg = get_config()
                svc = cfg.service
                use_gpu = _resolve_gpu()

                start = time.perf_counter()
                before_mem: float = 0.0

                ACTIVE_AGENTS.labels(svc, ep).inc()
                if use_gpu:
                    before_mem = gpu_before(svc, ep, cfg.gpu_device_index)

                status = "ok"
                try:
                    result = await func(*args, **kwargs)
                    return result
                except Exception as exc:
                    status = "error"
                    ERROR_COUNT.labels(svc, ep, type(exc).__name__).inc()
                    raise
                finally:
                    ACTIVE_AGENTS.labels(svc, ep).dec()
                    elapsed = time.perf_counter() - start
                    REQUEST_COUNT.labels(svc, ep, status).inc()
                    REQUEST_LATENCY.labels(svc, ep).observe(elapsed)

                    if system:
                        record_system_metrics(svc, ep)
                    if use_gpu:
                        gpu_after(svc, ep, before_mem, cfg.gpu_device_index)

            return async_wrapper

        # ── sync path ─────────────────────────────────────────────────────────
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            cfg = get_config()
            svc = cfg.service
            use_gpu = _resolve_gpu()

            start = time.perf_counter()
            before_mem: float = 0.0

            ACTIVE_AGENTS.labels(svc, ep).inc()
            if use_gpu:
                before_mem = gpu_before(svc, ep, cfg.gpu_device_index)

            status = "ok"
            try:
                return func(*args, **kwargs)
            except Exception as exc:
                status = "error"
                ERROR_COUNT.labels(svc, ep, type(exc).__name__).inc()
                raise
            finally:
                ACTIVE_AGENTS.labels(svc, ep).dec()
                elapsed = time.perf_counter() - start
                REQUEST_COUNT.labels(svc, ep, status).inc()
                REQUEST_LATENCY.labels(svc, ep).observe(elapsed)

                if system:
                    record_system_metrics(svc, ep)
                if use_gpu:
                    gpu_after(svc, ep, before_mem, cfg.gpu_device_index)

        return sync_wrapper

    return decorator
