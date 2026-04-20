#!/usr/bin/env python3
"""
Build script for pitcher-workload-research.

Reads:
  data/csvs/*.csv           — TruMedia exports
  data/metadata.json        — pitcher meta (org, year, age, draft, etc.)
  data/injury_flags.json    — injury context per pitcher
  data/weather_flags.json   — gap attribution per pitcher
  data/org_findings.json    — per-org qualitative findings
  data/overview_findings.json — top-level callouts, key patterns, age analysis

Writes:
  docs/index.html           — standalone deliverable (embeds all data + logic)

Usage:
  python3 scripts/build.py

Adding a new pitcher:
  1. Drop TruMedia CSV export in data/csvs/
  2. Add entry to data/metadata.json (keyed by surname)
  3. Optionally add injury/weather notes to the respective JSON files
  4. Run this script
  5. Commit & push
"""

import csv
import json
import pathlib
import datetime as dt
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CSV_DIR = DATA / "csvs"
OUT = ROOT / "docs" / "index.html"


# -----------------------------------------------------------------------------
# Read inputs
# -----------------------------------------------------------------------------

def load_json(name):
    with open(DATA / name) as f:
        return json.load(f)

meta = load_json("metadata.json")
injuries = load_json("injury_flags.json")
weather = load_json("weather_flags.json")
orgs = load_json("org_findings.json")
overview = load_json("overview_findings.json")

# Strip out _comment keys
meta = {k: v for k, v in meta.items() if not k.startswith("_")}
injuries = {k: v for k, v in injuries.items() if not k.startswith("_")}
weather = {k: v for k, v in weather.items() if not k.startswith("_")}
orgs = {k: v for k, v in orgs.items() if not k.startswith("_")}


# -----------------------------------------------------------------------------
# Process CSVs
# -----------------------------------------------------------------------------

def ip_to_outs(ip):
    ip = float(ip)
    whole = int(ip)
    frac = round((ip - whole) * 10)
    return whole * 3 + frac

def ip_to_decimal(ip):
    outs = ip_to_outs(ip)
    return round(outs / 3.0, 2)

def start_based_acwr(pitches):
    """Uncoupled rolling 4-start ACWR: current P / avg of previous 3."""
    out = []
    for i in range(len(pitches)):
        if i < 3:
            out.append(None)
        else:
            chronic = sum(pitches[i-3:i]) / 3.0
            if chronic > 0:
                out.append(round(pitches[i] / chronic, 3))
            else:
                out.append(None)
    return out

def process_pitcher_csv(csv_path):
    """Read one TruMedia CSV and return structured starts list."""
    rows = []
    with open(csv_path) as f:
        for r in csv.DictReader(f):
            gd = r['gameDay']
            date = dt.datetime.strptime(gd, '%m/%d/%y')
            rows.append({
                'date': date,
                'gameDay': gd,
                'ip': float(r['IP']),
                'p': int(r['P']),
                'result': r.get('result', ''),
                'opponent': r.get('opponent', ''),
                'team': r.get('teamWithLevel', '')
            })
    rows.sort(key=lambda x: x['date'])
    pitches = [r['p'] for r in rows]
    acwrs = start_based_acwr(pitches)

    starts = []
    prev_date = None
    for i, r in enumerate(rows):
        rest = (r['date'] - prev_date).days if prev_date else 0
        starts.append({
            'd': r['date'].strftime('%m/%d'),
            'ymd': r['date'].strftime('%Y-%m-%d'),
            'ip': r['ip'],
            'ipF': ip_to_decimal(r['ip']),
            'p': r['p'],
            'r': r['result'][:1] if r['result'] else '',
            'fr': r['result'],
            'opp': r['opponent'],
            'team': r['team'],
            'rest': rest,
            'acwr': acwrs[i]
        })
        prev_date = r['date']
    return starts

pitcher_data = {}
for name, m in meta.items():
    csv_path = CSV_DIR / m['csv']
    if not csv_path.exists():
        print(f"WARNING: {csv_path} not found, skipping {name}", file=sys.stderr)
        continue
    pitcher_data[name] = {'starts': process_pitcher_csv(csv_path)}
    print(f"  processed {name}: {len(pitcher_data[name]['starts'])} starts", file=sys.stderr)


# -----------------------------------------------------------------------------
# Build-up profile auto-computation (slope, group, note)
# -----------------------------------------------------------------------------

def compute_buildup(starts):
    """First 10 starts buildup slope/group."""
    first_n = min(10, len(starts))
    if first_n < 3:
        return None
    pcs = [s['p'] for s in starts[:first_n]]
    peak_idx = max(range(first_n), key=lambda i: pcs[i])
    slope = (pcs[peak_idx] - pcs[0]) / max(peak_idx, 1) if peak_idx > 0 else 0
    if slope >= 4:
        group = 'fast'
    elif slope >= 2:
        group = 'steady'
    elif slope >= 0:
        group = 'flat'
    else:
        group = 'declining'
    return {
        'pcs': pcs,
        'peak': peak_idx + 1,
        'peakP': pcs[peak_idx],
        'slope': round(slope, 1),
        'group': group
    }

build_data = {name: compute_buildup(d['starts']) for name, d in pitcher_data.items()}


# -----------------------------------------------------------------------------
# All-Star break auto-detection (July window)
# -----------------------------------------------------------------------------

def detect_asb(starts):
    """Find the largest gap in mid-July window."""
    window = [s for s in starts if '07-' in s['ymd'][5:8] and 6 <= int(s['ymd'][8:10]) <= 30]
    if len(window) < 2:
        return None
    for i, s in enumerate(window):
        if s['rest'] >= 8 and 15 <= int(s['ymd'][8:10]) <= 28:
            idx = starts.index(s)
            if idx == 0:
                continue
            pre = starts[idx - 1]
            post = s
            gap = post['rest']
            extra = gap - 7
            return {
                'pre': f"{pre['d']} · {pre['ip']}/{pre['p']}",
                'post': f"{post['d']} · {post['ip']}/{post['p']}",
                'gap': gap,
                'extra': extra
            }
    return None

asb_data = {name: detect_asb(d['starts']) for name, d in pitcher_data.items()}


# -----------------------------------------------------------------------------
# Generate HTML
# -----------------------------------------------------------------------------

ORG_COLOR = {
    'MIL': '#BA7517', 'SEA': '#185FA5', 'NYM': '#534AB7', 'ATL': '#A32D2D',
    'TB': '#1D9E75', 'CLE': '#D4537E', 'NYY/CHW': '#5F5E5A', 'LAD': '#378ADD',
    'MIA': '#0F766E', 'NYY': '#D0D6D9', 'CLE/WAS': '#E4572E', 'WAS': '#AB0003'
}

# Inject ORG_COLOR and order into overview.
all_pitchers = list(meta.keys())

# Generate data-js injection payload
js_payload = {
    'PITCHER_DATA': pitcher_data,
    'META': meta,
    'INJURIES': injuries,
    'WEATHER': weather,
    'ORGS': orgs,
    'OVERVIEW': overview,
    'BUILD_DATA': build_data,
    'ASB_DATA': asb_data,
    'ORG_COLOR': ORG_COLOR,
    'GENERATED': dt.datetime.now().strftime('%B %Y')
}

