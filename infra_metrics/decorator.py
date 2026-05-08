"""
infra_metrics/decorator.py

configure() — set service name / env / gpu_device_index programmatically.
@track()    — instruments any sync or async function with:
  - request count + error count  (3-label: service, endpoint, status/exception_type)
  - latency histogram
  - CPU / RAM snapshot (via _system.record_system_metrics)
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

from .config import ServiceConfig, get_config, set_config
from ._gpu import NVML_AVAILABLE, gpu_before, gpu_after, start_gpu_background
from ._metrics import ACTIVE_AGENTS, ERROR_COUNT, REQUEST_COUNT, REQUEST_LATENCY, PEAK_ACTIVE_AGENTS
from ._system import record_system_metrics


# ── configure() ──────────────────────────────────────────────────────────────

def configure(
    service: str = "",
    env: str = "prod",
    gpu_device_index: Optional[int] = None,
    extra_labels: Optional[dict] = None,
) -> None:
    """
    Set service config programmatically.  Overrides env vars and services.yaml.

    Args:
        service:          Prometheus 'service' label value (e.g. "embedding-service").
        env:              Deployment environment tag (stored but not currently used as label).
        gpu_device_index: NVML device index. None → GPU tracking disabled.
        extra_labels:     Reserved for future use.
    """
    set_config(ServiceConfig(service=service, gpu_device_index=gpu_device_index))


# ── track() ───────────────────────────────────────────────────────────────────

def track(
    endpoint: Optional[str] = None,
    *,
    gpu: Optional[bool] = None,
    system: bool = True,
) -> Callable:
    """
    Decorator factory.  Works on both sync and async functions.

    Args:
        endpoint: Override the Prometheus endpoint label (default: function name).
        gpu:      Force GPU tracking on/off. Default: on if pynvml is available
                  AND config.gpu_device_index is not None.
        system:   Whether to record CPU/RAM. Default True.
    """

    def decorator(func: Callable) -> Callable:
        ep = endpoint or func.__name__
        _gpu_started = False  # start bg thread only once per decorated fn (mutable via nonlocal)

        def _resolve_gpu() -> bool:
            cfg = get_config()
            if gpu is not None:
                return gpu and NVML_AVAILABLE and cfg.gpu_device_index is not None
            return NVML_AVAILABLE and cfg.gpu_device_index is not None

        # ── async path ────────────────────────────────────────────────────────
        if inspect.iscoroutinefunction(func):

            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                nonlocal _gpu_started
                cfg = get_config()
                svc = cfg.service
                use_gpu = _resolve_gpu()

                # Start background GPU thread once, lazily
                if use_gpu and not _gpu_started:
                    start_gpu_background(svc, cfg.gpu_device_index)
                    _gpu_started = True

                start = time.perf_counter()
                before_mem: float = 0.0

                ACTIVE_AGENTS.labels(svc, ep).inc()
                current = ACTIVE_AGENTS.labels(svc, ep)._value.get()
                peak_g  = PEAK_ACTIVE_AGENTS.labels(svc, ep)
                if current > peak_g._value.get():
                    peak_g.set(current)
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
            nonlocal _gpu_started
            cfg = get_config()
            svc = cfg.service
            use_gpu = _resolve_gpu()

            if use_gpu and not _gpu_started:
                start_gpu_background(svc, cfg.gpu_device_index)
                _gpu_started = True

            start = time.perf_counter()
            before_mem: float = 0.0

            ACTIVE_AGENTS.labels(svc, ep).inc()
            current = ACTIVE_AGENTS.labels(svc, ep)._value.get()
            peak_g  = PEAK_ACTIVE_AGENTS.labels(svc, ep)
            if current > peak_g._value.get():
                peak_g.set(current)
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