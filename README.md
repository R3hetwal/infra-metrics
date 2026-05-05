# infra-metrics

Unified Prometheus observability for Python AI services.
One decorator gives you: active agents, request count, latency, errors, CPU, RAM, and GPU — served at `/metrics` on your existing service port.

---

## Install

```bash
pip install git+https://github.com/YOUR-ORG/infra-metrics.git          # CPU only
pip install "infra-metrics[gpu] @ git+https://github.com/YOUR-ORG/infra-metrics.git"  # + GPU
```

### Upgrade existing install
```bash
# Must use --force-reinstall (not --upgrade) — ensures new code is pulled
pip install --force-reinstall git+https://github.com/YOUR-ORG/infra-metrics.git

# Inside a venv (most common — each service has its own venv)
/path/to/service/env/bin/pip install --force-reinstall git+https://github.com/YOUR-ORG/infra-metrics.git
```

> **Note:** `--upgrade` only re-installs if the version number changed.
> `--force-reinstall` always pulls fresh. Use it to be safe.

Verify version after install:
```bash
pip show infra-metrics
# or inside venv:
/path/to/service/env/bin/pip show infra-metrics
```

---

## Usage — minimal (no configure() needed)

Set service name via environment variable — no code change required:

```bash
# In your systemd service file or shell:
export INFRA_METRICS_SERVICE=sentiment_analysis
export INFRA_METRICS_ENV=prod
```

```python
from fastapi import FastAPI
from infra_metrics import track
from infra_metrics.server import mount_metrics

app = FastAPI()
mount_metrics(app)      # /metrics live on same port — no configure() needed

@track()
async def predict(text: str):
    ...
```

### Or call configure() explicitly (overrides env vars)

```python
from infra_metrics import configure, track
from infra_metrics.server import mount_metrics

configure(service="sentiment_analysis", env="prod")
mount_metrics(app)
```

### Recommended: set via systemd

In `/etc/systemd/system/your_service.service`:
```ini
[Service]
Environment=INFRA_METRICS_SERVICE=sentiment_analysis
Environment=INFRA_METRICS_ENV=prod
```
Then no code change needed at all.

---

## Per-service setup

Each service: one env var + one line of code. Metrics at `<port>/metrics`.

```
stt             :8001/metrics   INFRA_METRICS_SERVICE=stt
tts             :8002/metrics   INFRA_METRICS_SERVICE=tts
ner             :8003/metrics   INFRA_METRICS_SERVICE=ner
sentiment       :8004/metrics   INFRA_METRICS_SERVICE=sentiment
```

```python
# Same code in every service — service name comes from env var
from infra_metrics import track
from infra_metrics.server import mount_metrics

mount_metrics(app)

@track()
async def predict(...): ...
```

### Flask

```python
from infra_metrics.server import mount_metrics
mount_metrics(app)
```

### Background worker (no web app)

```python
from infra_metrics.server import start_metrics_server
start_metrics_server(port=9100)
```

---

## Metrics captured per request (all automatic via @track)

| Metric | Type | What it means |
|---|---|---|
| `active_agents_total` | Gauge | Concurrent requests in-flight right now |
| `service_requests_total` | Counter | Total requests (ok / error) |
| `service_request_latency_seconds` | Histogram | Response time |
| `service_errors_total` | Counter | Exceptions by type |
| `cpu_usage_percent` | Gauge | Process CPU % |
| `ram_usage_mb` | Gauge | Process RAM (MB) |
| `gpu_utilization_percent` | Gauge | GPU util % before/after |
| `gpu_memory_used_mb` | Gauge | VRAM used (MB) |
| `gpu_memory_delta_mb` | Gauge | VRAM change per request |

GPU metrics silently skipped if `pynvml` not installed.

---

## Decorator options

```python
@track(
    endpoint="custom-name",   # override label (default: function name)
    gpu=False,                # force GPU off
    system=False,             # skip CPU/RAM
)
def fast_path(): ...
```

---

## configure() options (optional — env vars preferred)

```python
configure(
    service="stt",
    env="prod",
    extra_labels={"region": "us-east-1"},
    gpu_device_index=0,        # None to disable GPU
)
```

| configure() arg | Env var override |
|---|---|
| `service` | `INFRA_METRICS_SERVICE` |
| `env` | `INFRA_METRICS_ENV` |

---

## Monitoring stack (Prometheus + Grafana, no Docker)

Everything in `monitoring/` folder. Clone the repo on your monitoring server.

### File map

```
monitoring/
├── services.yaml                             ← YOU edit — hosts + ports
├── generate_prometheus_config.py             ← generates prometheus.yml
├── prometheus.yml                            ← AUTO-GENERATED, not committed
├── setup_monitoring.sh                       ← run once on monitoring server
├── prometheus.service                        ← systemd unit
├── grafana.service                           ← systemd unit
└── grafana/
    ├── provisioning/
    │   ├── datasources/prometheus.yml        ← tells Grafana where Prometheus is
    │   └── dashboards/dashboards.yml         ← tells Grafana where dashboard files are
    └── dashboards/ai_services.json           ← actual graphs/panels (auto-loaded)
```

> Two files named `prometheus.yml` — different purposes:
>
> | File | Purpose | Commit? |
> |---|---|---|
> | `grafana/provisioning/datasources/prometheus.yml` | Grafana → find Prometheus at localhost:9090 | ✅ Yes |
> | `monitoring/prometheus.yml` | Prometheus scrape config — auto-generated | ❌ No |

### Step 1 — Edit services.yaml

```yaml
scrape_interval: 15s

services:
  - name: stt
    host: localhost
    port: 8001
  - name: tts
    host: localhost
    port: 8002
  - name: ner
    host: 192.168.1.11     # different machine
    port: 8003
```

### Step 2 — Run setup once

```bash
chmod +x monitoring/setup_monitoring.sh
sudo bash monitoring/setup_monitoring.sh
```

After:
```
Prometheus → http://your-server:9090
Grafana    → http://your-server:3000  (admin / admin)
```

Dashboard loads automatically.

### Step 3 — Add/change services later

```bash
nano monitoring/services.yaml
python3 monitoring/generate_prometheus_config.py \
  --config monitoring/services.yaml \
  --out /etc/prometheus/prometheus.yml
sudo systemctl reload prometheus
```

---

## Zabbix

Import `zabbix_template.yaml` → Configuration → Templates → Import.
Set macros per host: `{$SERVICE_NAME}`, `{$ENDPOINT}`, `{$METRICS_PORT}`.

---

## Run tests

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest tests/ -v
```
