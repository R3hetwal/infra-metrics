# infra-metrics

Unified Prometheus observability for Python AI services.
One decorator gives you: active agents, request count, latency, errors, CPU, RAM, and GPU — served at `/metrics` on your existing service port.

---

## Install

```bash
pip install infra-metrics          # CPU only
pip install "infra-metrics[gpu]"   # + GPU support
```

### Upgrade
```bash
pip install --upgrade infra-metrics
# or from GitHub:
pip install --upgrade git+https://github.com/YOUR-ORG/infra-metrics.git
```

---

## Usage — add to each service (2 lines)

```python
from fastapi import FastAPI
from infra_metrics import configure, track
from infra_metrics.server import mount_metrics

app = FastAPI()
configure(service="stt", env="prod")   # line 1
mount_metrics(app)                      # line 2 — adds GET /metrics on same port

@track()
async def transcribe(audio: bytes):
    ...                                 # cpu, ram, gpu, latency all auto-captured
```

Each service gets its own `/metrics` on its own port. No extra port needed.

```python
# stt_service.py  (runs on :8001) → metrics at :8001/metrics
configure(service="stt", env="prod")
mount_metrics(app)

# tts_service.py  (runs on :8002) → metrics at :8002/metrics
configure(service="tts", env="prod")
mount_metrics(app)

# ner_service.py  (runs on :8003) → metrics at :8003/metrics
configure(service="ner", env="prod")
mount_metrics(app)

# sentiment_service.py (runs on :8004) → metrics at :8004/metrics
configure(service="sentiment", env="prod")
mount_metrics(app)
```

### Flask

```python
from flask import Flask
from infra_metrics.server import mount_metrics

app = Flask(__name__)
configure(service="stt", env="prod")
mount_metrics(app)
```

### Background worker (no web app)

```python
from infra_metrics.server import start_metrics_server
configure(service="worker", env="prod")
start_metrics_server(port=9100)   # separate port, only use when no FastAPI/Flask app
```

---

## Metrics emitted per request

| Metric | Type | Labels |
|---|---|---|
| `active_agents_total` | Gauge | service, endpoint |
| `service_requests_total` | Counter | service, endpoint, status |
| `service_request_latency_seconds` | Histogram | service, endpoint |
| `service_errors_total` | Counter | service, endpoint, exception_type |
| `cpu_usage_percent` | Gauge | service, endpoint |
| `ram_usage_mb` | Gauge | service, endpoint |
| `gpu_utilization_percent` | Gauge | service, endpoint, stage |
| `gpu_memory_used_mb` | Gauge | service, endpoint, stage |
| `gpu_memory_delta_mb` | Gauge | service, endpoint |

GPU metrics silently skipped if `pynvml` not installed.

---

## Decorator options

```python
@track(
    endpoint="custom-name",   # override label (default: function name)
    gpu=False,                # force GPU off for this endpoint
    system=False,             # skip CPU/RAM
)
def fast_path(): ...
```

## Configure options

```python
configure(
    service="stt",
    env="prod",                            # "dev" | "prod" | etc
    extra_labels={"region": "us-east-1"}, # optional static labels
    gpu_device_index=0,                    # None to disable GPU
)

# Dev vs prod pattern:
import os
configure(
    service="stt",
    env=os.getenv("ENV", "dev"),
    gpu_device_index=None if os.getenv("ENV") == "dev" else 0,
)
```

---

## Monitoring stack (Prometheus + Grafana, no Docker)

Everything lives in the `monitoring/` folder.

### File map

```
monitoring/
├── services.yaml                             ← YOU edit this
├── generate_prometheus_config.py             ← generates Prometheus scrape config
├── prometheus.yml                            ← AUTO-GENERATED, do not edit or commit
├── setup_monitoring.sh                       ← run once on monitoring server
├── prometheus.service                        ← systemd unit for Prometheus
├── grafana.service                           ← systemd unit for Grafana
└── grafana/
    ├── provisioning/
    │   ├── datasources/
    │   │   └── prometheus.yml                ← tells Grafana where Prometheus is
    │   └── dashboards/
    │       └── dashboards.yml                ← tells Grafana where dashboard files are
    └── dashboards/
        └── ai_services.json                  ← the actual graphs/panels
```

> **Two files named `prometheus.yml` — don't confuse them:**
>
> | File | Purpose | Commit? |
> |---|---|---|
> | `grafana/provisioning/datasources/prometheus.yml` | Tells Grafana where Prometheus lives (`localhost:9090`) | ✅ Yes |
> | `monitoring/prometheus.yml` | Prometheus scrape config — which services to poll | ❌ No — auto-generated |

### Step 1 — Tell it about your services

Edit `monitoring/services.yaml`:

```yaml
scrape_interval: 15s

services:
  - name: stt
    host: localhost         # IP or hostname where service runs
    port: 8001

  - name: tts
    host: localhost
    port: 8002

  - name: ner
    host: 192.168.1.11     # service on a different machine
    port: 8003

  - name: sentiment
    host: 192.168.1.11
    port: 8004
```

### Step 2 — Install everything (run once)

Copy the `monitoring/` folder to your monitoring server, then:

```bash
chmod +x monitoring/setup_monitoring.sh
sudo bash monitoring/setup_monitoring.sh
```

The script:
- Installs Prometheus binary + Grafana via apt
- Creates all required system directories
- Copies Grafana provisioning files (datasource + dashboard auto-configure)
- Generates `/etc/prometheus/prometheus.yml` from your `services.yaml`
- Installs + starts both as systemd services

After it finishes:
```
Prometheus → http://your-server:9090
Grafana    → http://your-server:3000  (login: admin / admin)
```

Dashboard loads automatically — no manual Grafana setup needed.

### Step 3 — Adding or changing services later

```bash
# 1. Edit services.yaml
nano monitoring/services.yaml

# 2. Regenerate Prometheus config
python3 monitoring/generate_prometheus_config.py \
  --config monitoring/services.yaml \
  --out /etc/prometheus/prometheus.yml

# 3. Reload (no downtime)
sudo systemctl reload prometheus
```

### Check status

```bash
sudo systemctl status prometheus
sudo systemctl status grafana-server

# Live logs
sudo journalctl -u prometheus -f
sudo journalctl -u grafana-server -f
```

---

## Zabbix (alternative to Grafana)

Import `zabbix_template.yaml`:
Zabbix → Configuration → Templates → Import

Set macros per host:
- `{$SERVICE_NAME}` = your service name (matches `configure(service=...)`)
- `{$ENDPOINT}` = function name
- `{$METRICS_PORT}` = service port (8001, 8002, etc.)

---

## Run tests

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest tests/ -v
```
