"""
infra_metrics/server.py

mount_metrics(app)         — attach Prometheus /metrics to FastAPI app
                             + auto-start background GPU + system pollers on startup.
start_metrics_server(port) — standalone HTTP server for background workers
                             (no FastAPI/Flask required).
"""

from __future__ import annotations

import threading

from fastapi import FastAPI
from prometheus_client import make_asgi_app, start_http_server

from infra_metrics.config import get_config
from infra_metrics._gpu import start_gpu_background
from infra_metrics._system import start_system_background


def mount_metrics(app: FastAPI, path: str = "/metrics") -> None:
    """
    Call once during app setup:

        from infra_metrics.server import mount_metrics
        mount_metrics(app)

    Mounts /metrics and starts background GPU + system pollers on app startup.
    """
    metrics_app = make_asgi_app()
    app.mount(path, metrics_app)

    @app.on_event("startup")
    async def _start_bg() -> None:
        cfg = get_config()
        start_system_background(cfg.service)          # always — fixes idle 0 RAM/CPU
        if cfg.gpu_device_index is not None:
            start_gpu_background(cfg.service, cfg.gpu_device_index)


def start_metrics_server(port: int = 9100) -> None:
    """
    Start a standalone Prometheus HTTP server in a daemon thread.
    Use for background workers with no web framework:

        from infra_metrics.server import start_metrics_server
        start_metrics_server(port=9100)

    Also starts background GPU + system pollers.
    """
    cfg = get_config()
    start_system_background(cfg.service)              # always
    if cfg.gpu_device_index is not None:
        start_gpu_background(cfg.service, cfg.gpu_device_index)
    t = threading.Thread(target=start_http_server, args=(port,), daemon=True)
    t.start()