html_template = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>MiLB Pitcher Workload Research</title>
<style>
:root {
  --bg: #faf8f3; --bg-card: #ffffff; --bg-subtle: #f0ece2; --bg-hover: #ebe6d8;
  --text: #1c1c1c; --text-muted: #555150; --text-tertiary: #8c8984;
  --border: rgba(0,0,0,0.08); --border-strong: rgba(0,0,0,0.18);
  --accent: #c2410c; --accent-soft: #fee4d0; --accent-text: #7c2d12;
  --good: #0f766e; --good-soft: #ccfbf1;
  --warn: #b45309; --warn-soft: #fef3c7;
  --danger: #991b1b; --danger-soft: #fee2e2;
  --info: #1d4ed8; --info-soft: #dbeafe;
  --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #1a1816; --bg-card: #242120; --bg-subtle: #2c2926; --bg-hover: #36322d;
    --text: #e8e3d8; --text-muted: #a9a39a; --text-tertiary: #6b6760;
    --border: rgba(255,255,255,0.08); --border-strong: rgba(255,255,255,0.18);
    --accent: #fb923c; --accent-soft: #3f2418; --accent-text: #fdba74;
    --good: #5eead4; --good-soft: #134e4a;
    --warn: #fbbf24; --warn-soft: #3d2f0a;
    --danger: #fca5a5; --danger-soft: #4a1010;
    --info: #93c5fd; --info-soft: #1e2846;
  }
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body { margin: 0; font-family: var(--sans); background: var(--bg); color: var(--text); font-size: 14px; line-height: 1.5; -webkit-font-smoothing: antialiased; }
.container { max-width: 1200px; margin: 0 auto; padding: 0 20px; }
header.masthead { border-bottom: 1px solid var(--border); padding: 28px 0 24px; }
h1 { font-size: 22px; font-weight: 600; margin: 0 0 4px; letter-spacing: -0.01em; }
.subtitle { font-size: 13px; color: var(--text-muted); margin-bottom: 16px; }
.meta-bar { display: flex; gap: 16px; flex-wrap: wrap; font-size: 11px; color: var(--text-tertiary); padding-top: 8px; border-top: 1px dashed var(--border); }
.meta-bar span strong { color: var(--text-muted); font-weight: 500; }
nav.main-nav { background: var(--bg); border-bottom: 1px solid var(--border); position: sticky; top: 0; z-index: 50; backdrop-filter: blur(8px); }
nav.main-nav .container { display: flex; gap: 2px; overflow-x: auto; }
nav.main-nav button { background: transparent; border: none; padding: 12px 14px; font-size: 13px; color: var(--text-muted); cursor: pointer; font-family: inherit; border-bottom: 2px solid transparent; margin-bottom: -1px; font-weight: 500; letter-spacing: -0.005em; white-space: nowrap; }
nav.main-nav button.active { color: var(--accent); border-bottom-color: var(--accent); }
nav.main-nav button:hover:not(.active) { color: var(--text); }
main { padding: 24px 0 80px; }
.tab-panel { display: none; }
.tab-panel.active { display: block; }
h2 { font-size: 18px; font-weight: 600; margin: 28px 0 6px; letter-spacing: -0.01em; }
h2:first-child { margin-top: 0; }
h3 { font-size: 14px; font-weight: 600; margin: 20px 0 8px; color: var(--text); }
p { margin: 0 0 12px; }
.lede { font-size: 14.5px; color: var(--text-muted); margin-bottom: 20px; line-height: 1.65; max-width: 780px; }
.card { background: var(--bg-card); border: 1px solid var(--border); border-radius: 10px; padding: 16px 18px; margin-bottom: 14px; }
.stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 10px; margin-bottom: 16px; }
.stat { background: var(--bg-card); border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; }
.stat-label { font-size: 10px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--text-tertiary); margin-bottom: 3px; }
.stat-value { font-size: 20px; font-weight: 600; letter-spacing: -0.02em; }
.stat-sub { font-size: 11px; color: var(--text-muted); font-weight: 400; }
.callout { border-radius: 8px; padding: 10px 12px; margin-bottom: 12px; font-size: 12.5px; line-height: 1.55; }
.callout-danger { background: var(--danger-soft); color: var(--danger); }
.callout-warn { background: var(--warn-soft); color: var(--warn); }
.callout-info { background: var(--info-soft); color: var(--info); }
.callout-good { background: var(--good-soft); color: var(--good); }
.callout-accent { background: var(--accent-soft); color: var(--accent-text); }
.callout strong { font-weight: 600; }
.sub-nav { display: flex; gap: 0; flex-wrap: wrap; border-bottom: 1px solid var(--border); margin-bottom: 18px; overflow-x: auto; }
.sub-nav button { background: transparent; border: none; padding: 7px 11px; font-size: 12px; color: var(--text-muted); cursor: pointer; font-family: inherit; border-bottom: 2px solid transparent; margin-bottom: -1px; white-space: nowrap; }
.sub-nav button.active { color: var(--text); border-bottom-color: var(--text); font-weight: 500; }
.sub-nav button .org-tag { font-size: 9px; color: var(--text-tertiary); margin-left: 3px; }
.sub-nav button.active .org-tag { color: var(--text-muted); }
table { width: 100%; border-collapse: collapse; font-size: 12px; }
th, td { padding: 6px 8px; text-align: left; border-bottom: 1px solid var(--border); }
th { font-weight: 500; color: var(--text-muted); font-size: 10px; text-transform: uppercase; letter-spacing: 0.03em; background: var(--bg-subtle); }
.table-wrap { border: 1px solid var(--border); border-radius: 8px; overflow: hidden; margin-bottom: 14px; }
.chart-wrap { position: relative; height: 240px; margin: 10px 0 18px; }
.chart-wrap.tall { height: 280px; }
.chart-wrap.small { height: 90px; }
.calendar-grid { display: grid; grid-template-columns: repeat(6, 1fr); gap: 10px; margin-bottom: 18px; }
.cal-month { min-width: 0; }
.cal-month-name { font-size: 10px; font-weight: 600; color: var(--text-muted); text-align: center; margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.04em; }
.cal-dow { display: grid; grid-template-columns: repeat(7, 1fr); gap: 1px; margin-bottom: 2px; }
.cal-dow span { font-size: 8px; text-align: center; color: var(--text-tertiary); }
.cal-days { display: grid; grid-template-columns: repeat(7, 1fr); gap: 1px; }
.cal-cell { min-height: 26px; border-radius: 3px; display: flex; flex-direction: column; align-items: center; justify-content: center; font-size: 8px; padding: 1px; }
.cal-cell.empty { color: var(--text-tertiary); }
.cal-cell.start .daynum { font-size: 8px; font-weight: 600; line-height: 1.1; }
.cal-cell.start .ipval { font-size: 7px; opacity: 0.85; line-height: 1.1; }
.cal-cell.short { outline: 1.5px solid currentColor; outline-offset: -1px; }
.legend-row { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 10px; font-size: 10px; color: var(--text-muted); }
.legend-row > span { display: inline-flex; align-items: center; gap: 4px; }
.legend-swatch { width: 9px; height: 9px; border-radius: 2px; display: inline-block; }
.aftermath-grid { border: 1px solid var(--border); border-radius: 8px; overflow: hidden; margin-bottom: 14px; }
.aftermath-head { display: grid; grid-template-columns: 60px 1fr 50px 1fr; font-size: 10px; padding: 6px 10px; background: var(--bg-subtle); color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.03em; font-weight: 500; }
.aftermath-row { display: grid; grid-template-columns: 60px 1fr 50px 1fr; font-size: 11.5px; padding: 7px 10px; border-top: 1px solid var(--border); align-items: center; }
.aftermath-row .pct { color: var(--text-tertiary); font-size: 10px; }
.pill { display: inline-block; padding: 1px 7px; border-radius: 3px; font-size: 9px; font-weight: 500; letter-spacing: 0.02em; }
.pill-good { background: var(--good-soft); color: var(--good); }
.pill-warn { background: var(--warn-soft); color: var(--warn); }
.pill-danger { background: var(--danger-soft); color: var(--danger); }
.pill-info { background: var(--info-soft); color: var(--info); }
.pill-neutral { background: var(--bg-subtle); color: var(--text-muted); }
.pill-accent { background: var(--accent-soft); color: var(--accent-text); }
.scorecard { border: 1px solid var(--border); border-radius: 8px; overflow: hidden; margin-bottom: 14px; }
.scorecard-head { display: grid; grid-template-columns: 1.3fr 0.5fr 0.5fr 0.7fr 1.5fr 0.5fr; font-size: 10px; padding: 7px 12px; background: var(--bg-subtle); color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.04em; gap: 8px; font-weight: 500; }
.scorecard-row { display: grid; grid-template-columns: 1.3fr 0.5fr 0.5fr 0.7fr 1.5fr 0.5fr; font-size: 11.5px; padding: 7px 12px; border-top: 1px solid var(--border); gap: 8px; align-items: center; cursor: pointer; transition: background 0.12s; }
.scorecard-row:hover { background: var(--bg-hover); }
.bar-wrap { flex: 1; height: 9px; background: var(--bg-subtle); border-radius: 3px; position: relative; overflow: hidden; }
.bar-fill { position: absolute; left: 0; top: 0; height: 100%; border-radius: 3px; }
.inline-bar { display: flex; align-items: center; gap: 8px; }
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 16px; }
.three-col { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 12px; margin-bottom: 16px; }
@media (max-width: 700px) {
  .two-col, .three-col { grid-template-columns: 1fr; }
  .calendar-grid { grid-template-columns: repeat(3, 1fr); }
  .scorecard-head, .scorecard-row { grid-template-columns: 1fr 0.5fr 0.7fr 1.2fr; gap: 6px; padding: 6px 8px; }
  .scorecard-head > :nth-child(2), .scorecard-row > :nth-child(2) { display: none; }
  .scorecard-head > :nth-child(3), .scorecard-row > :nth-child(3) { display: none; }
  .aftermath-head, .aftermath-row { grid-template-columns: 50px 1fr 40px 1fr; padding: 6px 8px; }
}
.hard-cap-row { display: grid; grid-template-columns: 130px 1fr; gap: 8px; align-items: center; margin-bottom: 6px; cursor: pointer; padding: 3px 0; border-radius: 4px; }
.hard-cap-row:hover { background: var(--bg-hover); }
.hard-cap-name { font-size: 11px; text-align: right; }
.hard-cap-name strong { font-weight: 500; }
.hard-cap-name small { font-size: 9px; color: var(--text-tertiary); display: block; line-height: 1.1; }
.hard-cap-track { position: relative; height: 22px; }
footer { border-top: 1px solid var(--border); padding: 24px 0; margin-top: 40px; font-size: 11px; color: var(--text-tertiary); text-align: center; }
.org-header { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 10px; }
.org-header h2 { margin: 0; }
.org-pitchers { font-size: 12px; color: var(--text-muted); }
.finding { margin-bottom: 14px; }
.finding-title { font-weight: 600; font-size: 13px; margin-bottom: 3px; }
.finding-body { font-size: 12.5px; color: var(--text-muted); line-height: 1.6; }
.kpi-block { background: var(--bg-subtle); border-radius: 8px; padding: 10px 12px; margin-bottom: 10px; }
.kpi-block-label { font-size: 10px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--text-tertiary); margin-bottom: 4px; }
.kpi-block-value { font-size: 12.5px; line-height: 1.55; }
.best-item { border-left: 2px solid var(--accent); padding: 6px 0 6px 12px; margin-bottom: 12px; }
.org-rankings-grid { display: flex; flex-direction: column; gap: 18px; margin-top: 12px; }
.org-rank-tier h3 { font-size: 13px; font-weight: 600; margin: 0 0 8px 0; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.03em; }
.org-rank-row { display: flex; gap: 12px; padding: 10px 12px; border: 1px solid var(--border); border-radius: 6px; margin-bottom: 8px; cursor: pointer; transition: background 0.12s, border-color 0.12s; }
.org-rank-row:hover { background: var(--bg-hover); border-color: var(--text-tertiary); }
.org-rank-badge { flex: 0 0 auto; width: 48px; height: 48px; border-radius: 6px; color: #fff; font-size: 11px; font-weight: 600; display: flex; align-items: center; justify-content: center; }
.org-rank-main { flex: 1; min-width: 0; }
.org-rank-stats { display: flex; gap: 14px; margin-bottom: 4px; flex-wrap: wrap; }
.org-rank-stats span { display: flex; flex-direction: column; font-size: 13px; }
.org-rank-stats span strong { font-weight: 600; font-size: 14px; }
.org-rank-stats span small { font-size: 9px; text-transform: uppercase; letter-spacing: 0.03em; color: var(--text-tertiary); }
.org-rank-note { font-size: 11.5px; color: var(--text-muted); line-height: 1.5; }
.best-item-title { font-weight: 600; font-size: 13px; margin-bottom: 3px; color: var(--accent-text); }
.best-item-body { font-size: 12.5px; color: var(--text-muted); line-height: 1.6; }
.age-group-card { background: var(--bg-card); border: 1px solid var(--border); border-radius: 10px; padding: 14px 16px; margin-bottom: 12px; }
.age-group-head { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 8px; }
.age-group-label { font-weight: 600; font-size: 14px; }
.age-group-n { font-size: 11px; color: var(--text-tertiary); }
.age-group-stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-bottom: 10px; padding-bottom: 10px; border-bottom: 1px dashed var(--border); }
.age-group-stats .stat-label { font-size: 10px; }
.age-group-stats .stat-value { font-size: 16px; }
.age-group-pitchers { font-size: 11px; color: var(--text-muted); margin-bottom: 8px; }
.age-group-takeaway { font-size: 12.5px; color: var(--text-muted); line-height: 1.6; }
</style>
</head>
<body>
<header class="masthead"><div class="container">
  <h1>MiLB Pitcher Workload Research</h1>
  <div class="subtitle">Growing dataset tracking young pitching prospects across MLB organizations</div>
  <div class="meta-bar">
    <span><strong>Author:</strong> Marcelo Alfonsin</span>
    <span><strong>Pitchers tracked:</strong> __N_PITCHERS__</span>
    <span><strong>Organizations:</strong> __N_ORGS__</span>
    <span><strong>Last build:</strong> __GENERATED__</span>
    <span><strong>Methodology:</strong> See final tab</span>
  </div>
