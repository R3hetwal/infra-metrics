#!/usr/bin/env python3
"""
infra-metrics enhanced web dashboard
- Live sparkline charts per service card (agents, CPU, GPU, VRAM)
- Full multi-service charts tab (all services on one graph)
- Usage tab: Activity Monitor-style rolling time-series for CPU / RAM / GPU / VRAM
- Detailed crash log: time, service, reason, agents, CPU, RAM, GPU, VRAM, errors
- Crash logs saved to crash_logs/crashes_YYYY-MM-DD.jsonl (one file per day)
- Auto-refreshes every 5s

Usage:
    pip install fastapi uvicorn requests pyyaml
    python3 web_dashboard.py --config services.yaml --port 9999
"""

import argparse
import json
import os
import re
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path

import requests
import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

# ── Config ─────────────────────────────────────────────────────────────────────
DEFAULT_SERVICES = [
    {"name": "stt",              "host": "localhost", "port": 8003},
    {"name": "xtts",             "host": "localhost", "port": 8007},
    {"name": "ner",              "host": "localhost", "port": 8004},
    {"name": "sentiment",        "host": "localhost", "port": 8006},
    {"name": "asterisk_ai",      "host": "localhost", "port": 8001},
]

SERVICES      = list(DEFAULT_SERVICES)
HISTORY_LEN   = 60    # 60 pts × 5 s = 5 min of history
history       = defaultdict(lambda: defaultdict(lambda: deque(maxlen=HISTORY_LEN)))
crash_log     = []
last_up       = {}
last_errors   = {}
CRASH_DIR     = Path("crash_logs")
CRASH_DIR.mkdir(exist_ok=True)


def load_services(path: str) -> list:
    try:
        import yaml
        with open(path) as f:
            return yaml.safe_load(f).get("services", DEFAULT_SERVICES)
    except Exception:
        return DEFAULT_SERVICES


# ── Prometheus parser ──────────────────────────────────────────────────────────
def parse_metrics(text: str) -> dict:
    result = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r'^(\w+)(\{[^}]*\})?\s+([\d.eE+\-]+)', line)
        if not m:
            continue
        name, lstr, val = m.group(1), m.group(2) or "", m.group(3)
        labels = dict(re.findall(r'(\w+)="([^"]*)"', lstr))
        result.setdefault(name, []).append((labels, float(val)))
    return result


def sum_val(m, metric, **f):
    t, found = 0.0, False
    for labels, val in m.get(metric, []):
        if all(labels.get(k) == v for k, v in f.items()):
            t += val; found = True
    return t if found else None


def get_val(m, metric, **f):
    for labels, val in m.get(metric, []):
        if all(labels.get(k) == v for k, v in f.items()):
            return val
    return None


# ── Scraper ────────────────────────────────────────────────────────────────────
def scrape(svc: dict):
    url = f"http://{svc['host']}:{svc['port']}/metrics"
    try:
        r = requests.get(url, timeout=2.0)
        r.raise_for_status()
        return parse_metrics(r.text), None
    except Exception as e:
        return None, str(e)


# ── Crash logger ───────────────────────────────────────────────────────────────
def load_crash_history():
    """Load existing crash logs into memory on startup."""
    entries = []
    for f in sorted(CRASH_DIR.glob("crashes_*.jsonl")):
        try:
            for line in f.read_text().splitlines():
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
        except Exception:
            pass
    crash_log.extend(entries[-100:])


def log_crash(name: str, reason: str, snap: dict):
    ts = datetime.now()
    entry = {"ts": ts.isoformat(timespec="seconds"), "service": name,
             "reason": reason, **snap}
    crash_log.append(entry)
    if len(crash_log) > 100:
        crash_log.pop(0)
    log_file = CRASH_DIR / f"crashes_{ts.strftime('%Y-%m-%d')}.jsonl"
    with open(log_file, "a") as f:
        f.write(json.dumps(entry) + "\n")


