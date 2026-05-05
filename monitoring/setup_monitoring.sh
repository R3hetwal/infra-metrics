#!/usr/bin/env bash
# =============================================================================
# setup_monitoring.sh
# Run this ONCE on your monitoring server to install Prometheus + Grafana.
# No Docker required. Everything runs as systemd services.
#
# Usage:
#   chmod +x setup_monitoring.sh
#   sudo bash setup_monitoring.sh
# =============================================================================

set -e

MONITORING_DIR="$(cd "$(dirname "$0")" && pwd)"   # folder where this script lives
PROM_VERSION="2.51.0"

echo "==> [1/7] Creating system users..."
id prometheus &>/dev/null || useradd --no-create-home --shell /bin/false prometheus
id grafana    &>/dev/null || useradd --no-create-home --shell /bin/false grafana

echo "==> [2/7] Creating directories..."

# Prometheus
mkdir -p /etc/prometheus
mkdir -p /var/lib/prometheus
chown prometheus:prometheus /var/lib/prometheus

# Grafana provisioning (this is what auto-configures datasource + dashboard)
mkdir -p /etc/grafana/provisioning/datasources
mkdir -p /etc/grafana/provisioning/dashboards
mkdir -p /var/lib/grafana/dashboards
chown -R grafana:grafana /etc/grafana /var/lib/grafana

echo "==> [3/7] Installing Prometheus binaries..."
cd /tmp
wget -q "https://github.com/prometheus/prometheus/releases/download/v${PROM_VERSION}/prometheus-${PROM_VERSION}.linux-amd64.tar.gz"
tar xf "prometheus-${PROM_VERSION}.linux-amd64.tar.gz"
cp "prometheus-${PROM_VERSION}.linux-amd64/prometheus" /usr/local/bin/
cp "prometheus-${PROM_VERSION}.linux-amd64/promtool"   /usr/local/bin/
rm -rf "prometheus-${PROM_VERSION}.linux-amd64"*

echo "==> [4/7] Installing Grafana..."
apt-get install -y apt-transport-https software-properties-common wget gnupg
wget -q -O /usr/share/keyrings/grafana.key https://apt.grafana.com/gpg.key
echo "deb [signed-by=/usr/share/keyrings/grafana.key] https://apt.grafana.com stable main" \
    > /etc/apt/sources.list.d/grafana.list
apt-get update -q
apt-get install -y grafana

echo "==> [5/7] Copying config files..."

# Grafana provisioning — these tell Grafana where Prometheus is and where dashboards are
cp "$MONITORING_DIR/grafana/provisioning/datasources/prometheus.yml" \
    /etc/grafana/provisioning/datasources/prometheus.yml

cp "$MONITORING_DIR/grafana/provisioning/dashboards/dashboards.yml" \
    /etc/grafana/provisioning/dashboards/dashboards.yml

# Grafana dashboard JSON — the actual panels/graphs
cp "$MONITORING_DIR/grafana/dashboards/ai_services.json" \
    /var/lib/grafana/dashboards/ai_services.json

chown -R grafana:grafana /etc/grafana /var/lib/grafana

echo "==> [6/7] Installing systemd services..."
cp "$MONITORING_DIR/prometheus.service" /etc/systemd/system/prometheus.service
cp "$MONITORING_DIR/grafana.service"    /etc/systemd/system/grafana.service
systemctl daemon-reload

echo "==> [7/7] Generating initial Prometheus config from services.yaml..."
pip3 install -q pyyaml
python3 "$MONITORING_DIR/generate_prometheus_config.py" \
    --config "$MONITORING_DIR/services.yaml" \
    --out /etc/prometheus/prometheus.yml
chown prometheus:prometheus /etc/prometheus/prometheus.yml

echo ""
echo "==> Enabling and starting services..."
systemctl enable --now prometheus
systemctl enable --now grafana-server

echo ""
echo "======================================================"
echo "  Done."
echo "  Prometheus : http://$(hostname -I | awk '{print $1}'):9090"
echo "  Grafana    : http://$(hostname -I | awk '{print $1}'):3000"
echo "  Default login: admin / admin  (change on first login)"
echo "======================================================"
echo ""
echo "  To add/change services later:"
echo "    1. Edit monitoring/services.yaml"
echo "    2. python3 generate_prometheus_config.py --out /etc/prometheus/prometheus.yml"
echo "    3. sudo systemctl reload prometheus"
