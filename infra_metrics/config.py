"""
infra_metrics/config.py
Service config — reads services.yaml, exposes gpu_device_index for GPU tracking.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

_config: Optional["ServiceConfig"] = None


@dataclass
class ServiceConfig:
    service: str = ""
    host: str = "localhost"
    port: int = 0
    gpu_device_index: Optional[int] = None   # GPU device index; None → no GPU tracking


def load_config(path: str = "monitoring/services.yaml") -> "ServiceConfig":
    """
    Load config for THIS service from services.yaml.
    Service name resolved from env var SERVICE_NAME (set it in your start script).
    Falls back to empty ServiceConfig if file/key missing.
    """
    global _config
    svc_name = os.environ.get("INFRA_METRICS_SERVICE") or os.environ.get("SERVICE_NAME", "")
    try:
        import yaml  # optional dep
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        for svc in data.get("services", []):
            if svc.get("name") == svc_name:
                _config = ServiceConfig(
                    service=svc["name"],
                    host=svc.get("host", "localhost"),
                    port=svc.get("port", 0),
                    gpu_device_index=svc.get("device_index", None),  # yaml key stays device_index
                )
                return _config
    except Exception:
        pass
    _config = ServiceConfig(service=svc_name)
    return _config


def get_config() -> "ServiceConfig":
    global _config
    if _config is None:
        load_config()
    return _config


def set_config(cfg: "ServiceConfig") -> None:
    """Override config programmatically (useful for tests or manual init)."""
    global _config
    _config = cfg