# ── Collector ──────────────────────────────────────────────────────────────────
def collect_all() -> list:
    results = []
    ts = datetime.now().isoformat(timespec="seconds")

    for svc in SERVICES:
        name = svc["name"]
        m, err = scrape(svc)
        is_up  = m is not None

        def sv(metric, **kw): return sum_val(m or {}, metric, **kw) or 0
        def gv(metric, **kw): return get_val(m or {}, metric, **kw) or 0

        lat_s = sv("service_request_latency_seconds_sum",   service=name)
        lat_c = sv("service_request_latency_seconds_count", service=name) or 1

        snap = {
            "agents":      int(sv("active_agents_total",       service=name)),
            "peak_agents": int(sv("peak_active_agents_total",  service=name)),
            "requests":    int(sv("service_requests_total",    service=name)),
            "errors":      int(sv("service_errors_total",      service=name)),
            "latency_ms":  round((lat_s / lat_c) * 1000, 1),
            # Use service-level gauges (populated by background thread even at 0 requests)
            "cpu":         round(gv("cpu_usage_percent_service",  service=name), 1),
            "ram_mb":      round(gv("ram_usage_mb_service",       service=name), 0),
            "cpu_watts":   round(gv("cpu_power_watts",            service=name), 1),
            "gpu_util":    round(gv("gpu_utilization_percent",    service=name, stage="after"), 1),
            "vram_mb":     round(gv("gpu_memory_used_mb",         service=name, stage="after"), 0),
            "vram_delta":  round(sv("gpu_memory_delta_mb",        service=name), 1),
            "gpu_watts":   round(gv("gpu_power_watts",            service=name), 1),
        }

        was_up = last_up.get(name, True)
        if was_up and not is_up:
            log_crash(name, err or "unreachable", snap)
        last_up[name] = is_up

        if is_up:
            prev_err = last_errors.get(name, 0)
            if snap["errors"] > prev_err:
                log_crash(name, f"error spike → {snap['errors']} total errors", snap)
            last_errors[name] = snap["errors"]
            h = history[name]
            h["ts"].append(ts)
            for k, v in snap.items():
                h[k].append(v)

        results.append({"name": name, "port": svc["port"], "up": is_up,
                         "error": err, **snap,
                         "history": {k: list(v) for k, v in history[name].items()}})
    return results


# ── FastAPI ────────────────────────────────────────────────────────────────────
app = FastAPI(docs_url=None, redoc_url=None)

@app.get("/api/metrics")
def api_metrics():
    return JSONResponse({"services": collect_all(),
                         "crashes":  crash_log[-100:],
                         "ts":       datetime.now().isoformat(timespec="seconds")})

@app.get("/", response_class=HTMLResponse)
def index(): return HTML