</div></header>
<nav class="main-nav"><div class="container">
  <button data-tab="overview" class="active">Overview</button>
  <button data-tab="pitchers">Pitchers</button>
  <button data-tab="orgs">Organizations</button>
  <button data-tab="best">Best practices</button>
  <button data-tab="ages">Age analysis</button>
  <button data-tab="methodology">Methodology</button>
</div></nav>
<main><div class="container">
<div class="tab-panel active" id="tab-overview"><div id="overview-content"></div></div>
<div class="tab-panel" id="tab-pitchers"><div class="sub-nav" id="pitcher-subnav"></div><div id="pitcher-detail"></div></div>
<div class="tab-panel" id="tab-orgs"><div class="sub-nav" id="org-subnav"></div><div id="org-detail"></div></div>
<div class="tab-panel" id="tab-best"><div id="best-content"></div></div>
<div class="tab-panel" id="tab-ages"><div id="ages-content"></div></div>
<div class="tab-panel" id="tab-methodology"><div id="methodology-content"></div></div>
</div></main>
<footer><div class="container">Analysis compiled __GENERATED__ · Standalone HTML · Chart.js via CDN · Source data: TruMedia pitching KPIs</div></footer>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<script>
__DATA_INJECTION__
</script>
<script>
__APP_JS__
</script>
</body>
</html>
"""

# Stringify the JSON data for JavaScript injection
js_data = "const PAYLOAD = " + json.dumps(js_payload, default=str) + ";"

# Load the runtime JS (separated for readability)
app_js = r"""
const { PITCHER_DATA, META, INJURIES, WEATHER, ORGS, OVERVIEW, BUILD_DATA, ASB_DATA, ORG_COLOR } = PAYLOAD;

// ============================================================================
// Helpers
// ============================================================================

