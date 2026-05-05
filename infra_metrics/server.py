"""
Helpers to expose the Prometheus /metrics endpoint on the SAME port as your service.

Recommended: mount /metrics directly on your existing FastAPI or Flask app.
No separate port needed.

  FastAPI / Starlette → mount_metrics(app)
  Flask               → mount_metrics(app)
  Standalone fallback → start_metrics_server(port=N)  (workers with no web app)
"""

from __future__ import annotations

import logging
import threading

from prometheus_client import CONTENT_TYPE_LATEST, generate_latest, start_http_server

logger = logging.getLogger(__name__)


# ── Universal mount — auto-detects FastAPI or Flask ──────────────────────────

def mount_metrics(app, path: str = "/metrics") -> None:
    """
    Mount a /metrics endpoint on an EXISTING FastAPI or Flask app.
    Metrics served on the same port as your service — no extra port needed.

    FastAPI usage:
        from fastapi import FastAPI
        from infra_metrics.server import mount_metrics

        app = FastAPI()
        mount_metrics(app)          # → GET /metrics on same port

    Flask usage:
        from flask import Flask
        from infra_metrics.server import mount_metrics

        app = Flask(__name__)
        mount_metrics(app)          # → GET /metrics on same port
    """
    app_qualnames = [f"{c.__module__}.{c.__name__}" for c in type(app).__mro__]
    is_fastapi = any("fastapi" in q or "starlette" in q for q in app_qualnames)
    is_flask   = any("flask" in q for q in app_qualnames)

    if is_fastapi:
        _mount_fastapi(app, path)
    elif is_flask:
        _mount_flask(app, path)
    else:
        raise TypeError(
            f"mount_metrics() does not recognise app type {type(app)}. "
            "Use mount_metrics_fastapi() or mount_metrics_flask() directly."
        )


# ── FastAPI / Starlette ───────────────────────────────────────────────────────

def mount_metrics_fastapi(app, path: str = "/metrics") -> None:
    """Mount /metrics on a FastAPI or Starlette app (same port as service)."""
    try:
        from starlette.responses import Response

        async def _handler(request):  # noqa: ARG001
            return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

        app.add_route(path, _handler)
        logger.info("Prometheus /metrics mounted at %s (FastAPI)", path)
    except ImportError:
        raise RuntimeError("pip install starlette")


def _mount_fastapi(app, path):
    mount_metrics_fastapi(app, path)


# ── Flask ─────────────────────────────────────────────────────────────────────

def mount_metrics_flask(app, path: str = "/metrics") -> None:
    """Mount /metrics on a Flask app (same port as service)."""
    try:
        from flask import Response as FlaskResponse

        def _view():
            return FlaskResponse(generate_latest(), mimetype=CONTENT_TYPE_LATEST)

        app.add_url_rule(path, "prometheus_metrics", _view)
        logger.info("Prometheus /metrics mounted at %s (Flask)", path)
    except ImportError:
        raise RuntimeError("pip install flask")


def _mount_flask(app, path):
    mount_metrics_flask(app, path)


# ── Standalone fallback (separate port) ───────────────────────────────────────

def start_metrics_server(port: int = 9100, addr: str = "0.0.0.0") -> None:
    """
    Spin up a SEPARATE HTTP server just for /metrics.
    Use only for background workers with no FastAPI/Flask app.
    For web services use mount_metrics(app) instead.
    """
    def _serve():
        start_http_server(port, addr=addr)
        logger.info("Prometheus metrics at http://%s:%d/metrics", addr, port)

    t = threading.Thread(target=_serve, daemon=True, name="prometheus-metrics")
    t.start()
