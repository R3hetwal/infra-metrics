"""
System-level metrics: CPU, RAM, and CPU power — captured per request AND by background thread.

Background thread fixes the "0 MB RAM" issue for services with no requests yet.
CPU power reads from Intel RAPL (/sys/class/powercap) — silently skipped on unsupported hardware.
"""

import time
from pathlib import Path
from typing import Optional

import psutil
from prometheus_client import Gauge

# ── Per-request gauges (endpoint-labelled) ────────────────────────────────────
CPU_USAGE = Gauge(
    "cpu_usage_percent",
    "Process CPU usage (%)",
    ["service", "endpoint"],
)
RAM_USAGE = Gauge(
    "ram_usage_mb",
    "Process RSS memory usage (MB)",
    ["service", "endpoint"],
)

# ── Service-level gauges (no endpoint label) — updated by background thread ───
# Dashboard uses these for baseline display even with 0 requests.
CPU_USAGE_SERVICE = Gauge(
    "cpu_usage_percent_service",
    "Process CPU usage (%) — service baseline (background)",
    ["service"],
)
RAM_USAGE_SERVICE = Gauge(
    "ram_usage_mb_service",
    "Process RSS memory (MB) — service baseline (background)",
    ["service"],
)

# ── CPU power via Intel RAPL ──────────────────────────────────────────────────
CPU_POWER_WATTS = Gauge(
    "cpu_power_watts",
    "CPU package power draw (W) — Intel RAPL; 0 if unsupported",
    ["service"],
)

_RAPL_ROOT   = Path("/sys/class/powercap/intel-rapl/intel-rapl:0")
_RAPL_ENERGY = _RAPL_ROOT / "energy_uj"
_RAPL_MAX    = _RAPL_ROOT / "max_energy_range_uj"

# Two-sample state for dE/dt → watts
_rapl_last_uj:   Optional[float] = None
_rapl_last_time: Optional[float] = None


def _read_cpu_power_watts() -> Optional[float]:
    """
    Compute CPU package power (W) from RAPL energy counter.
    First call initialises state and returns None.
    Handles energy counter wraparound.
    Returns None if RAPL unavailable (non-Intel, missing permissions, etc.).
    """
    global _rapl_last_uj, _rapl_last_time
    if not _RAPL_ENERGY.exists():
        return None
    try:
        now_uj   = float(_RAPL_ENERGY.read_text().strip())
        now_time = time.monotonic()

        if _rapl_last_uj is not None and _rapl_last_time is not None:
            delta_uj = now_uj - _rapl_last_uj
            if delta_uj < 0 and _RAPL_MAX.exists():          # wraparound
                delta_uj += float(_RAPL_MAX.read_text().strip())
            delta_s = now_time - _rapl_last_time
            if delta_s > 0:
                watts = (delta_uj / 1e6) / delta_s           # µJ → J → W
                _rapl_last_uj   = now_uj
                _rapl_last_time = now_time
                return max(0.0, watts)

        _rapl_last_uj   = now_uj
        _rapl_last_time = now_time
        return None
    except Exception:
        return None


def record_system_metrics(service: str, endpoint: str) -> None:
    """
    Push CPU% and RSS memory to per-endpoint AND service-level Prometheus gauges.
    Service-level gauges ensure the dashboard shows real values even for services
    with few or no requests.
    """
    proc = psutil.Process()
    cpu = proc.cpu_percent(interval=None)
    ram = proc.memory_info().rss / 1024 / 1024

    CPU_USAGE.labels(service, endpoint).set(cpu)
    RAM_USAGE.labels(service, endpoint).set(ram)
    CPU_USAGE_SERVICE.labels(service).set(cpu)
    RAM_USAGE_SERVICE.labels(service).set(ram)

    watts = _read_cpu_power_watts()
    if watts is not None:
        CPU_POWER_WATTS.labels(service).set(watts)


def record_service_baseline(service: str) -> None:
    """
    Lightweight update — only touches service-level gauges.
    Called by the background thread so idle services always report RAM/CPU.
    """
    proc = psutil.Process()
    CPU_USAGE_SERVICE.labels(service).set(proc.cpu_percent(interval=None))
    RAM_USAGE_SERVICE.labels(service).set(proc.memory_info().rss / 1024 / 1024)

    watts = _read_cpu_power_watts()
    if watts is not None:
        CPU_POWER_WATTS.labels(service).set(watts)