"""
Central configuration for infra-metrics.

Usage:
    from infra_metrics import configure
    configure(service="my-service", env="prod")
"""

from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class _Config:
    service: str = "unknown"
    env: str = "dev"
    # Extra static labels added to every metric (e.g. region, pod)
    extra_labels: Dict = field(default_factory=dict)
    # GPU device index to monitor (None = skip GPU even if pynvml present)
    gpu_device_index: Optional[int] = 0


_config = _Config()


def configure(
    service: str,
    env: str = "dev",
    extra_labels: Optional[Dict] = None,
    gpu_device_index: Optional[int] = 0,
) -> None:
    """
    Call once at application startup.

    Args:
        service:          Name of this service, used as a Prometheus label.
        env:              Deployment environment ("dev" / "prod" / etc).
        extra_labels:     Any additional static key-value labels to attach.
        gpu_device_index: NVML device index to monitor. Pass None to disable
                          GPU tracking even when pynvml is installed.
    """
    _config.service = service
    _config.env = env
    _config.extra_labels = extra_labels or {}
    _config.gpu_device_index = gpu_device_index


def get_config() -> _Config:
    return _config