function aggAcwr(starts) {
  const valid = starts.map(s => s.acwr).filter(x => x !== null && !isNaN(x));
  if (valid.length === 0) return { n: 0, mean: 0, max: 0, high: 0, danger: 0, low: 0, sweet: 0, sweetPct: 0 };
  const mean = valid.reduce((a, b) => a + b, 0) / valid.length;
  const max = Math.max(...valid);
  const sweet = valid.filter(x => x >= 0.8 && x <= 1.3).length;
  return { n: valid.length, mean, max, sweet, sweetPct: 100 * sweet / valid.length };
}

function stats(starts) {
  const pcs = starts.map(s => s.p);
  const ips = starts.map(s => s.ipF);
  const s = [...pcs].sort((a, b) => a - b);
  const q = p => s[Math.max(0, Math.min(s.length - 1, Math.floor(p * (s.length - 1))))];
  return {
    gs: starts.length,
    totP: pcs.reduce((a, b) => a + b, 0),
    totIp: ips.reduce((a, b) => a + b, 0),
    medianP: q(0.5),
    p25: q(0.25),
    p75: q(0.75),
    maxP: Math.max(...pcs),
    minP: Math.min(...pcs)
  };
}

function hexToRgb(hex) {
  const h = hex.replace('#', '');
  return `${parseInt(h.slice(0, 2), 16)},${parseInt(h.slice(2, 4), 16)},${parseInt(h.slice(4, 6), 16)}`;
}

// ============================================================================
// Tab switching + routing
// ============================================================================

const TABS = ['overview', 'pitchers', 'orgs', 'best', 'ages', 'methodology'];

function switchTab(tab) {
  document.querySelectorAll('nav.main-nav button').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.toggle('active', p.id === 'tab-' + tab));
  window.scrollTo({ top: 0, behavior: 'smooth' });
  const h = location.hash.split('/');
  if (h[0] !== '#' + tab) location.hash = tab;
}

document.querySelectorAll('nav.main-nav button').forEach(btn => {
  btn.addEventListener('click', () => switchTab(btn.dataset.tab));
});

window.addEventListener('hashchange', handleHash);

function handleHash() {
  const h = location.hash.replace('#', '').split('/');
  const tab = h[0] || 'overview';
  const sub = h[1];
  if (TABS.includes(tab)) {
    switchTab(tab);
    if (tab === 'pitchers' && sub && META[sub]) renderPitcher(sub);
    if (tab === 'orgs' && sub && ORGS[sub]) renderOrg(sub);
  }
}

// ============================================================================
// Overview
// ============================================================================

function renderOverview() {
  const callouts = OVERVIEW.callouts.map(c => `<div class="callout callout-${c.tone}"><strong>${c.headline}</strong><br>${c.body}</div>`).join('');
  const patterns = OVERVIEW.key_patterns.map(p => `<div class="finding"><div class="finding-title">${p.title}</div><div class="finding-body">${p.body}</div></div>`).join('');

  const rows = Object.keys(META).map(name => {
    const m = META[name]; const p = PITCHER_DATA[name];
    if (!p) return null;
    const a = aggAcwr(p.starts); const s = stats(p.starts); const inj = INJURIES[name];
    return { name, m, a, s, inj };
  }).filter(x => x !== null).sort((x, y) => y.a.sweetPct - x.a.sweetPct);

  const scorecard = rows.map(r => {
    const pct = r.a.sweetPct;
    const pctColor = pct >= 85 ? 'var(--good)' : pct >= 70 ? 'var(--info)' : pct >= 55 ? 'var(--warn)' : 'var(--danger)';
    const maxColor = r.a.max > 1.5 ? 'var(--danger)' : r.a.max > 1.3 ? 'var(--warn)' : 'var(--text)';
    const sevClass = r.inj ? (r.inj.severity.includes('TJ') || r.inj.severity === 'in-season' ? 'pill-danger' : r.inj.severity === 'nagging-undiagnosed' ? 'pill-warn' : r.inj.severity === 'unique-role' ? 'pill-info' : 'pill-neutral') : 'pill-good';
    const sevText = r.inj ? r.inj.label : '—';
    return `<div class="scorecard-row" onclick="location.hash='pitchers/${r.name}'">
      <div><strong>${r.name}</strong> <span style="font-size:10px;color:${ORG_COLOR[r.m.org] || '#888'};">${r.m.org}</span> <span style="font-size:10px;color:var(--text-tertiary);">${r.m.yr}</span></div>
      <div>${r.s.gs}</div><div>${r.s.maxP}</div>
      <div style="color:${maxColor};font-weight:500;">${r.a.max.toFixed(2)}</div>
      <div class="inline-bar"><div class="bar-wrap"><div class="bar-fill" style="width:${Math.round(pct)}%;background:${pctColor};"></div></div><span style="min-width:30px;text-align:right;color:${pctColor};font-weight:500;font-size:11px;">${Math.round(pct)}%</span></div>
      <div><span class="pill ${sevClass}">${sevText}</span></div>
    </div>`;
  }).join('');

  // Hard cap ranking
  const capRows = Object.keys(META).map(name => {
    const m = META[name]; const p = PITCHER_DATA[name];
    if (!p) return null;
    return { name, m, s: stats(p.starts) };
  }).filter(x => x !== null).sort((x, y) => y.s.maxP - x.s.maxP);

  const globalMax = 100;
  const capHtml = capRows.map(r => {
    const { p25, p75, medianP, maxP } = r.s;
    const color = ORG_COLOR[r.m.org] || '#888';
    return `<div class="hard-cap-row" onclick="location.hash='pitchers/${r.name}'">
      <div class="hard-cap-name"><strong>${r.name}</strong><small>${r.m.org} · ${r.m.yr} · age ${r.m.age}</small></div>
      <div class="hard-cap-track" title="p25 ${p25}P · median ${medianP}P · p75 ${p75}P · max ${maxP}P">
        <div style="position:absolute;left:0;top:50%;transform:translateY(-50%);height:2px;width:100%;background:var(--border);"></div>
        <div style="position:absolute;left:${(p25/globalMax)*100}%;top:50%;transform:translateY(-50%);height:8px;width:${((p75-p25)/globalMax)*100}%;background:${color};opacity:0.25;border-radius:2px;"></div>
        <div style="position:absolute;left:${(medianP/globalMax)*100}%;top:50%;transform:translate(-50%,-50%);width:3px;height:12px;background:${color};border-radius:1px;"></div>
        <div style="position:absolute;left:${(maxP/globalMax)*100}%;top:50%;transform:translate(-50%,-50%);width:10px;height:10px;border-radius:50%;background:${color};"></div>
        <div style="position:absolute;left:${(maxP/globalMax)*100}%;top:50%;transform:translate(4px,-50%);font-size:10px;color:${color};font-weight:500;white-space:nowrap;">${maxP}P</div>
      </div>
    </div>`;
  }).join('');

  // Injury list
  const injuredOrder = Object.keys(INJURIES).filter(n => META[n] && PITCHER_DATA[n]);
  injuredOrder.sort((a, b) => {
    const sevRank = { 'season-ender-TJ': 0, 'in-season': 1, 'nagging-undiagnosed': 2, 'pre-season': 3, 'late-season': 4, 'workload-tempering': 5, 'org-change': 6, 'minor': 7, 'unique-role': 8 };
    return (sevRank[INJURIES[a].severity] ?? 99) - (sevRank[INJURIES[b].severity] ?? 99);
  });
  const injuriesHtml = injuredOrder.map(name => {
    const inj = INJURIES[name]; const m = META[name];
    const sevClass = inj.severity.includes('TJ') || inj.severity === 'in-season' ? 'callout-danger' : inj.severity === 'nagging-undiagnosed' ? 'callout-warn' : inj.severity === 'unique-role' ? 'callout-info' : 'callout-accent';
    return `<div class="callout ${sevClass}" style="cursor:pointer;" onclick="location.hash='pitchers/${name}'">
      <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:3px;">
        <strong>${name} <span style="font-size:11px;font-weight:400;opacity:0.8;">${m.org} · ${m.yr}</span></strong>
        <span style="font-size:10px;opacity:0.75;">${inj.label}</span>
      </div>
      <div style="font-size:12px;line-height:1.55;">${inj.note}</div>
    </div>`;
  }).join('');

  document.getElementById('overview-content').innerHTML = `
    <h2>Summary</h2>
    <p class="lede">${OVERVIEW.lede}</p>
    <h2>The big picture</h2>
    <div class="two-col">${callouts}</div>
    <h2>Workload management scorecard</h2>
    <p class="lede">Uncoupled rolling 4-start ACWR. Acute = current start pitches, Chronic = average of previous 3 starts. Sweet spot = 0.8-1.3. Spike = &gt;1.5. Click any row to drill into the pitcher.</p>
    <div class="scorecard">
      <div class="scorecard-head"><div>pitcher · org · yr</div><div>GS</div><div>max P</div><div>ACWR max</div><div>% in sweet spot</div><div>status</div></div>
      ${scorecard}
    </div>
    <h2>Hard cap ranking</h2>
    <p class="lede">p25 · median · p75 · max pitch count per pitcher. Look for compressed bars with low max for strict cap pattern.</p>
    <div class="legend-row">
      <span><span class="legend-swatch" style="background:#888;opacity:0.25;"></span>p25-p75 range</span>
      <span><span class="legend-swatch" style="background:#555;width:3px;height:10px;"></span>median</span>
      <span><span class="legend-swatch" style="background:#555;border-radius:50%;"></span>max pitch count</span>
    </div>
    ${capHtml}
    <h2 style="margin-top:24px;">Injury watchlist</h2>
    <p class="lede">Confirmed or suspected injury situations with visible impact on workload data. Based on public reporting cross-referenced with CSV patterns.</p>
    ${injuriesHtml}
    <h2>Key patterns across all pitchers</h2>
    ${patterns}
    ${OVERVIEW.org_rankings ? renderOrgRankings(OVERVIEW.org_rankings) : ''}
  `;
}

