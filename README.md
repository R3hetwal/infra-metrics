# infra-metrics

Unified Prometheus observability for Python ML services — request count, latency, CPU, RAM, and GPU in one decorator.

## Install

```bash
# CPU-only
pip install infra-metrics

# With GPU support
pip install "infra-metrics[gpu]"
```

## Quickstart

```python
from infra_metrics import configure, track
from infra_metrics.server import start_metrics_server

# Call once at startup
configure(service="embedding-service", env="prod")
start_metrics_server(port=8000)   # exposes /metrics

@track()
async def embed(text: str):
    ...

@track(endpoint="health")
def health_check():
    return {"status": "ok"}
```

Every call to `embed()` now emits:

| Metric | Type | Labels |
|---|---|---|
| `service_requests_total` | Counter | service, endpoint, status |
| `service_request_latency_seconds` | Histogram | service, endpoint |
| `service_errors_total` | Counter | service, endpoint, exception_type |
| `cpu_usage_percent` | Gauge | service, endpoint |
| `ram_usage_mb` | Gauge | service, endpoint |
| `gpu_utilization_percent` | Gauge | service, endpoint, stage |
| `gpu_memory_used_mb` | Gauge | service, endpoint, stage |
| `gpu_memory_delta_mb` | Gauge | service, endpoint |

GPU metrics are silently skipped if `pynvml` is not installed.

## Options

```python
configure(
    service="my-service",
    env="prod",
    extra_labels={"region": "us-east-1"},  # added to every metric
    gpu_device_index=0,                    # None to disable GPU tracking
)

@track(
    endpoint="custom-name",   # override the label (default: function name)
    gpu=False,                # force GPU off for this endpoint
    system=False,             # skip CPU/RAM for this endpoint
)
def fast_path(): ...
```

## FastAPI integration

```python
from fastapi import FastAPI
from infra_metrics.server import metrics_route

app = FastAPI()
app.add_route("/metrics", metrics_route())
```

## Flask integration

```python
from flask import Flask
from infra_metrics.server import flask_metrics_view

app = Flask(__name__)
app.add_url_rule("/metrics", "metrics", flask_metrics_view())
```

## Manual GPU profiling

```python
from infra_metrics import gpu_profile

with gpu_profile(service="svc", endpoint="infer"):
    result = model.predict(x)
```

## Dev vs prod

```python
import os
from infra_metrics import configure

configure(
    service="my-service",
    env=os.getenv("ENV", "dev"),
    gpu_device_index=None if os.getenv("ENV") == "dev" else 0,
)
```

## Run tests

```bash
pip install -e ".[dev]"
pytest tests/
```
