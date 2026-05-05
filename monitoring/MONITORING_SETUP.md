# Monitoring Setup — Bare Metal (no Docker)

This folder contains everything needed to run Prometheus + Grafana as systemd
services on your monitoring server. No Docker required.

---

## Folder structure explained

```
monitoring/
├── services.yaml                    ← YOU edit this — your hosts and ports
├── generate_prometheus_config.py    ← script: reads services.yaml → writes prometheus.yml
├── setup_monitoring.sh              ← run ONCE on server to install everything
├── prometheus.service               ← systemd unit (copied to /etc/systemd by setup script)
├── grafana.service                  ← systemd unit (copied to /etc/systemd by setup script)
└── grafana/
    ├── provisioning/
    │   ├── datasources/
    │   │   └── prometheus.yml       ← tells Grafana where Prometheus is
    │   └── dashboards/
    │       └── dashboards.yml       ← tells Grafana where to find dashboard JSON files
    └── dashboards/
        └── ai_services.json         ← the actual dashboard (panels, graphs)
```

The `grafana/` folder is NOT auto-created. It exists in this repo.
The setup script copies these files to the right system paths (`/etc/grafana/`, `/var/lib/grafana/`).
You never need to create or edit folders manually.

---

## Step 1 — Edit services.yaml (before anything else)

Open `monitoring/services.yaml` and set your actual service hosts and ports:

```yaml
scrape_interval: 15s

services:
  - name: stt
    host: localhost        # or IP like 192.168.1.10
    port: 8001

  - name: tts
    host: localhost
    port: 8002

  - name: ner
    host: 192.168.1.11    # service on a different machine
    port: 8003
```

One entry per service. `host` = IP or hostname where that service runs.
`port` = the port your FastAPI/Flask app listens on (metrics at `<host>:<port>/metrics`).

---

## Step 2 — Run setup script (once, on monitoring server)

Copy the entire `monitoring/` folder to your monitoring server, then:

```bash
chmod +x monitoring/setup_monitoring.sh
sudo bash monitoring/setup_monitoring.sh
```

This script does ALL of the following automatically:
- Creates system users (`prometheus`, `grafana`)
- Creates all required directories
- Downloads and installs Prometheus binary
- Installs Grafana via apt
- Copies provisioning files so Grafana auto-loads the datasource and dashboard
- Generates `/etc/prometheus/prometheus.yml` from your `services.yaml`
- Installs and starts both systemd services

After it finishes:
- Prometheus → `http://your-server:9090`
- Grafana    → `http://your-server:3000`  (login: admin / admin)

---

## Adding or changing a service later

1. Edit `monitoring/services.yaml`
2. Regenerate Prometheus config:
   ```bash
   python3 monitoring/generate_prometheus_config.py \
     --config monitoring/services.yaml \
     --out /etc/prometheus/prometheus.yml
   ```
3. Reload Prometheus (no downtime, no restart):
   ```bash
   sudo systemctl reload prometheus
   ```

---

## Checking status

```bash
sudo systemctl status prometheus
sudo systemctl status grafana-server

# Live logs
sudo journalctl -u prometheus -f
sudo journalctl -u grafana-server -f
```

---

## Multi-server setup

Prometheus runs on ONE monitoring server and scrapes all other servers.
Your AI services just need to have port reachable from the monitoring server.

```
[Monitoring server]          [App server A: 192.168.1.10]
  Prometheus ──────────────→  stt :8001/metrics
  Grafana                  →  tts :8002/metrics

                             [App server B: 192.168.1.11]
               ──────────────→  ner :8003/metrics
               ──────────────→  sentiment :8004/metrics
```

In `services.yaml`:
```yaml
services:
  - name: stt
    host: 192.168.1.10
    port: 8001
  - name: tts
    host: 192.168.1.10
    port: 8002
  - name: ner
    host: 192.168.1.11
    port: 8003
  - name: sentiment
    host: 192.168.1.11
    port: 8004
```