function renderOrgRankings(orgRank) {
  const tierHtml = orgRank.tiers.map(tier => {
    const orgs = tier.orgs.map(o => {
      const color = ORG_COLOR[o.org] || '#888';
      return `<div class="org-rank-row" onclick="location.hash='orgs/${o.org}'">
        <div class="org-rank-badge" style="background:${color};">${o.org}</div>
        <div class="org-rank-main">
          <div class="org-rank-stats">
            <span><strong>${o.sweet}%</strong><small>sweet</small></span>
            <span><strong>${o.max_acwr}</strong><small>max ACWR</small></span>
            <span><strong>${o.avg_ip}</strong><small>avg IP</small></span>
            <span><strong>n=${o.n}</strong><small>sample</small></span>
          </div>
          <div class="org-rank-note">${o.note}</div>
        </div>
      </div>`;
    }).join('');
    return `<div class="org-rank-tier">
      <h3>${tier.tier}</h3>
      ${orgs}
    </div>`;
  }).join('');
  return `
    <h2 style="margin-top:32px;">${orgRank.title}</h2>
    <p class="lede">${orgRank.intro}</p>
    <div class="org-rankings-grid">${tierHtml}</div>
  `;
}

// ============================================================================
// Pitcher sub-nav + detail
// ============================================================================

function renderPitcherSubnav() {
  const sortedNames = Object.keys(META).sort((a, b) => {
    const ma = META[a], mb = META[b];
    if (ma.org !== mb.org) return ma.org.localeCompare(mb.org);
    return ma.yr - mb.yr;
  });
  const html = sortedNames.map(name => {
    const m = META[name];
    return `<button data-name="${name}" onclick="location.hash='pitchers/${name}'">${name}<span class="org-tag">${m.org}·${String(m.yr).slice(2)}</span></button>`;
  }).join('');
  document.getElementById('pitcher-subnav').innerHTML = html;
}

