"""
Helpers to expose the Prometheus /metrics endpoint.

Supports:
  - Standalone HTTP server  (start_metrics_server)
  - FastAPI / Starlette     (metrics_route)
  - Flask                   (flask_metrics_route — optional import)
"""

from __future__ import annotations

import logging
import threading

from prometheus_client import CONTENT_TYPE_LATEST, generate_latest, start_http_server

logger = logging.getLogger(__name__)


def start_metrics_server(port: int = 8000, addr: str = "0.0.0.0") -> None:
    """
    Start a Prometheus scrape endpoint in a background thread.

    Call this once at application startup. The thread is daemonised so it
    shuts down cleanly when the main process exits.

    Args:
        port: Port to listen on (default 8000).
        addr: Bind address (default 0.0.0.0).
    """

    def _serve():
        start_http_server(port, addr=addr)
        logger.info("Prometheus metrics available at http://%s:%d/metrics", addr, port)

    t = threading.Thread(target=_serve, daemon=True, name="prometheus-metrics")
    t.start()


# ── FastAPI / Starlette ───────────────────────────────────────────────────────

def metrics_route():
    """
    Returns a plain ASGI response with the current metrics payload.

    Usage (FastAPI):
        from fastapi import FastAPI, Response
        from infra_metrics.server import metrics_route

        app = FastAPI()
        app.add_route("/metrics", metrics_route)

    Usage (Starlette):
        from starlette.applications import Starlette
        from starlette.routing import Route
        from infra_metrics.server import metrics_route

        app = Starlette(routes=[Route("/metrics", metrics_route)])
    """
    try:
        from starlette.responses import Response

        async def _handler(request):  # noqa: ARG001
            return Response(
                content=generate_latest(),
                media_type=CONTENT_TYPE_LATEST,
            )

        return _handler
    except ImportError:
        raise RuntimeError(
            "starlette is required for metrics_route(). "
            "Install it with: pip install starlette"
        )


# ── Flask ─────────────────────────────────────────────────────────────────────

def flask_metrics_view():
    """
    Returns a Flask view function for /metrics.

    Usage:
        from flask import Flask
        from infra_metrics.server import flask_metrics_view

        app = Flask(__name__)
        app.add_url_rule("/metrics", "metrics", flask_metrics_view())
    """
    try:
        from flask import Response as FlaskResponse

        def _view():
            return FlaskResponse(generate_latest(), mimetype=CONTENT_TYPE_LATEST)

        return _view
    except ImportError:
        raise RuntimeError(
            "flask is required for flask_metrics_view(). "
            "Install it with: pip install flask"
        )