# ── Frontend ───────────────────────────────────────────────────────────────────
HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>infra-metrics</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Syne:wght@700;800&display=swap" rel="stylesheet">
<style>
:root{
  --bg:#0e1117;--sf:#161b22;--sf2:#1c2333;--bd:#253047;--tx:#d0d7e3;--mu:#5a6882;
  --gr:#56d364;--ye:#e3b341;--rd:#ff7b72;--bl:#79c0ff;--cy:#56d4dd;--pu:#d2a8ff;--or:#ffa657;
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--tx);font-family:'JetBrains Mono',monospace;font-size:13px}
header{display:flex;align-items:center;gap:16px;padding:16px 28px;border-bottom:1px solid var(--bd);
  background:#0a0e18;position:sticky;top:0;z-index:100;position:relative}
.logo{font-family:'Syne',sans-serif;font-size:20px;font-weight:800;color:#fff}
.logo em{color:var(--cy);font-style:normal}
.live{display:flex;align-items:center;gap:6px;font-size:10px;color:var(--gr);text-transform:uppercase;letter-spacing:1px}
.dot{width:7px;height:7px;border-radius:50%;background:var(--gr);animation:blink 1.4s infinite}
@keyframes blink{0%,100%{opacity:1}50%{opacity:.2}}
#hclock{margin-left:auto;color:var(--mu);font-size:12px}
.prog{height:2px;background:var(--cy);position:absolute;bottom:0;left:0;right:0;
  transform-origin:left;animation:prog 5s linear infinite}
@keyframes prog{from{transform:scaleX(1)}to{transform:scaleX(0)}}
nav{display:flex;background:var(--sf);border-bottom:1px solid var(--bd)}
nav button{background:none;border:none;border-bottom:2px solid transparent;color:var(--mu);
  font-family:inherit;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.8px;
  padding:12px 22px;cursor:pointer;transition:.2s}
nav button.on{color:var(--cy);border-bottom-color:var(--cy)}
nav button:hover:not(.on){color:var(--tx)}
main{padding:24px 28px}
.pane{display:none}.pane.on{display:block}

/* Summary */
#sum{display:flex;background:var(--sf);border:1px solid var(--bd);border-radius:10px;
  margin-bottom:24px;overflow:hidden}
.ss{flex:1;padding:14px 18px;border-right:1px solid var(--bd)}
.ss:last-child{border-right:none}
.sl{font-size:10px;text-transform:uppercase;letter-spacing:.8px;color:var(--mu);margin-bottom:5px}
.sv{font-family:'Syne',sans-serif;font-size:24px;font-weight:800;color:#fff}

/* Cards */
#cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(380px,1fr));gap:16px;margin-bottom:32px}
.card{background:var(--sf);border:1px solid var(--bd);border-radius:10px;overflow:hidden}
.ca{height:3px}.ca.up{background:linear-gradient(90deg,var(--cy),var(--gr))}.ca.dn{background:var(--rd)}.ca.wn{background:var(--ye)}
.ch{display:flex;align-items:center;gap:10px;padding:13px 16px;border-bottom:1px solid var(--bd)}
.sn{font-family:'Syne',sans-serif;font-size:15px;font-weight:800;color:#fff}
.sp{color:var(--mu);font-size:11px;margin-left:auto}
.badge{font-size:10px;font-weight:700;padding:2px 9px;border-radius:20px;letter-spacing:.5px}
.bup{background:rgba(46,168,74,.15);color:var(--gr)}
.bdn{background:rgba(230,57,70,.15);color:var(--rd);animation:blink 1.4s infinite}
.bwn{background:rgba(212,160,23,.15);color:var(--ye)}
.cm{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;padding:14px 16px}
.mt{display:flex;flex-direction:column;gap:3px}
.ml{font-size:10px;text-transform:uppercase;letter-spacing:.5px;color:var(--mu)}
.mv{font-size:15px;font-weight:600;color:#fff}
.mv.wn{color:var(--ye)}.mv.cr{color:var(--rd)}.mv.ok{color:var(--gr)}
.mb{height:3px;border-radius:2px;background:var(--bd);margin-top:4px}
.mf{height:100%;border-radius:2px;transition:width .5s}
.dn-body{padding:16px;color:var(--rd);font-size:12px}

/* Chart sub-nav */
.chart-subnav{display:flex;gap:0;border-bottom:1px solid var(--bd);margin-bottom:20px}
.csn{background:none;border:none;border-bottom:2px solid transparent;color:var(--mu);
  font-family:inherit;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.8px;
  padding:10px 20px;cursor:pointer;transition:.2s}
.csn.on{color:var(--pu);border-bottom-color:var(--pu)}
.csn:hover:not(.on){color:var(--tx)}
.cpane{display:none}.cpane.on{display:block}

#chart-grid-ag,#chart-grid-lv,#chart-grid-cr{display:grid;grid-template-columns:repeat(2,1fr);gap:20px}
.cg-box{background:var(--sf);border:1px solid var(--bd);border-radius:10px;padding:16px}
.cg-title{font-family:'Syne',sans-serif;font-size:13px;font-weight:800;color:#fff;margin-bottom:12px}
.cg-box canvas{height:200px}

/* ── Usage Tab — Activity Monitor style ─────────────────────────── */
.am-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.am-card{background:var(--sf);border:1px solid var(--bd);border-radius:10px;padding:16px;display:flex;flex-direction:column;gap:10px}
.am-header{display:flex;align-items:center;gap:0;border-bottom:1px solid var(--bd);padding-bottom:10px;flex-wrap:wrap;row-gap:6px}
.am-title{font-family:'Syne',sans-serif;font-size:13px;font-weight:800;color:#fff}
.am-cur{font-size:10px;color:var(--mu);margin-left:auto;white-space:nowrap}
.am-legend{display:flex;flex-wrap:wrap;gap:10px;margin-top:8px;width:100%}
.am-leg-item{display:flex;align-items:center;gap:5px;font-size:10px;color:var(--mu)}
.am-swatch{width:8px;height:8px;border-radius:2px;flex-shrink:0}
.am-val{color:var(--tx);font-weight:600;margin-left:2px}
.am-chart-wrap{position:relative;height:190px}

/* Crash log */
#crash-wrap{background:var(--sf);border:1px solid var(--bd);border-radius:10px;overflow:hidden}
.cx-head{padding:14px 20px;border-bottom:1px solid var(--bd);display:flex;align-items:center;gap:12px}
.cx-head h2{font-family:'Syne',sans-serif;font-size:14px;font-weight:800;color:#fff}
.cx-hint{color:var(--mu);font-size:11px;margin-left:auto}
#cx-empty{padding:20px;color:var(--gr);font-size:12px;text-align:center}
table{width:100%;border-collapse:collapse}
th{text-align:left;color:var(--mu);font-size:10px;text-transform:uppercase;letter-spacing:.5px;
  padding:9px 14px;border-bottom:1px solid var(--bd)}
td{padding:9px 14px;border-bottom:1px solid var(--bd);font-size:11px;vertical-align:top}
tr:last-child td{border-bottom:none}
tr:hover td{background:var(--sf2)}
.cts{color:var(--mu);white-space:nowrap;font-size:10px}
.csvc{color:var(--bl);font-weight:700}
.creason{color:var(--rd)}
.cval{color:var(--tx)}
</style>
</head>
<body>
<header>
  <div class="logo">infra<em>·</em>metrics</div>
  <div class="live"><span class="dot"></span>live</div>
  <span id="hclock">—</span>
  <div class="prog"></div>
</header>
<nav>
  <button class="on" onclick="tab('overview',this)">Overview</button>
  <button onclick="tab('charts',this)">Charts</button>
  <button onclick="tab('usage',this)">Usage</button>
  <button onclick="tab('crashes',this)">Crash Log</button>
</nav>
<main>

<!-- OVERVIEW -->
<div id="pane-overview" class="pane on">
  <div id="sum">
    <div class="ss"><div class="sl">Services</div><div class="sv" id="s-tot">—</div></div>
    <div class="ss"><div class="sl">Online</div><div class="sv" id="s-up" style="color:var(--gr)">—</div></div>
    <div class="ss"><div class="sl">Down</div><div class="sv" id="s-dn" style="color:var(--rd)">—</div></div>
    <div class="ss"><div class="sl">Active Agents</div><div class="sv" id="s-ag" style="color:var(--cy)">—</div></div>
    <div class="ss"><div class="sl">Total Errors</div><div class="sv" id="s-er" style="color:var(--ye)">—</div></div>
    <div class="ss"><div class="sl">Crashes Today</div><div class="sv" id="s-cr" style="color:var(--rd)">—</div></div>
  </div>
  <div id="cards"></div>
</div>

<!-- CHARTS -->
<div id="pane-charts" class="pane">
  <div class="chart-subnav">
    <button class="csn on" onclick="chartPage('agents-gpu',this)">Agents &amp; GPU</button>
    <button class="csn" onclick="chartPage('lat-vram',this)">Latency &amp; VRAM</button>
    <button class="csn" onclick="chartPage('cpu-ram',this)">CPU &amp; RAM</button>
  </div>
  <div id="cpane-agents-gpu" class="cpane on"><div id="chart-grid-ag"></div></div>
  <div id="cpane-lat-vram"   class="cpane"><div id="chart-grid-lv"></div></div>
  <div id="cpane-cpu-ram"    class="cpane"><div id="chart-grid-cr"></div></div>
</div>

<!-- USAGE — Activity Monitor style rolling charts -->
<div id="pane-usage" class="pane">
  <div class="am-grid">
    <div class="am-card">
      <div class="am-header">
        <span class="am-title">CPU Usage</span>
        <span class="am-cur" id="am-cur-cpu">—</span>
        <div class="am-legend" id="am-leg-cpu"></div>
      </div>
      <div class="am-chart-wrap"><canvas id="uc-cpu"></canvas></div>
    </div>
    <div class="am-card">
      <div class="am-header">
        <span class="am-title">System RAM</span>
        <span class="am-cur" id="am-cur-ram">—</span>
        <div class="am-legend" id="am-leg-ram"></div>
      </div>
      <div class="am-chart-wrap"><canvas id="uc-ram"></canvas></div>
    </div>
    <div class="am-card">
      <div class="am-header">
        <span class="am-title">GPU Utilisation</span>
        <span class="am-cur" id="am-cur-gpu">—</span>
        <div class="am-legend" id="am-leg-gpu"></div>
      </div>
      <div class="am-chart-wrap"><canvas id="uc-gpu"></canvas></div>
    </div>
    <div class="am-card">
      <div class="am-header">
        <span class="am-title">VRAM Used</span>
        <span class="am-cur" id="am-cur-vram">—</span>
        <div class="am-legend" id="am-leg-vram"></div>
      </div>
      <div class="am-chart-wrap"><canvas id="uc-vram"></canvas></div>
    </div>
    <div class="am-card">
      <div class="am-header">
        <span class="am-title">CPU Power</span>
        <span class="am-cur" id="am-cur-cpuw">—</span>
        <div class="am-legend" id="am-leg-cpuw"></div>
      </div>
      <div class="am-chart-wrap"><canvas id="uc-cpuw"></canvas></div>
    </div>
    <div class="am-card">
      <div class="am-header">
        <span class="am-title">GPU Power</span>
        <span class="am-cur" id="am-cur-gpuw">—</span>
        <div class="am-legend" id="am-leg-gpuw"></div>
      </div>
      <div class="am-chart-wrap"><canvas id="uc-gpuw"></canvas></div>
    </div>
  </div>
</div>

<!-- CRASHES -->
<div id="pane-crashes" class="pane">
  <div id="crash-wrap">
    <div class="cx-head">
      <h2>Crash &amp; Event Log</h2>
      <span class="cx-hint">Saved to crash_logs/crashes_YYYY-MM-DD.jsonl</span>
    </div>
    <div id="cx-empty">✓ No crashes recorded this session</div>
    <table id="cx-table" style="display:none">
      <thead><tr>
        <th>Time</th><th>Service</th><th>Reason</th>
        <th>Agents</th><th>CPU</th><th>RAM</th><th>GPU</th><th>VRAM</th><th>Errors</th>
      </tr></thead>
      <tbody id="cx-body"></tbody>
    </table>
  </div>
</div>
</main>

<script>
// ── Globals ────────────────────────────────────────────────────────────────────
let sparkCharts={}, fullCharts={}, lastData=null;
const COLORS=['#00d4d4','#3d9be9','#2ea84a','#d4a017','#e63946','#9d6fe8','#e07c2a'];

// ── Helpers ────────────────────────────────────────────────────────────────────
const mb = v => v>=1024?(v/1024).toFixed(1)+' GB':Math.round(v)+' MB';
const vc = (v,w,c) => v>=c?'cr':v>=w?'wn':'';
function mbar(pct) {
  const col = pct>=85?'var(--rd)':pct>=60?'var(--ye)':'var(--cy)';
  return `<div class="mb"><div class="mf" style="width:${Math.min(pct,100)}%;background:${col}"></div></div>`;
}

// ── Tab switching ──────────────────────────────────────────────────────────────
function tab(id, btn) {
  document.querySelectorAll('.pane').forEach(p=>p.classList.remove('on'));
  document.querySelectorAll('nav button').forEach(b=>b.classList.remove('on'));
  document.getElementById('pane-'+id).classList.add('on');
  btn.classList.add('on');
  if(id==='charts' && lastData) renderFullCharts(lastData.services);
  if(id==='usage'  && lastData) renderUsageTab(lastData.services);
}

// ── Overview cards ─────────────────────────────────────────────────────────────
function renderCard(s) {
  const ac = !s.up?'dn':s.errors>0?'wn':'up';
  const badge = !s.up?'<span class="badge bdn">DOWN</span>':s.errors>0?'<span class="badge bwn">WARN</span>':'<span class="badge bup">UP</span>';
  let body='';
  if(!s.up){
    body=`<div class="dn-body">✕ ${s.error||'unreachable'}</div>`;
  } else {
    body=`
    <div class="cm">
      <div class="mt"><span class="ml">Agents</span><span class="mv ${vc(s.agents,10,30)}">${s.agents}</span><span style="font-size:9px;color:var(--mu)"> peak&nbsp;${s.peak_agents}</span></div>
      <div class="mt"><span class="ml">Requests</span><span class="mv">${s.requests.toLocaleString()}</span></div>
      <div class="mt"><span class="ml">Latency</span><span class="mv ${vc(s.latency_ms,300,1000)}">${s.latency_ms}ms</span></div>
      <div class="mt"><span class="ml">CPU</span><span class="mv ${vc(s.cpu,60,85)}">${s.cpu}%</span>${mbar(s.cpu)}</div>
      <div class="mt"><span class="ml">CPU Power</span><span class="mv">${s.cpu_watts>0?s.cpu_watts.toFixed(1)+' W':'—'}</span></div>
      <div class="mt"><span class="ml">Sys RAM</span><span class="mv">${mb(s.ram_mb)}</span></div>
      <div class="mt"><span class="ml">Errors</span><span class="mv ${s.errors>0?'cr':''}">${s.errors}</span></div>
      <div class="mt"><span class="ml">GPU</span><span class="mv ${vc(s.gpu_util,60,85)}">${s.gpu_util>0?s.gpu_util+'%':'—'}</span>${s.gpu_util>0?mbar(s.gpu_util):''}</div>
      <div class="mt"><span class="ml">GPU Power</span><span class="mv">${s.gpu_watts>0?s.gpu_watts.toFixed(0)+' W':'—'}</span></div>
      <div class="mt"><span class="ml">VRAM</span><span class="mv">${s.vram_mb>0?mb(s.vram_mb):'—'}</span></div>
      <div class="mt"><span class="ml">VRAM Δ</span><span class="mv ${s.vram_delta>500?'wn':''}">${s.vram_delta>0?mb(s.vram_delta):'—'}</span></div>
    </div>`;
  }
  return `<div class="card"><div class="ca ${ac}"></div>
    <div class="ch">${badge}<span class="sn">${s.name}</span><span class="sp">:${s.port}</span></div>
    ${body}</div>`;
}

// ── Full multi-service charts ──────────────────────────────────────────────────
const CHART_PAGES = {
  'agents-gpu': [{key:'agents',title:'Active Agents',unit:'agents'},{key:'gpu_util',title:'GPU Utilisation',unit:'%'}],
  'lat-vram':   [{key:'latency_ms',title:'Avg Latency',unit:'ms'},{key:'vram_mb',title:'GPU VRAM',unit:'MB'}],
  'cpu-ram':    [{key:'cpu',title:'CPU Usage',unit:'%'},{key:'ram_mb',title:'Sys RAM Usage',unit:'MB'}],
};
const GRID_IDS = {'agents-gpu':'chart-grid-ag','lat-vram':'chart-grid-lv','cpu-ram':'chart-grid-cr'};

function chartPage(id, btn) {
  document.querySelectorAll('.cpane').forEach(p=>p.classList.remove('on'));
  document.querySelectorAll('.csn').forEach(b=>b.classList.remove('on'));
  document.getElementById('cpane-'+id).classList.add('on');
  btn.classList.add('on');
  if(lastData) renderFullCharts(lastData.services);
}

const yMax = {};
function stableMax(key, datasets) {
  const allVals = datasets.flatMap(d=>d.data).filter(v=>v!=null&&!isNaN(v));
  const dataMax = allVals.length ? Math.max(...allVals) : 0;
  const floors = {gpu_util:100, cpu:100, latency_ms:500, agents:10, ram_mb:512, vram_mb:512};
  if(!yMax[key]) yMax[key] = Math.max(dataMax * 1.2, floors[key]||10);
  else if(dataMax > yMax[key]) yMax[key] = dataMax * 1.1;
  return yMax[key];
}

function renderFullCharts(svcs) {
  const fixedLabels = Array.from({length:60}, (_,i)=>i);
  Object.entries(CHART_PAGES).forEach(([page, defs]) => {
    const grid = document.getElementById(GRID_IDS[page]);
    if(!grid) return;
    if(!grid.innerHTML) {
      grid.innerHTML = defs.map(d=>`
        <div class="cg-box">
          <div class="cg-title">${d.title}</div>
          <canvas id="fc-${d.key}" height="200"></canvas>
        </div>`).join('');
    }
    defs.forEach(({key}) => {
      const pad = arr => { const a=[...arr]; while(a.length<60) a.unshift(null); return a.slice(-60); };
      const datasets = svcs.filter(s=>s.up&&(s.history?.[key]||[]).length).map((s,i)=>({
        label: s.name,
        data: pad(s.history[key]||[]),
        borderColor: COLORS[i%COLORS.length],
        backgroundColor: COLORS[i%COLORS.length]+'18',
        borderWidth:2, pointRadius:0, tension:0.3, fill:true, spanGaps:false
      }));
      const id=`fc-${key}`;
      if(!datasets.length) return;
      const maxY = stableMax(key, datasets);
      if(fullCharts[id]) {
        fullCharts[id].data.datasets.forEach((d,i)=>{ if(datasets[i]) d.data=datasets[i].data; });
        fullCharts[id].options.scales.y.max = maxY;
        fullCharts[id].update('none');
        return;
      }
      const ctx=document.getElementById(id); if(!ctx) return;
      fullCharts[id]=new Chart(ctx,{type:'line',data:{labels:fixedLabels,datasets},options:{
        responsive:true, maintainAspectRatio:false,
        plugins:{legend:{labels:{color:'#8b9ab5',font:{family:'JetBrains Mono',size:10}}}},
        scales:{
          x:{display:false},
          y:{ticks:{color:'#3d4f63',font:{size:10}},grid:{color:'#1c2433'},
             beginAtZero:true, min:0, max:maxY}
        },
        animation:false,
        transitions:{active:{animation:{duration:0}},resize:{animation:{duration:0}},show:{animation:{duration:0}},hide:{animation:{duration:0}}}
      }});
    });
  });
}

// ══════════════════════════════════════════════════════════════════════════════
// USAGE TAB — Activity Monitor style rolling time-series
// 4 panels always visible: CPU, RAM, GPU, VRAM
// Each line = one service, scrolls left every 5 s, same mechanic as Charts tab
// ══════════════════════════════════════════════════════════════════════════════

let usageCharts = {};
const amYMax    = {};   // stable Y ceiling — only grows

const AM_DEFS = [
  { canvasId:'uc-cpu',  legId:'am-leg-cpu',  curId:'am-cur-cpu',
    key:'cpu',       title:'CPU Usage',       unit:'%',  fixedMax:100,  floor:100 },
  { canvasId:'uc-ram',  legId:'am-leg-ram',  curId:'am-cur-ram',
    key:'ram_mb',    title:'System RAM',      unit:' MB',fixedMax:null, floor:512 },
  { canvasId:'uc-gpu',  legId:'am-leg-gpu',  curId:'am-cur-gpu',
    key:'gpu_util',  title:'GPU Utilisation', unit:'%',  fixedMax:100,  floor:100 },
  { canvasId:'uc-vram', legId:'am-leg-vram', curId:'am-cur-vram',
    key:'vram_mb',   title:'VRAM Used',       unit:' MB',fixedMax:null, floor:512 },
  { canvasId:'uc-cpuw', legId:'am-leg-cpuw', curId:'am-cur-cpuw',
    key:'cpu_watts', title:'CPU Power',       unit:' W', fixedMax:null, floor:50  },
  { canvasId:'uc-gpuw', legId:'am-leg-gpuw', curId:'am-cur-gpuw',
    key:'gpu_watts', title:'GPU Power',       unit:' W', fixedMax:null, floor:50  },
];

// Pad history array to exactly 60 points (null-fill the front)
function amPad(arr) {
  const a = [...arr];
  while(a.length < 60) a.unshift(null);
  return a.slice(-60);
}

// Y ceiling that only grows — prevents chart rescaling on every tick
function amCeil(key, floor, datasets) {
  const allVals = datasets.flatMap(d => d.data).filter(v => v != null && !isNaN(v));
  const dataMax = allVals.length ? Math.max(...allVals) : 0;
  if(!amYMax[key]) amYMax[key] = Math.max(dataMax * 1.25, floor);
  else if(dataMax > amYMax[key]) amYMax[key] = dataMax * 1.1;
  return amYMax[key];
}

// Format a value for display in the legend / header
function amFmt(val, unit) {
  if(val == null || isNaN(val)) return '—';
  if(unit === ' MB') return mb(val);
  return val + unit;
}

function renderUsageTab(svcs) {
  const fixedLabels = Array.from({length:60}, (_, i) => i);
  const upSvcs = svcs.filter(s => s.up);

  AM_DEFS.forEach(({ canvasId, legId, curId, key, unit, fixedMax, floor }) => {

    // Build datasets from history (same shape as Charts tab)
    const datasets = upSvcs
      .filter(s => (s.history?.[key] || []).length)
      .map((s, i) => ({
        label: s.name,
        data: amPad(s.history[key] || []),
        borderColor:     COLORS[i % COLORS.length],
        backgroundColor: COLORS[i % COLORS.length] + '18',
        borderWidth: 1.5,
        pointRadius: 0,
        tension: 0.35,
        fill: true,
        spanGaps: false,
      }));

    const maxY = fixedMax || amCeil(key, floor, datasets);

    // ── Update existing chart ──────────────────────────────────────
    if(usageCharts[canvasId]) {
      const ch = usageCharts[canvasId];
      // Sync dataset count (services may come/go)
      while(ch.data.datasets.length > datasets.length) ch.data.datasets.pop();
      datasets.forEach((ds, i) => {
        if(ch.data.datasets[i]) {
          ch.data.datasets[i].data = ds.data;
        } else {
          ch.data.datasets.push(ds);
        }
      });
      ch.options.scales.y.max = maxY;
      ch.update('none');
    } else {
      // ── Create chart ───────────────────────────────────────────────
      const ctx = document.getElementById(canvasId);
      if(!ctx || !datasets.length) return;
      usageCharts[canvasId] = new Chart(ctx, {
        type: 'line',
        data: { labels: fixedLabels, datasets },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          animation: false,
          transitions: {
            active:{animation:{duration:0}},
            resize:{animation:{duration:0}},
          },
          plugins: {
            legend: { display: false },
            tooltip: {
              mode: 'index',
              intersect: false,
              backgroundColor: '#1c2333',
              borderColor: '#253047',
              borderWidth: 1,
              titleColor: '#5a6882',
              bodyColor: '#d0d7e3',
              titleFont: { family:'JetBrains Mono', size:10 },
              bodyFont:  { family:'JetBrains Mono', size:11 },
              callbacks: {
                title: () => '',
                label: c => `  ${c.dataset.label}  ${c.parsed.y != null ? amFmt(c.parsed.y, unit) : '—'}`,
              }
            }
          },
          scales: {
            x: { display: false },
            y: {
              beginAtZero: true, min: 0, max: maxY,
              ticks: {
                color: '#3d4f63',
                font: { size: 9, family:'JetBrains Mono' },
                maxTicksLimit: 5,
                callback: v => unit === ' MB' ? (v >= 1024 ? (v/1024).toFixed(0)+'G' : v+'M') : v + unit,
              },
              grid: { color: '#1c2433' },
            }
          }
        }
      });
    }

    // ── Update legend with current values ─────────────────────────
    const legEl = document.getElementById(legId);
    const curEl = document.getElementById(curId);
    if(legEl) {
      legEl.innerHTML = upSvcs.map((s, i) => `
        <span class="am-leg-item">
          <span class="am-swatch" style="background:${COLORS[i%COLORS.length]}"></span>
          ${s.name}<span class="am-val">${amFmt(s[key], unit)}</span>
        </span>`).join('');
    }
    // Header: show highest current value across services
    if(curEl && upSvcs.length) {
      const vals = upSvcs.map(s => s[key] || 0);
      const peakIdx = vals.indexOf(Math.max(...vals));
      const peak = vals[peakIdx];
      curEl.textContent = `peak ${amFmt(peak, unit)} · ${upSvcs[peakIdx]?.name || ''}`;
    }
  });
}

// ── Crash log ──────────────────────────────────────────────────────────────────
function renderCrashes(crashes) {
  const empty=document.getElementById('cx-empty');
  const table=document.getElementById('cx-table');
  const tbody=document.getElementById('cx-body');
  const today=new Date().toISOString().slice(0,10);
  const visible=crashes.filter(c=>!c.reason.includes('recovered'));
  const todayN=visible.filter(c=>c.ts.startsWith(today)).length;
  document.getElementById('s-cr').textContent=todayN;
  if(!visible.length){empty.style.display='';table.style.display='none';return;}
  empty.style.display='none';table.style.display='';
  tbody.innerHTML=[...visible].reverse().map(c=>`<tr>
    <td class="cts">${c.ts}</td>
    <td class="csvc">${c.service}</td>
    <td class="creason">${c.reason}</td>
    <td class="cval">${c.agents??'—'}</td>
    <td class="cval">${c.cpu!=null?c.cpu+'%':'—'}</td>
    <td class="cval">${c.ram_mb?Math.round(c.ram_mb)+' MB':'—'}</td>
    <td class="cval">${c.gpu_util!=null?c.gpu_util+'%':'—'}</td>
    <td class="cval">${c.vram_mb?Math.round(c.vram_mb)+' MB':'—'}</td>
    <td class="cval ${c.errors>0?'creason':''}">${c.errors??'—'}</td>
  </tr>`).join('');
}

// ── Main refresh loop ──────────────────────────────────────────────────────────
async function refresh() {
  try {
    const res=await fetch('/api/metrics');
    const data=await res.json();
    lastData=data;
    const svcs=data.services;
    const up=svcs.filter(s=>s.up).length;
    document.getElementById('s-tot').textContent=svcs.length;
    document.getElementById('s-up').textContent=up;
    document.getElementById('s-dn').textContent=svcs.length-up;
    document.getElementById('s-ag').textContent=svcs.reduce((a,s)=>a+s.agents,0);
    document.getElementById('s-er').textContent=svcs.reduce((a,s)=>a+s.errors,0);

    document.getElementById('cards').innerHTML=svcs.map(renderCard).join('');

    if(document.getElementById('pane-charts').classList.contains('on')) renderFullCharts(svcs);
    if(document.getElementById('pane-usage').classList.contains('on'))  renderUsageTab(svcs);
    renderCrashes(data.crashes);
  } catch(e){ console.error(e); }
}

setInterval(()=>{ document.getElementById('hclock').textContent=new Date().toLocaleTimeString(); },1000);
refresh();
setInterval(refresh,5000);
</script>
</body>
</html>"""

# ── Entry ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port",   default=9999, type=int)
    parser.add_argument("--host",   default="0.0.0.0")
    parser.add_argument("--config", default="monitoring/services.yaml")
    args = parser.parse_args()

    if os.path.exists(args.config):
        SERVICES.clear()
        SERVICES.extend(load_services(args.config))
        print(f"Loaded {len(SERVICES)} services from {args.config}")
    else:
        print("Config not found — using defaults")

    load_crash_history()
    print(f"Loaded {len(crash_log)} crash entries from history")
    print(f"\nDashboard  → http://localhost:{args.port}")
    print(f"Crash logs → {CRASH_DIR.resolve()}/crashes_YYYY-MM-DD.jsonl\n")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")