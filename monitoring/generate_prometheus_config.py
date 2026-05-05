#!/usr/bin/env python3
"""
Generate prometheus.yml from a simple services.yaml config.

Usage:
    python3 generate_prometheus_config.py                        # uses services.yaml
    python3 generate_prometheus_config.py --config prod.yaml     # custom config file
    python3 generate_prometheus_config.py --out /etc/prometheus/prometheus.yml

services.yaml format:
    scrape_interval: 15s
    services:
      - name: stt
        host: 192.168.1.10
        port: 8001
      - name: tts
        host: 192.168.1.10
        port: 8002
      - name: ner
        host: 192.168.1.11   # different server
        port: 8003
"""

import argparse
import sys

try:
    import yaml
except ImportError:
    print("pip install pyyaml")
    sys.exit(1)


PROMETHEUS_TEMPLATE = """\
global:
  scrape_interval: {scrape_interval}
  evaluation_interval: {scrape_interval}

scrape_configs:
{jobs}
"""

JOB_TEMPLATE = """\
  - job_name: "{name}"
    metrics_path: /metrics
    static_configs:
      - targets: ["{host}:{port}"]
        labels:
          service: "{name}"
"""


def generate(config_path: str, out_path: str) -> None:
    with open(config_path) as f:
        cfg = yaml.safe_load(f)

    interval = cfg.get("scrape_interval", "15s")
    services = cfg.get("services", [])

    if not services:
        print("No services defined in config.")
        sys.exit(1)

    jobs = "".join(
        JOB_TEMPLATE.format(
            name=svc["name"],
            host=svc.get("host", "localhost"),
            port=svc["port"],
        )
        for svc in services
    )

    output = PROMETHEUS_TEMPLATE.format(scrape_interval=interval, jobs=jobs)

    if out_path == "-":
        print(output)
    else:
        with open(out_path, "w") as f:
            f.write(output)
        print(f"Written to {out_path}")
        print("Reload Prometheus: sudo systemctl reload prometheus")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="services.yaml")
    parser.add_argument("--out", default="prometheus.yml")
    args = parser.parse_args()
    generate(args.config, args.out)