function renderPitcher(name) {
  if (!META[name] || !PITCHER_DATA[name]) return;
  document.querySelectorAll('#pitcher-subnav button').forEach(b => b.classList.toggle('active', b.dataset.name === name));
  const m = META[name];
  const p = PITCHER_DATA[name];
  const a = aggAcwr(p.starts);
  const s = stats(p.starts);
  const inj = INJURIES[name];
  const weather = WEATHER[name] || [];
  const build = BUILD_DATA[name];
  const asb = ASB_DATA[name];

  const short = [];
  for (let i = 1; i < p.starts.length; i++) {
    const prev = p.starts[i - 1]; const cur = p.starts[i];
    const curOuts = Math.floor(cur.ip) * 3 + Math.round((cur.ip - Math.floor(cur.ip)) * 10);
    const prevOuts = Math.floor(prev.ip) * 3 + Math.round((prev.ip - Math.floor(prev.ip)) * 10);
    if (curOuts < 12 && (prevOuts - curOuts) >= 6) {
      const nxt = i + 1 < p.starts.length ? p.starts[i + 1] : null;
      short.push({
        sDate: cur.d, sIp: cur.ip, sP: cur.p, pctPrev: Math.round(cur.p / prev.p * 100),
        nDate: nxt ? nxt.d : null, nIp: nxt ? nxt.ip : null, nP: nxt ? nxt.p : null, nRest: nxt ? nxt.rest : null,
        nextPctPrev: nxt ? Math.round(nxt.p / prev.p * 100) : null
      });
    }
  }

  const monthly = {};
  for (const st of p.starts) {
    const mo = st.ymd.slice(0, 7);
    if (!monthly[mo]) monthly[mo] = { count: 0, p: 0, ip: 0 };
    monthly[mo].count++; monthly[mo].p += st.p; monthly[mo].ip += st.ipF;
  }

  const injCard = inj ? `<div class="callout ${inj.severity.includes('TJ') || inj.severity === 'in-season' ? 'callout-danger' : inj.severity === 'nagging-undiagnosed' ? 'callout-warn' : inj.severity === 'unique-role' ? 'callout-info' : 'callout-accent'}">
    <div style="font-weight:600;margin-bottom:3px;">${inj.label}</div>${inj.note}</div>` : '';
  const weatherCard = weather.length ? `<div class="callout callout-info"><div style="font-weight:600;margin-bottom:3px;">Gap attribution</div>${weather.map(w => `<div style="margin-bottom:2px;"><strong>${w.date}:</strong> ${w.detail}</div>`).join('')}</div>` : '';
  const asbCard = asb ? `<div class="callout callout-info"><div style="font-weight:600;margin-bottom:3px;">All-Star break handling</div>Pre-break: ${asb.pre} · Gap: <strong>${asb.gap}d</strong> (+${asb.extra}d extra) · Post-break: ${asb.post}</div>` : '';

  document.getElementById('pitcher-detail').innerHTML = `
    <h2 style="margin-top:0;display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;">
      ${name}
      <span style="font-size:13px;font-weight:400;color:var(--text-muted);">${m.team} · ${m.level}</span>
      <span class="pill" style="background:${ORG_COLOR[m.org]}22;color:${ORG_COLOR[m.org]};">${m.org} ${m.yr}</span>
    </h2>
    <div class="three-col">
      <div class="kpi-block"><div class="kpi-block-label">age · draft</div><div class="kpi-block-value">${m.age} · ${m.draft}</div></div>
      <div class="kpi-block"><div class="kpi-block-label">buildup · style</div><div class="kpi-block-value">${build ? `+${build.slope}P/start · ${build.group}` : '—'}</div></div>
      <div class="kpi-block"><div class="kpi-block-label">note</div><div class="kpi-block-value">${m.note}</div></div>
    </div>
    <div class="stats-grid">
      <div class="stat"><div class="stat-label">Starts</div><div class="stat-value">${s.gs}</div></div>
      <div class="stat"><div class="stat-label">Total P</div><div class="stat-value">${s.totP}</div></div>
      <div class="stat"><div class="stat-label">Total IP</div><div class="stat-value">${s.totIp.toFixed(1)}</div></div>
      <div class="stat"><div class="stat-label">Median P</div><div class="stat-value">${s.medianP}</div></div>
      <div class="stat"><div class="stat-label">Max P</div><div class="stat-value">${s.maxP}</div></div>
      <div class="stat" style="background:${a.max > 1.5 ? 'var(--danger-soft)' : a.max > 1.3 ? 'var(--warn-soft)' : 'var(--bg-card)'};"><div class="stat-label">ACWR max · sweet %</div><div class="stat-value" style="color:${a.max > 1.5 ? 'var(--danger)' : a.max > 1.3 ? 'var(--warn)' : 'var(--text)'};">${a.max.toFixed(2)}<span class="stat-sub"> · ${Math.round(a.sweetPct)}%</span></div></div>
    </div>
    ${injCard}${weatherCard}${asbCard}
    <h3>Workload trajectory — pitches, IP, ACWR</h3>
    <div class="legend-row">
      <span><span class="legend-swatch" style="background:${ORG_COLOR[m.org]};"></span>Pitches (left axis)</span>
      <span><span class="legend-swatch" style="background:#0f766e;"></span>IP (inner right)</span>
      <span><span class="legend-swatch" style="background:#c2410c;"></span>ACWR (outer right)</span>
    </div>
    <div class="chart-wrap tall"><canvas id="chart-traj-${name}" role="img" aria-label="${name} workload trajectory"></canvas></div>
    <h3>Monthly volume breakdown</h3>
    <div class="table-wrap"><table>
      <thead><tr><th>Month</th><th>GS</th><th>Total P</th><th>Total IP</th><th>Avg P/start</th><th>Avg IP/start</th></tr></thead>
      <tbody>${Object.entries(monthly).map(([mo, v]) => `<tr><td>${mo}</td><td>${v.count}</td><td>${v.p}</td><td>${v.ip.toFixed(1)}</td><td>${Math.round(v.p / v.count)}</td><td>${(v.ip / v.count).toFixed(1)}</td></tr>`).join('')}</tbody>
    </table></div>
    <h3>Full calendar view</h3>
    <div class="calendar-grid" id="calendar-${name}"></div>
    <h3>Short-start aftermath (&lt; 4 IP &amp; ≥ 2 IP shorter than previous)</h3>
    ${short.length ? `<div class="aftermath-grid"><div class="aftermath-head"><div>date</div><div>short start (% of prev)</div><div>next rest</div><div>next start (% of pre-short P)</div></div>
    ${short.map(r => `<div class="aftermath-row"><div style="color:var(--text-muted);">${r.sDate}</div><div>${r.sIp} IP · ${r.sP}P <span class="pct">(${r.pctPrev}%)</span></div><div style="font-size:10px;color:${r.nRest === null ? 'var(--text-tertiary)' : r.nRest >= 10 ? 'var(--danger)' : r.nRest <= 5 ? 'var(--info)' : 'var(--text-muted)'};">${r.nRest === null ? '—' : r.nRest + 'd'}</div><div>${r.nDate ? `${r.nIp} IP · ${r.nP}P <span class="pct">(${r.nextPctPrev}%)</span>` : '<span style="color:var(--text-tertiary);">end of season</span>'}</div></div>`).join('')}</div>` : '<div style="font-size:12px;color:var(--text-muted);font-style:italic;margin-bottom:14px;">No qualifying short starts.</div>'}
    <h3>Build-up profile (first 10 starts)</h3>
    ${build ? `<div class="card" style="padding:10px 12px;"><div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:2px;"><div style="font-size:13px;font-weight:600;">${m.note}</div><div style="font-size:11px;color:${build.group === 'fast' ? 'var(--good)' : build.group === 'steady' ? 'var(--info)' : 'var(--text-muted)'};font-weight:500;">+${build.slope}P/start · ${build.group}</div></div><div style="font-size:10px;color:var(--text-tertiary);margin-bottom:6px;">opener ${build.pcs[0]}P → peak ${build.peakP}P at start #${build.peak}</div><div class="chart-wrap small"><canvas id="chart-build-${name}"></canvas></div></div>` : ''}
  `;

  setTimeout(() => { drawTrajectory(name); drawCalendar(name); if (build) drawBuildChart(name); }, 30);
}

function drawTrajectory(name) {
  const p = PITCHER_DATA[name]; const m = META[name];
  const ctx = document.getElementById('chart-traj-' + name);
  if (!ctx || !window.Chart) return;
  const color = ORG_COLOR[m.org] || '#378ADD';
  new Chart(ctx, {
    data: {
      labels: p.starts.map(s => s.d),
      datasets: [
        { type: 'line', label: 'Pitches', data: p.starts.map(s => s.p), borderColor: color, backgroundColor: color, borderWidth: 2, pointRadius: 3, tension: 0.2, yAxisID: 'y' },
        { type: 'line', label: 'IP', data: p.starts.map(s => s.ipF), borderColor: '#0f766e', backgroundColor: 'rgba(15,118,110,0.1)', borderWidth: 1, borderDash: [3, 3], pointRadius: 1.5, tension: 0.2, yAxisID: 'y1' },
        { type: 'line', label: 'ACWR', data: p.starts.map(s => s.acwr), borderColor: '#c2410c', backgroundColor: '#c2410c', borderWidth: 1.2, pointRadius: 2.4, pointStyle: 'triangle', tension: 0.25, yAxisID: 'y2' }
      ]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: (c) => { if (c.dataset.label === 'IP') return `IP: ${c.raw}`; if (c.dataset.label === 'ACWR') return `ACWR: ${c.raw === null || isNaN(c.raw) ? '—' : c.raw.toFixed(2)}`; return `${c.dataset.label}: ${c.raw}`; } } }
      },
      scales: {
        x: { ticks: { autoSkip: true, maxRotation: 0, font: { size: 9 }, maxTicksLimit: 15 }, grid: { display: false } },
        y: { position: 'left', min: 0, max: 110, title: { display: true, text: 'Pitches', font: { size: 10 } }, ticks: { font: { size: 9 }, stepSize: 20 }, grid: { color: 'rgba(128,128,128,0.08)' } },
        y1: { position: 'right', min: 0, max: 9, title: { display: true, text: 'IP', font: { size: 10 } }, ticks: { font: { size: 9 }, stepSize: 2 }, grid: { display: false } },
        y2: { position: 'right', min: 0, max: 2.5, title: { display: true, text: 'ACWR', font: { size: 10 } }, ticks: { font: { size: 9 }, stepSize: 0.5, callback: v => v.toFixed(1) }, grid: { display: false }, offset: true }
      }
    }
  });
}

function drawBuildChart(name) {
  const build = BUILD_DATA[name]; const m = META[name];
  const ctx = document.getElementById('chart-build-' + name);
  if (!ctx || !window.Chart) return;
  const color = ORG_COLOR[m.org] || '#888';
  new Chart(ctx, {
    type: 'line',
    data: { labels: build.pcs.map((_, i) => i + 1), datasets: [{ data: build.pcs, borderColor: color, backgroundColor: color + '22', borderWidth: 1.5, pointRadius: 3, pointBackgroundColor: color, tension: 0.25, fill: true }] },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false }, tooltip: { callbacks: { title: (t) => `Start #${t[0].label}`, label: (c) => `${c.raw}P` } } }, scales: { x: { ticks: { font: { size: 9 } }, grid: { display: false } }, y: { min: 20, max: 110, ticks: { font: { size: 9 }, stepSize: 20 }, grid: { color: 'rgba(128,128,128,0.06)' } } } }
  });
}

