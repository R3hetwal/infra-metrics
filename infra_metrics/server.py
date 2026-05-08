"""
infra_metrics/server.py

mount_metrics(app) — attach Prometheus /metrics endpoint to a FastAPI app
                     and auto-start the background GPU polling thread.
"""

from __future__ import annotations

from fastapi import FastAPI
from prometheus_client import make_asgi_app

from infra_metrics.config import get_config
from infra_metrics._gpu import start_gpu_background


def mount_metrics(app: FastAPI, path: str = "/metrics") -> None:
    """
    Call once during app setup:

        from infra_metrics.server import mount_metrics
        mount_metrics(app)

    This:
      1. Mounts a Prometheus-compatible /metrics endpoint.
      2. Registers a startup handler that begins background GPU polling
         if device_index is configured for this service.
    """
    metrics_app = make_asgi_app()
    app.mount(path, metrics_app)

    @app.on_event("startup")
    async def _start_gpu_bg() -> None:
        cfg = get_config()
        if cfg.device_index is not None:
            start_gpu_background(cfg.service, cfg.device_index)