"""
infra_metrics/server.py

mount_metrics(app)        — attach Prometheus /metrics to FastAPI app
                            + auto-start background GPU polling on startup.
start_metrics_server(port) — standalone HTTP server for background workers
                             (no FastAPI/Flask required).
"""

from __future__ import annotations

import threading

from fastapi import FastAPI
from prometheus_client import make_asgi_app, start_http_server

from infra_metrics.config import get_config
from infra_metrics._gpu import start_gpu_background


def mount_metrics(app: FastAPI, path: str = "/metrics") -> None:
    """
    Call once during app setup:

        from infra_metrics.server import mount_metrics
        mount_metrics(app)

    This:
      1. Mounts a Prometheus-compatible /metrics endpoint on `path`.
      2. Registers a startup handler that begins background GPU polling
         if gpu_device_index is configured for this service.
    """
    metrics_app = make_asgi_app()
    app.mount(path, metrics_app)

    @app.on_event("startup")
    async def _start_gpu_bg() -> None:
        cfg = get_config()
        if cfg.gpu_device_index is not None:
            start_gpu_background(cfg.service, cfg.gpu_device_index)


def start_metrics_server(port: int = 9100) -> None:
    """
    Start a standalone Prometheus HTTP server in a daemon thread.
    Use this for background workers that have no web framework:

        from infra_metrics.server import start_metrics_server
        start_metrics_server(port=9100)

    The /metrics endpoint will be available at http://localhost:<port>/metrics.
    Also starts background GPU polling if gpu_device_index is configured.
    """
    cfg = get_config()
    if cfg.gpu_device_index is not None:
        start_gpu_background(cfg.service, cfg.gpu_device_index)
    t = threading.Thread(target=start_http_server, args=(port,), daemon=True)
    t.start()