function drawCalendar(name) {
  const p = PITCHER_DATA[name];
  const year = p.starts[0].ymd.slice(0, 4);
  const monthList = [{ num: '04', name: 'April' }, { num: '05', name: 'May' }, { num: '06', name: 'June' }, { num: '07', name: 'July' }, { num: '08', name: 'August' }, { num: '09', name: 'Sept' }];
  const startMap = {};
  for (const st of p.starts) startMap[st.ymd] = st;
  const container = document.getElementById('calendar-' + name);
  container.innerHTML = monthList.map(mo => {
    const year4 = parseInt(year);
    const monthIdx = parseInt(mo.num) - 1;
    const daysInMonth = new Date(year4, monthIdx + 1, 0).getDate();
    const firstDow = new Date(year4, monthIdx, 1).getDay();
    const cells = [];
    for (let i = 0; i < firstDow; i++) cells.push(`<div class="cal-cell empty"></div>`);
    for (let d = 1; d <= daysInMonth; d++) {
      const ymd = `${year}-${mo.num}-${String(d).padStart(2, '0')}`;
      const st = startMap[ymd];
      if (st) {
        const pct = Math.min(1, st.p / 100);
        const color = ORG_COLOR[META[name].org] || '#888';
        const bg = `rgba(${hexToRgb(color)}, ${0.2 + pct * 0.55})`;
        const isShort = st.ipF < 4;
        cells.push(`<div class="cal-cell start ${isShort ? 'short' : ''}" style="background:${bg};color:${color};" title="${ymd} · ${st.ip} IP / ${st.p}P · ${st.fr} vs ${st.opp}"><div class="daynum">${d}</div><div class="ipval">${st.ip}</div></div>`);
      } else {
        cells.push(`<div class="cal-cell empty"><div class="daynum">${d}</div></div>`);
      }
    }
    return `<div class="cal-month"><div class="cal-month-name">${mo.name}</div><div class="cal-dow"><span>S</span><span>M</span><span>T</span><span>W</span><span>T</span><span>F</span><span>S</span></div><div class="cal-days">${cells.join('')}</div></div>`;
  }).join('');
}

// ============================================================================
// Orgs
// ============================================================================

function renderOrgSubnav() {
  const orgKeys = Object.keys(ORGS);
  const html = orgKeys.map(o => {
    const count = ORGS[o].pitchers ? ORGS[o].pitchers.length : 0;
    return `<button data-org="${o}" onclick="location.hash='orgs/${o}'">${o}<span class="org-tag">${count}</span></button>`;
  }).join('');
  document.getElementById('org-subnav').innerHTML = html;
}

function renderOrg(key) {
  document.querySelectorAll('#org-subnav button').forEach(b => b.classList.toggle('active', b.dataset.org === key));
  const f = ORGS[key];
  const color = ORG_COLOR[key] || '#888';
  const orgPitchers = f.pitchers.filter(n => META[n] && PITCHER_DATA[n]);
  const agg = orgPitchers.map(n => { const p = PITCHER_DATA[n]; return { name: n, meta: META[n], a: aggAcwr(p.starts), s: stats(p.starts) }; });
  const meanSweet = agg.length ? agg.reduce((x, r) => x + r.a.sweetPct, 0) / agg.length : 0;
  const meanMaxP = agg.length ? agg.reduce((x, r) => x + r.s.maxP, 0) / agg.length : 0;
  const meanGS = agg.length ? agg.reduce((x, r) => x + r.s.gs, 0) / agg.length : 0;
  const meanIP = agg.length ? agg.reduce((x, r) => x + r.s.totIp, 0) / agg.length : 0;

  const sections = [
    { key: 'rhythm', title: 'Rotation rhythm & rest' },
    { key: 'cap', title: 'Pitch count caps' },
    { key: 'buildup', title: 'Build-up approach' },
    { key: 'short', title: 'Short-start handling' },
    { key: 'injury', title: 'Injury management' },
    { key: 'risk', title: 'Risk notes' },
    { key: 'cijntje_special', title: 'Cijntje — piggyback role context' },
    { key: 'multi_level', title: 'Multi-level progression' },
    { key: 'exemplar', title: 'Exemplar pitcher' },
    { key: 'pattern', title: 'Observed pattern' },
    { key: 'promo', title: 'Level promotion handling' }
  ];
  const findingsHtml = sections.filter(s => f[s.key]).map(s => `<div class="finding"><div class="finding-title">${s.title}</div><div class="finding-body">${f[s.key]}</div></div>`).join('');

  document.getElementById('org-detail').innerHTML = `
    <div class="org-header"><h2 style="color:${color};">${key}</h2><div class="org-pitchers">${orgPitchers.length} pitcher${orgPitchers.length > 1 ? 's' : ''}: ${orgPitchers.map(p => `<a href="#pitchers/${p}" style="color:${color};text-decoration:none;border-bottom:1px dotted;">${p}</a>`).join(', ')}</div></div>
    <div class="stats-grid">
      <div class="stat"><div class="stat-label">Pitchers studied</div><div class="stat-value">${orgPitchers.length}</div></div>
      <div class="stat"><div class="stat-label">Avg starts/pitcher</div><div class="stat-value">${meanGS.toFixed(0)}</div></div>
      <div class="stat"><div class="stat-label">Avg IP/pitcher</div><div class="stat-value">${meanIP.toFixed(0)}</div></div>
      <div class="stat"><div class="stat-label">Avg max P</div><div class="stat-value">${meanMaxP.toFixed(0)}</div></div>
      <div class="stat"><div class="stat-label">Avg ACWR sweet</div><div class="stat-value" style="color:${meanSweet >= 85 ? 'var(--good)' : meanSweet >= 70 ? 'var(--info)' : 'var(--warn)'};">${meanSweet.toFixed(0)}%</div></div>
    </div>
    <h3>Pitcher summaries</h3>
    <div class="table-wrap"><table>
      <thead><tr><th>Pitcher</th><th>Year</th><th>Age</th><th>Level</th><th>GS</th><th>IP</th><th>Max P</th><th>ACWR max</th><th>% sweet</th></tr></thead>
      <tbody>${agg.map(r => `<tr onclick="location.hash='pitchers/${r.name}'" style="cursor:pointer;"><td><strong>${r.name}</strong></td><td>${r.meta.yr}</td><td>${r.meta.age}</td><td>${r.meta.level}</td><td>${r.s.gs}</td><td>${r.s.totIp.toFixed(1)}</td><td>${r.s.maxP}</td><td style="color:${r.a.max > 1.5 ? 'var(--danger)' : r.a.max > 1.3 ? 'var(--warn)' : 'var(--text)'};font-weight:500;">${r.a.max.toFixed(2)}</td><td>${Math.round(r.a.sweetPct)}%</td></tr>`).join('')}</tbody>
    </table></div>
    <h3>Findings</h3>
    ${findingsHtml}
    ${f.strengths ? `<h3>Strengths</h3><div class="callout callout-good">${f.strengths}</div>` : ''}
    ${f.concerns ? `<h3>Concerns</h3><div class="callout callout-warn">${f.concerns}</div>` : ''}
  `;
}

// ============================================================================
// Best practices tab
// ============================================================================

