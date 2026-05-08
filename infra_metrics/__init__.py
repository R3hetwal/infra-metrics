"""
infra_metrics/__init__.py

Public API:
  configure()       — set service name, env, gpu_device_index
  @track()          — decorator; one line per endpoint (sync + async)
  gpu_before()      — manual GPU snapshot before (for streaming endpoints)
  gpu_after()       — manual GPU snapshot after  (for streaming endpoints)
  get_config()      — access resolved ServiceConfig
  set_config()      — override config programmatically

@track() auto-tracks:
  ✓ Active agents + peak agents (concurrent requests in-flight)
  ✓ Request count  (status label: "ok" / "error")
  ✓ Error count    (exception_type label)
  ✓ Request latency (histogram)
  ✓ Process CPU % + RSS RAM  (via _system.record_system_metrics)
  ✓ GPU util % snapshot before/after   ← only if gpu_device_index set
  ✓ VRAM used before/after
  ✓ VRAM delta (after − before)
  ✓ Background true GPU util % + power watts polled every 2 s

STREAMING ENDPOINTS (StreamingResponse / generator):
  @track() wraps the *construction* of the response, not the stream lifetime.
  Use the manual pattern (gpu_before / gpu_after inside generator finally block)
  so GPU/agent metrics stay accurate for the full stream duration.
"""

from infra_metrics.decorator import configure, track          # canonical implementations
from infra_metrics._gpu import gpu_before, gpu_after
from infra_metrics.config import get_config, set_config, load_config   # re-export

__all__ = [
    "configure",
    "track",
    "gpu_before",
    "gpu_after",
    "get_config",
    "set_config",
    "load_config",
]