function renderBest() {
  const bp = OVERVIEW.best_practices;
  const items = bp.items.map(i => `<div class="best-item"><div class="best-item-title">${i.title}</div><div class="best-item-body">${i.body}</div></div>`).join('');
  document.getElementById('best-content').innerHTML = `
    <h2>${bp.title}</h2>
    <p class="lede">${bp.intro}</p>
    ${items}
    <h3>The exemplars</h3>
    <div class="two-col">
      <div class="callout callout-good"><strong>Parker Messick (CLE 2024, 23yo)</strong><br>138 IP · 28 GS · max 97P · 80% ACWR sweet. FSU college lefty, 2022 2nd rd. Lake County → Akron (AA). Eastern League All-Star. MLB debut April 2026 with a near-no-hitter in 11th start.</div>
      <div class="callout callout-good"><strong>Drue Hackenberg (ATL 2024, 22yo)</strong><br>129 IP · 25 GS · max 97P · 91% ACWR sweet. Virginia Tech college righty, 2023 2nd rd. Rome → Mississippi → Gwinnett (3 levels). Clean health across aggressive promotions.</div>
    </div>
    <div class="two-col">
      <div class="callout callout-good"><strong>Woodrow Ford (SEA 2025, 20yo)</strong><br>125 IP · 23 GS · max 89P · 100% ACWR sweet. 2022 2nd rd. Modesto (Low-A). Held 7-day rotation for 20 of 22 rest gaps. Only Low-A arm in the exemplar group — shows it's possible to log heavy innings at the lowest full-season level.</div>
      <div class="callout callout-good"><strong>Jonathan Santucci (NYM 2025, 22yo)</strong><br>122 IP · 26 GS · max 86P · 96% ACWR sweet. 2024 2nd rd. Brooklyn → Binghamton. Clean progression High-A to AA, opener to peak with no injury disruptions.</div>
    </div>
  `;
}

// ============================================================================
// Ages tab
// ============================================================================

function renderAges() {
  const a = OVERVIEW.age_analysis;
  const groupsHtml = a.groups.map(g => `
    <div class="age-group-card">
      <div class="age-group-head"><div class="age-group-label">${g.label}</div><div class="age-group-n">n = ${g.n}</div></div>
      <div class="age-group-stats">
        <div><div class="stat-label">avg IP</div><div class="stat-value">${g.avg_ip}</div></div>
        <div><div class="stat-label">avg max P</div><div class="stat-value">${g.avg_max_p}</div></div>
        <div><div class="stat-label">avg sweet %</div><div class="stat-value">${g.avg_sweet_pct}%</div></div>
      </div>
      <div class="age-group-pitchers">${g.pitchers.map(p => `<a href="#pitchers/${p}" style="color:var(--text-muted);text-decoration:none;border-bottom:1px dotted;">${p}</a>`).join(' · ')}</div>
      <div class="age-group-takeaway">${g.takeaway}</div>
    </div>
  `).join('');
  const conclusionsHtml = a.conclusions.map(c => `<div class="finding"><div class="finding-body">${c}</div></div>`).join('');
  document.getElementById('ages-content').innerHTML = `
    <h2>${a.title}</h2>
    <p class="lede">${a.intro}</p>
    ${groupsHtml}
    <h3>Conclusions</h3>
    ${conclusionsHtml}
  `;
}

// ============================================================================
// Methodology tab
// ============================================================================

function renderMethodology() {
  document.getElementById('methodology-content').innerHTML = `
    <h2>Methodology</h2>
    <h3>Data source</h3>
    <p>TruMedia pitching KPIs export, full-season game logs. Game-by-game records include date, opponent, IP, pitches, result, strike rate, velocity, breaking ball metrics, and batted ball outcomes. This analysis focuses on IP, pitches, rest days, and derived workload metrics.</p>
    <h3>ACWR calculation</h3>
    <p>Uncoupled rolling 4-start ACWR, adapted from Gabbett (2016) for starting pitchers on a weekly rotation:</p>
    <div class="kpi-block"><div class="kpi-block-label">formula</div><div class="kpi-block-value">ACWR<sub>i</sub> = P<sub>i</sub> / mean(P<sub>i-3</sub>, P<sub>i-2</sub>, P<sub>i-1</sub>)</div></div>
    <p>Valid for starts i ≥ 4. Interpretation:</p>
    <div class="table-wrap"><table>
      <thead><tr><th>Range</th><th>Interpretation</th></tr></thead>
      <tbody>
        <tr><td>&gt; 1.50</td><td>Spike / elevated injury risk zone</td></tr>
        <tr><td>1.30 - 1.50</td><td>High load — monitor</td></tr>
        <tr><td>0.80 - 1.30</td><td>Sweet spot — optimal load management</td></tr>
        <tr><td>0.50 - 0.80</td><td>Undertraining / detraining</td></tr>
        <tr><td>&lt; 0.50</td><td>Rapid deload (typical post-injury or first start back)</td></tr>
      </tbody>
    </table></div>
    <p>Uncoupled (exclude current start from chronic baseline) over coupled because the prior-3-start average better reflects what the pitcher has been accustomed to.</p>
    <h3>Short-start definition</h3>
    <p>A start qualifies as "short" when BOTH: (1) less than 4.0 IP AND (2) at least 2 full innings shorter than the previous start. This excludes consistent short-usage patterns and captures only the "chased from a game he was expected to go deep in" scenario.</p>
    <h3>"% of previous" framing</h3>
    <p>For short-start aftermath, the NEXT start's pitch count is compared to the PRE-SHORT start (the one before the short one). This answers: did the org plan a shorter next outing, or restart normal workload?</p>
    <h3>Age group definitions</h3>
    <p>18-19yo, 20-21yo, 22+yo. Age is as of the season covered by the CSV (not current age). For pitchers who turned 20 during the season, they're in the 18-19 group if they were 19 at season start.</p>
    <h3>Weather caveat</h3>
    <p>CSV data does not include weather fields. Unusual gaps (8+ days without known injury or All-Star break) may reflect weather-related rainouts. Short rest windows (&lt; 5 days) can indicate compressed rotations after rainouts. Attribution of suspicious gaps is tracked in data/weather_flags.json based on reporting and game-log context.</p>
    <h3>Repo structure</h3>
    <div class="kpi-block"><div class="kpi-block-value" style="font-family:monospace;white-space:pre;font-size:11px;">pitcher-workload-research/
├── data/
│   ├── csvs/              TruMedia exports — drop new ones here
│   ├── metadata.json      Pitcher meta (org, yr, age, draft, etc)
│   ├── injury_flags.json  Per-pitcher injury context
│   ├── weather_flags.json Per-pitcher gap attribution
│   ├── org_findings.json  Per-org qualitative writeups
│   └── overview_findings.json  Top-level patterns and callouts
├── scripts/
│   └── build.py           Regenerates docs/index.html
├── docs/
│   └── index.html         The deliverable (GitHub Pages)
└── README.md</div></div>
    <p>To add a pitcher: drop CSV in data/csvs/, add entry to metadata.json, optionally add injury/weather notes, run scripts/build.py, commit &amp; push. If the new data shifts conclusions, also update the relevant JSON prose.</p>
  `;
}

// ============================================================================
// Initialize
// ============================================================================

renderOverview();
renderPitcherSubnav();
renderOrgSubnav();
renderBest();
renderAges();
renderMethodology();

if (location.hash) handleHash();
else switchTab('overview');

document.querySelector('nav.main-nav button[data-tab="pitchers"]').addEventListener('click', () => {
  if (!location.hash.includes('/')) location.hash = 'pitchers/Messick';
});
document.querySelector('nav.main-nav button[data-tab="orgs"]').addEventListener('click', () => {
  if (!location.hash.includes('/')) location.hash = 'orgs/ATL';
});
"""

# Substitute placeholders
html = html_template.replace('__N_PITCHERS__', str(len(pitcher_data)))
html = html.replace('__N_ORGS__', str(len(orgs)))
html = html.replace('__GENERATED__', js_payload['GENERATED'])
html = html.replace('__DATA_INJECTION__', js_data)
html = html.replace('__APP_JS__', app_js)

OUT.parent.mkdir(parents=True, exist_ok=True)
with open(OUT, 'w') as f:
    f.write(html)

print(f"\nBuilt {OUT}", file=sys.stderr)
print(f"  {len(pitcher_data)} pitchers", file=sys.stderr)
print(f"  {len(orgs)} organizations", file=sys.stderr)
print(f"  {OUT.stat().st_size:,} bytes", file=sys.stderr)
