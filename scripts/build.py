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
    with open(DATA / name, encoding='utf-8') as f:
        return json.load(f)

meta = load_json("metadata.json")
injuries = load_json("injury_flags.json")
weather = load_json("weather_flags.json")
orgs = load_json("org_findings.json")
overview = load_json("overview_findings.json")
league_context_v2 = load_json("league_context_v2.json")

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

def _safe_float(v):
    """Parse a CSV cell that may be empty / '—' / valid float."""
    if v is None:
        return None
    s = str(v).strip()
    if not s or s in ('—', '-', 'NA', 'N/A'):
        return None
    # Strip trailing % if present
    if s.endswith('%'):
        s = s[:-1]
    try:
        return float(s)
    except ValueError:
        return None

def _safe_int(v):
    if v is None:
        return 0
    s = str(v).strip()
    if not s or s in ('—', '-', 'NA', 'N/A'):
        return 0
    try:
        return int(float(s))
    except ValueError:
        return 0

def process_pitcher_csv(csv_path):
    """Read one TruMedia CSV and return structured starts list."""
    rows = []
    with open(csv_path, encoding='utf-8') as f:
        for r in csv.DictReader(f):
            gd = r['gameDay']
            date = dt.datetime.strptime(gd, '%m/%d/%y')
            rows.append({
                'date': date,
                'gameDay': gd,
                'ip': float(r['IP']),
                'p': int(r['P']),
                'bf': _safe_int(r.get('BF')),
                'result': r.get('result', ''),
                'opponent': r.get('opponent', ''),
                'team': r.get('teamWithLevel', ''),
                'vel': _safe_float(r.get('Vel4S')),
                'strike_pct': _safe_float(r.get('Strike%')),
            })
    rows.sort(key=lambda x: x['date'])
    pitches = [r['p'] for r in rows]
    acwrs = start_based_acwr(pitches)

    starts = []
    prev_date = None
    for i, r in enumerate(rows):
        rest = (r['date'] - prev_date).days if prev_date else 0
        ip_dec = ip_to_decimal(r['ip'])
        bf = r['bf']
        ppi = round(r['p'] / ip_dec, 2) if ip_dec > 0 else None
        ppb = round(r['p'] / bf, 2) if bf > 0 else None
        starts.append({
            'd': r['date'].strftime('%m/%d'),
            'ymd': r['date'].strftime('%Y-%m-%d'),
            'ip': r['ip'],
            'ipF': ip_dec,
            'p': r['p'],
            'bf': bf,
            'pPerIp': ppi,
            'pPerBf': ppb,
            'r': r['result'][:1] if r['result'] else '',
            'fr': r['result'],
            'opp': r['opponent'],
            'team': r['team'],
            'rest': rest,
            'acwr': acwrs[i],
            'vel': r['vel'],
            'strikePct': r['strike_pct'],
        })
        prev_date = r['date']
    return starts

pitcher_data = {}
insufficient_history = []  # pitchers with <4 starts (no ACWR-eligible window)
for name, m in meta.items():
    csv_path = CSV_DIR / m['csv']
    if not csv_path.exists():
        print(f"WARNING: {csv_path} not found, skipping {name}", file=sys.stderr)
        continue
    pitcher_data[name] = {'starts': process_pitcher_csv(csv_path)}
    n_starts = len(pitcher_data[name]['starts'])
    print(f"  processed {name}: {n_starts} starts", file=sys.stderr)
    if n_starts < 4:
        insufficient_history.append(name)
        print(f"  WARNING: {name} has only {n_starts} starts — no ACWR-eligible window; excluded from org/age sweet% aggregates", file=sys.stderr)


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
# Short-start detection (lifted from runtime JS for cross-org aggregation)
# -----------------------------------------------------------------------------

SHORT_PITCH_RATIO = 0.80  # cur P must be <= this * prev P to qualify as TRUE short-workload

def compute_short_starts(starts):
    """Detect low-IP starts and split into TWO buckets:

    True short-workload ('short'): cur_ip < 4 AND cur_p <= 0.80 * prev_p AND
        (prev_ip - cur_ip) >= 2.0. Pitch-count guard ensures the workload
        actually dropped — not just IP.

    Inefficient low-IP ('inefficient'): cur_ip < 4 AND cur_p > 0.80 * prev_p.
        Same low-IP outing, but the pitch count was held (or rose). High-stress
        outing, NOT a short-workload event. Surfaced separately.

    Returns dict {short: [...], inefficient: [...]}.
    """
    short = []
    inefficient = []
    for i in range(1, len(starts)):
        prev = starts[i - 1]
        cur = starts[i]
        cur_outs = ip_to_outs(cur['ip'])
        prev_outs = ip_to_outs(prev['ip'])
        if cur_outs >= 12:
            continue
        if (prev_outs - cur_outs) < 6:
            # Need at least 2 IP shorter than previous to be relevant either way.
            continue
        nxt = starts[i + 1] if i + 1 < len(starts) else None
        ratio = (cur['p'] / prev['p']) if prev['p'] else None
        ev = {
            'sDate': cur['d'],
            'sIp': cur['ip'],
            'sP': cur['p'],
            'sPperIp': cur.get('pPerIp'),
            'prevP': prev['p'],
            'prevIp': prev['ip'],
            'pctPrev': round(ratio * 100) if ratio is not None else None,
            'nDate': nxt['d'] if nxt else None,
            'nIp': nxt['ip'] if nxt else None,
            'nP': nxt['p'] if nxt else None,
            'nRest': nxt['rest'] if nxt else None,
            'nextPctPrev': round(nxt['p'] / prev['p'] * 100) if (nxt and prev['p']) else None
        }
        if ratio is not None and ratio <= SHORT_PITCH_RATIO:
            short.append(ev)
        else:
            inefficient.append(ev)
    return {'short': short, 'inefficient': inefficient}

_short_raw = {name: compute_short_starts(d['starts']) for name, d in pitcher_data.items()}
short_start_data = {name: v['short'] for name, v in _short_raw.items()}
inefficient_start_data = {name: v['inefficient'] for name, v in _short_raw.items()}


def compute_short_start_aggregates(short_start_data, meta, injuries):
    """Roll up short-start events by org for cross-org comparison.

    Per-event: pitcher, org, dates, IP/P, % reframing, next-rest, injury flag.
    Per-org: event count, pitchers involved, median/mean reframe%, skipped-turn
    count (rough heuristic: next rest >= 10 days).
    """
    events = []
    org_summary = {}
    for name, evs in short_start_data.items():
        if not evs:
            continue
        m = meta[name]
        org = m['org']
        if org not in org_summary:
            org_summary[org] = {
                'org': org,
                'nEvents': 0,
                'pitchersWithShort': set(),
                'reframes': [],
                'skippedTurns': 0,
                'endOfSeason': 0,
            }
        for ev in evs:
            rest = ev['nRest']
            # Rough heuristic for skipped turn — documented caveat: for most
            # orgs normal rest is 5-8 days, so >=10 suggests a skipped rotation
            # turn. Hand-verified: Harrison (TB) is the only confirmed case in
            # the dataset.
            is_skipped = rest is not None and rest >= 10
            is_eos = ev['nDate'] is None
            inj = injuries.get(name)
            events.append({
                'pitcher': name,
                'org': org,
                'yr': m['yr'],
                'age': m['age'],
                'ageGroup': m.get('ageGroup', ''),
                'sDate': ev['sDate'],
                'sIp': ev['sIp'],
                'sP': ev['sP'],
                'prevP': ev['prevP'],
                'prevIp': ev['prevIp'],
                'pctPrev': ev['pctPrev'],
                'nDate': ev['nDate'],
                'nIp': ev['nIp'],
                'nP': ev['nP'],
                'nRest': rest,
                'nextPctPrev': ev['nextPctPrev'],
                'skipped': is_skipped,
                'endOfSeason': is_eos,
                'injuryLabel': inj['label'] if inj else None,
                'injurySeverity': inj['severity'] if inj else None,
            })
            org_summary[org]['nEvents'] += 1
            org_summary[org]['pitchersWithShort'].add(name)
            if ev['nextPctPrev'] is not None:
                org_summary[org]['reframes'].append(ev['nextPctPrev'])
            if is_skipped:
                org_summary[org]['skippedTurns'] += 1
            if is_eos:
                org_summary[org]['endOfSeason'] += 1

    orgs_out = []
    for org, s in org_summary.items():
        r = s['reframes']
        median_reframe = None
        if r:
            sr = sorted(r)
            n = len(sr)
            median_reframe = sr[n // 2] if n % 2 == 1 else round((sr[n // 2 - 1] + sr[n // 2]) / 2)
        mean_reframe = round(sum(r) / len(r)) if r else None
        orgs_out.append({
            'org': org,
            'nEvents': s['nEvents'],
            'nPitchers': len(s['pitchersWithShort']),
            'orgPitcherCount': sum(1 for n, mm in meta.items() if mm['org'] == org and n in pitcher_data),
            'medianReframe': median_reframe,
            'meanReframe': mean_reframe,
            'skippedTurns': s['skippedTurns'],
            'endOfSeason': s['endOfSeason'],
        })
    # Sort by median reframe ascending — lower = more tempered re-entry
    orgs_out.sort(key=lambda x: (x['medianReframe'] is None, x['medianReframe'] if x['medianReframe'] is not None else 999))
    events.sort(key=lambda e: (e['org'], e['pitcher'], e['sDate']))

    # Global summary across all events
    all_reframes = [e['nextPctPrev'] for e in events if e['nextPctPrev'] is not None]
    all_reframes_sorted = sorted(all_reframes)
    global_median = None
    if all_reframes_sorted:
        n = len(all_reframes_sorted)
        global_median = all_reframes_sorted[n // 2] if n % 2 == 1 else round((all_reframes_sorted[n // 2 - 1] + all_reframes_sorted[n // 2]) / 2)
    return {
        'orgs': orgs_out,
        'events': events,
        'totalEvents': len(events),
        'totalPitchersWithShort': sum(1 for evs in short_start_data.values() if evs),
        'globalMedianReframe': global_median,
        'globalMeanReframe': round(sum(all_reframes) / len(all_reframes)) if all_reframes else None,
        'totalSkipped': sum(1 for e in events if e['skipped']),
    }

short_start_aggregates = compute_short_start_aggregates(short_start_data, meta, injuries)
print(f"  short-start events (true low-workload): {short_start_aggregates['totalEvents']} across {short_start_aggregates['totalPitchersWithShort']} pitchers", file=sys.stderr)


def compute_inefficient_aggregates(inefficient_data, meta, injuries):
    """Roll up inefficient-low-IP events: <4 IP outings where pitch count was
    held (or rose) — same workload jammed into fewer outs. NOT a short-workload
    event; surfaced separately for stress visibility.
    """
    events = []
    org_summary = {}
    for name, evs in inefficient_data.items():
        if not evs:
            continue
        m = meta[name]
        org = m['org']
        if org not in org_summary:
            org_summary[org] = {
                'org': org,
                'nEvents': 0,
                'pitchersInvolved': set(),
                'pPerIps': [],
            }
        for ev in evs:
            inj = injuries.get(name)
            p_per_ip = round(ev['sP'] / ev['sIp'], 1) if ev['sIp'] else None
            events.append({
                'pitcher': name,
                'org': org,
                'yr': m['yr'],
                'age': m['age'],
                'ageGroup': m.get('ageGroup', ''),
                'sDate': ev['sDate'],
                'sIp': ev['sIp'],
                'sP': ev['sP'],
                'pPerIp': p_per_ip,
                'prevP': ev['prevP'],
                'prevIp': ev['prevIp'],
                'pctPrev': ev['pctPrev'],
                'nDate': ev['nDate'],
                'nIp': ev['nIp'],
                'nP': ev['nP'],
                'nRest': ev['nRest'],
                'nextPctPrev': ev['nextPctPrev'],
                'injuryLabel': inj['label'] if inj else None,
                'injurySeverity': inj['severity'] if inj else None,
            })
            org_summary[org]['nEvents'] += 1
            org_summary[org]['pitchersInvolved'].add(name)
            if p_per_ip is not None:
                org_summary[org]['pPerIps'].append(p_per_ip)
    orgs_out = []
    for org, s in org_summary.items():
        ppi = s['pPerIps']
        orgs_out.append({
            'org': org,
            'nEvents': s['nEvents'],
            'nPitchers': len(s['pitchersInvolved']),
            'meanPperIp': round(sum(ppi) / len(ppi), 1) if ppi else None,
        })
    orgs_out.sort(key=lambda x: -x['nEvents'])
    events.sort(key=lambda e: (e['org'], e['pitcher'], e['sDate']))
    all_ppi = [e['pPerIp'] for e in events if e['pPerIp'] is not None]
    return {
        'orgs': orgs_out,
        'events': events,
        'totalEvents': len(events),
        'totalPitchersInvolved': sum(1 for evs in inefficient_data.values() if evs),
        'globalMeanPperIp': round(sum(all_ppi) / len(all_ppi), 1) if all_ppi else None,
    }

inefficient_aggregates = compute_inefficient_aggregates(inefficient_start_data, meta, injuries)
print(f"  inefficient low-IP events: {inefficient_aggregates['totalEvents']} across {inefficient_aggregates['totalPitchersInvolved']} pitchers", file=sys.stderr)


# -----------------------------------------------------------------------------
# Tempered-start detection (build-up-aware companion to short starts)
# -----------------------------------------------------------------------------

def compute_tempered_starts(starts):
    """Detect tempered starts: pitch count <= 75% of running max over prior 4 starts.

    Distinct from chased/short starts. A "tempered" start is deliberately low
    volume relative to what the pitcher has shown he can handle. Requires:
    (1) not one of the first 4 starts (so buildup doesn't dominate),
    (2) prior-4-start running max >= 50P (filter out openers/piggybacks whose
        own baseline is low), and
    (3) current P <= 75% of that running max.

    Events are distinct from short-starts because the 4IP+2IP-shorter filter
    catches "chased from the game mid-outing" while this catches "team called
    for a deliberately lighter day" (planned backdown, precaution, weather,
    piggyback slot after a deep start).
    """
    out = []
    for i, cur in enumerate(starts):
        if i < 4:
            continue
        prior_window = starts[max(0, i - 4):i]
        if not prior_window:
            continue
        window_max_p = max(s['p'] for s in prior_window)
        if window_max_p < 50:
            continue
        ratio = cur['p'] / window_max_p
        if ratio > 0.75:
            continue
        # Also skip events that overlap the low-IP definitions (true-short OR
        # inefficient-low-IP), since those are surfaced in their own tables.
        prev = starts[i - 1]
        cur_outs = ip_to_outs(cur['ip'])
        prev_outs = ip_to_outs(prev['ip'])
        is_low_ip_event = cur_outs < 12 and (prev_outs - cur_outs) >= 6
        if is_low_ip_event:
            continue
        nxt = starts[i + 1] if i + 1 < len(starts) else None
        # Running season max to date (all starts up to and including cur)
        season_max = max(s['p'] for s in starts[:i + 1])
        out.append({
            'sDate': cur['d'],
            'sIp': cur['ip'],
            'sP': cur['p'],
            'priorMaxP': window_max_p,
            'pctPriorMax': round(cur['p'] / window_max_p * 100),
            'seasonMaxToDate': season_max,
            'pctSeasonMax': round(cur['p'] / season_max * 100) if season_max else None,
            'nDate': nxt['d'] if nxt else None,
            'nIp': nxt['ip'] if nxt else None,
            'nP': nxt['p'] if nxt else None,
            'nRest': nxt['rest'] if nxt else None,
            'nextPctPriorMax': round(nxt['p'] / window_max_p * 100) if nxt else None,
        })
    return out


tempered_start_data = {name: compute_tempered_starts(d['starts']) for name, d in pitcher_data.items()}


def compute_tempered_start_aggregates(tempered_data, meta, injuries):
    """Roll up tempered-start events by org, parallel to short-start aggregates."""
    events = []
    org_summary = {}
    for name, evs in tempered_data.items():
        if not evs:
            continue
        m = meta[name]
        org = m['org']
        if org not in org_summary:
            org_summary[org] = {
                'org': org,
                'nEvents': 0,
                'pitchersWithTempered': set(),
                'ratiosPriorMax': [],
                'ratiosSeasonMax': [],
            }
        for ev in evs:
            inj = injuries.get(name)
            events.append({
                'pitcher': name,
                'org': org,
                'yr': m['yr'],
                'age': m['age'],
                'sDate': ev['sDate'],
                'sIp': ev['sIp'],
                'sP': ev['sP'],
                'priorMaxP': ev['priorMaxP'],
                'pctPriorMax': ev['pctPriorMax'],
                'seasonMaxToDate': ev['seasonMaxToDate'],
                'pctSeasonMax': ev['pctSeasonMax'],
                'nDate': ev['nDate'],
                'nIp': ev['nIp'],
                'nP': ev['nP'],
                'nRest': ev['nRest'],
                'nextPctPriorMax': ev['nextPctPriorMax'],
                'injuryLabel': inj['label'] if inj else None,
                'injurySeverity': inj['severity'] if inj else None,
            })
            org_summary[org]['nEvents'] += 1
            org_summary[org]['pitchersWithTempered'].add(name)
            org_summary[org]['ratiosPriorMax'].append(ev['pctPriorMax'])
            if ev['pctSeasonMax'] is not None:
                org_summary[org]['ratiosSeasonMax'].append(ev['pctSeasonMax'])

    orgs_out = []
    for org, s in org_summary.items():
        rp = sorted(s['ratiosPriorMax'])
        rs = sorted(s['ratiosSeasonMax'])
        def _median(xs):
            if not xs: return None
            n = len(xs)
            return xs[n // 2] if n % 2 == 1 else round((xs[n // 2 - 1] + xs[n // 2]) / 2)
        orgs_out.append({
            'org': org,
            'nEvents': s['nEvents'],
            'nPitchers': len(s['pitchersWithTempered']),
            'orgPitcherCount': sum(1 for n, mm in meta.items() if mm['org'] == org and n in pitcher_data),
            'medianPctPriorMax': _median(rp),
            'medianPctSeasonMax': _median(rs),
        })
    orgs_out.sort(key=lambda x: (x['medianPctPriorMax'] is None, x['medianPctPriorMax'] if x['medianPctPriorMax'] is not None else 999))
    events.sort(key=lambda e: (e['org'], e['pitcher'], e['sDate']))

    all_prior = sorted([e['pctPriorMax'] for e in events])
    all_season = sorted([e['pctSeasonMax'] for e in events if e['pctSeasonMax'] is not None])
    def _median(xs):
        if not xs: return None
        n = len(xs)
        return xs[n // 2] if n % 2 == 1 else round((xs[n // 2 - 1] + xs[n // 2]) / 2)
    return {
        'orgs': orgs_out,
        'events': events,
        'totalEvents': len(events),
        'totalPitchersWithTempered': sum(1 for evs in tempered_data.values() if evs),
        'globalMedianPctPriorMax': _median(all_prior),
        'globalMedianPctSeasonMax': _median(all_season),
    }


tempered_start_aggregates = compute_tempered_start_aggregates(tempered_start_data, meta, injuries)
print(f"  tempered-start events: {tempered_start_aggregates['totalEvents']} across {tempered_start_aggregates['totalPitchersWithTempered']} pitchers", file=sys.stderr)


# Augment short_start_aggregates events with pctSeasonMax column (parallel lens)
def _augment_short_events_with_season_max():
    for e in short_start_aggregates['events']:
        starts = pitcher_data[e['pitcher']]['starts']
        # Find the cur start index by date string
        idx = next((i for i, s in enumerate(starts) if s['d'] == e['sDate']), None)
        if idx is None:
            e['pctSeasonMax'] = None
            e['seasonMaxToDate'] = None
            continue
        season_max = max(s['p'] for s in starts[:idx + 1])
        e['seasonMaxToDate'] = season_max
        e['pctSeasonMax'] = round(e['sP'] / season_max * 100) if season_max else None
        # Next start's % of season max to date (at time of short start)
        if not e['endOfSeason'] and e['nP'] is not None:
            e['nextPctSeasonMax'] = round(e['nP'] / season_max * 100) if season_max else None
        else:
            e['nextPctSeasonMax'] = None

_augment_short_events_with_season_max()


# -----------------------------------------------------------------------------
# Performance-regression scheduling-response analysis
# -----------------------------------------------------------------------------

def detect_performance_regressions(starts):
    """Flag starts where fastball velo drops ≥1.0 mph OR Strike% drops ≥5 pts
    from the rolling 3-start baseline. Returns events with baseline, delta,
    next rest, and next-start rebound framing.
    """
    out = []
    for i in range(3, len(starts)):
        cur = starts[i]
        window = starts[i - 3:i]
        prior_vels = [s['vel'] for s in window if s.get('vel') is not None]
        prior_strikes = [s['strikePct'] for s in window if s.get('strikePct') is not None]
        cur_vel = cur.get('vel')
        cur_strike = cur.get('strikePct')
        vel_drop = None
        strike_drop = None
        baseline_vel = None
        baseline_strike = None
        if len(prior_vels) >= 2 and cur_vel is not None:
            baseline_vel = sum(prior_vels) / len(prior_vels)
            vel_drop = baseline_vel - cur_vel
        if len(prior_strikes) >= 2 and cur_strike is not None:
            baseline_strike = sum(prior_strikes) / len(prior_strikes)
            strike_drop = baseline_strike - cur_strike
        flags = []
        if vel_drop is not None and vel_drop >= 1.0:
            flags.append(f"velo -{vel_drop:.1f}mph")
        if strike_drop is not None and strike_drop >= 5.0:
            flags.append(f"strike% -{strike_drop:.1f}pp")
        if not flags:
            continue
        nxt = starts[i + 1] if i + 1 < len(starts) else None
        # Baseline rest for this pitcher = median of rest values >0 (rest=0 is the first start)
        all_rests = [s['rest'] for s in starts if s['rest'] and s['rest'] > 0]
        if all_rests:
            sr = sorted(all_rests)
            n = len(sr)
            baseline_rest = sr[n // 2] if n % 2 == 1 else (sr[n // 2 - 1] + sr[n // 2]) / 2
        else:
            baseline_rest = None
        next_rest = nxt['rest'] if nxt else None
        delta_rest = (next_rest - baseline_rest) if (next_rest is not None and baseline_rest is not None) else None
        # Did it rebound? Compare next-start velo/strike to cur
        rebound_vel = None
        rebound_strike = None
        if nxt and nxt.get('vel') is not None and cur_vel is not None:
            rebound_vel = nxt['vel'] - cur_vel
        if nxt and nxt.get('strikePct') is not None and cur_strike is not None:
            rebound_strike = nxt['strikePct'] - cur_strike
        out.append({
            'sDate': cur['d'],
            'sIp': cur['ip'],
            'sP': cur['p'],
            'curVel': cur_vel,
            'curStrike': cur_strike,
            'baselineVel': round(baseline_vel, 1) if baseline_vel is not None else None,
            'baselineStrike': round(baseline_strike, 1) if baseline_strike is not None else None,
            'velDrop': round(vel_drop, 1) if vel_drop is not None else None,
            'strikeDrop': round(strike_drop, 1) if strike_drop is not None else None,
            'flags': flags,
            'baselineRest': round(baseline_rest, 1) if baseline_rest is not None else None,
            'nDate': nxt['d'] if nxt else None,
            'nIp': nxt['ip'] if nxt else None,
            'nP': nxt['p'] if nxt else None,
            'nRest': next_rest,
            'deltaRest': round(delta_rest, 1) if delta_rest is not None else None,
            'reboundVel': round(rebound_vel, 1) if rebound_vel is not None else None,
            'reboundStrike': round(rebound_strike, 1) if rebound_strike is not None else None,
            'addedRest': (delta_rest is not None and delta_rest >= 2),
            'endOfSeason': nxt is None,
        })
    return out


regression_data = {name: detect_performance_regressions(d['starts']) for name, d in pitcher_data.items()}


def compute_scheduling_response(regression_data, meta):
    """Org-level roll-up: how often do teams add rest after a flagged regression?"""
    events = []
    org_summary = {}
    for name, evs in regression_data.items():
        if not evs:
            continue
        m = meta[name]
        org = m['org']
        if org not in org_summary:
            org_summary[org] = {
                'org': org,
                'nEvents': 0,
                'nAddedRest': 0,
                'nEndOfSeason': 0,
                'deltaRests': [],
            }
        for ev in evs:
            events.append({
                'pitcher': name,
                'org': org,
                'yr': m['yr'],
                **ev,
            })
            org_summary[org]['nEvents'] += 1
            if ev['addedRest']:
                org_summary[org]['nAddedRest'] += 1
            if ev['endOfSeason']:
                org_summary[org]['nEndOfSeason'] += 1
            if ev['deltaRest'] is not None:
                org_summary[org]['deltaRests'].append(ev['deltaRest'])

    orgs_out = []
    for org, s in org_summary.items():
        dr = sorted(s['deltaRests'])
        median_delta = None
        if dr:
            n = len(dr)
            median_delta = dr[n // 2] if n % 2 == 1 else round((dr[n // 2 - 1] + dr[n // 2]) / 2, 1)
        orgs_out.append({
            'org': org,
            'nEvents': s['nEvents'],
            'nAddedRest': s['nAddedRest'],
            'addedRestPct': round(100 * s['nAddedRest'] / s['nEvents']) if s['nEvents'] else 0,
            'medianDeltaRest': median_delta,
            'endOfSeason': s['nEndOfSeason'],
        })
    orgs_out.sort(key=lambda x: (-x['addedRestPct'], -x['nEvents']))
    events.sort(key=lambda e: (e['org'], e['pitcher'], e['sDate']))

    total_events = len(events)
    total_added = sum(1 for e in events if e['addedRest'])
    total_eos = sum(1 for e in events if e['endOfSeason'])
    return {
        'orgs': orgs_out,
        'events': events,
        'totalEvents': total_events,
        'totalAddedRest': total_added,
        'totalEndOfSeason': total_eos,
        'addedRestPct': round(100 * total_added / total_events) if total_events else 0,
        'totalPitchersFlagged': sum(1 for evs in regression_data.values() if evs),
    }


scheduling_response = compute_scheduling_response(regression_data, meta)
print(f"  performance-regression events: {scheduling_response['totalEvents']} across {scheduling_response['totalPitchersFlagged']} pitchers; added-rest in {scheduling_response['totalAddedRest']}", file=sys.stderr)


# -----------------------------------------------------------------------------
# Volatility (ACWR / pitch-count dispersion)
# -----------------------------------------------------------------------------

import math
import random

def _mean(xs):
    return sum(xs) / len(xs) if xs else None

def _sd(xs):
    if len(xs) < 2:
        return None
    m = _mean(xs)
    var = sum((x - m) ** 2 for x in xs) / (len(xs) - 1)
    return math.sqrt(var)

def _median(xs):
    if not xs:
        return None
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 == 1 else (s[n // 2 - 1] + s[n // 2]) / 2

def compute_volatility(starts):
    acwrs = [s['acwr'] for s in starts if s['acwr'] is not None]
    pitches = [s['p'] for s in starts]
    if not acwrs:
        return None
    acwr_mean = _mean(acwrs)
    acwr_sd = _sd(acwrs)
    acwr_cv = (acwr_sd / acwr_mean) if (acwr_sd is not None and acwr_mean) else None
    pitches_sd = _sd(pitches)
    crossings_13 = 0
    crossings_15 = 0
    for i in range(1, len(acwrs)):
        prev, cur = acwrs[i - 1], acwrs[i]
        if (prev <= 1.3 < cur) or (prev > 1.3 >= cur):
            crossings_13 += 1
        if (prev <= 1.5 < cur) or (prev > 1.5 >= cur):
            crossings_15 += 1
    return {
        'acwrSd': round(acwr_sd, 3) if acwr_sd is not None else None,
        'acwrCv': round(acwr_cv, 3) if acwr_cv is not None else None,
        'pitchesSd': round(pitches_sd, 1) if pitches_sd is not None else None,
        'crossings13': crossings_13,
        'crossings15': crossings_15,
    }

volatility_data = {name: compute_volatility(d['starts']) for name, d in pitcher_data.items()}


# -----------------------------------------------------------------------------
# Efficiency (P/IP, P/BF, high-stress rate)
# -----------------------------------------------------------------------------

HIGH_STRESS_PPI = 18.0

def compute_efficiency(starts):
    ppis = [s['pPerIp'] for s in starts if s.get('pPerIp') is not None]
    ppbs = [s['pPerBf'] for s in starts if s.get('pPerBf') is not None]
    if not ppis:
        return None
    high_stress = sum(1 for x in ppis if x >= HIGH_STRESS_PPI)
    return {
        'meanPperIp': round(_mean(ppis), 2),
        'medianPperIp': round(_median(ppis), 2),
        'meanPperBf': round(_mean(ppbs), 2) if ppbs else None,
        'highStressN': high_stress,
        'highStressPct': round(100 * high_stress / len(ppis), 1),
        'nStarts': len(ppis),
    }

efficiency_data = {name: compute_efficiency(d['starts']) for name, d in pitcher_data.items()}


# -----------------------------------------------------------------------------
# Rest instability
# -----------------------------------------------------------------------------

def compute_rest_instability(starts, weather_gaps):
    """Per-pitcher rest pattern dispersion. Excludes the first start (rest=0)
    and weather-flagged gaps from the long-rest count.
    """
    rests = [s['rest'] for s in starts[1:]]
    if not rests:
        return None
    rest_sd = _sd(rests)
    n = len(rests)
    eq7 = sum(1 for r in rests if r == 7)
    in67 = sum(1 for r in rests if 6 <= r <= 7)
    compressed = sum(1 for r in rests if r <= 4)
    long_rest = sum(1 for r in rests if r >= 10)
    return {
        'restSd': round(rest_sd, 2) if rest_sd is not None else None,
        'medianRest': _median(rests),
        'shareEq7': round(100 * eq7 / n, 1),
        'shareIn67': round(100 * in67 / n, 1),
        'compressedCount': compressed,
        'longRestCount': long_rest,
        'nIntervals': n,
    }

rest_instability_data = {name: compute_rest_instability(d['starts'], weather.get(name)) for name, d in pitcher_data.items()}


# -----------------------------------------------------------------------------
# Velocity response around events
# -----------------------------------------------------------------------------

def _vel_avg_window(starts, idx, before=True, n=2):
    if before:
        window = starts[max(0, idx - n):idx]
    else:
        window = starts[idx + 1:idx + 1 + n]
    vels = [s['vel'] for s in window if s.get('vel') is not None]
    return _mean(vels) if vels else None

def compute_velocity_response(starts):
    """For each event type, report mean Vel4S 2 starts before vs 2 starts after."""
    events_by_type = {
        'spike': [], 'compressedRest': [], 'trueShort': [], 'longGap': []
    }
    for i, cur in enumerate(starts):
        if i == 0:
            continue
        # ACWR spike >1.5
        if cur['acwr'] is not None and cur['acwr'] > 1.5:
            pre = _vel_avg_window(starts, i, True, 2)
            post = _vel_avg_window(starts, i, False, 2)
            if pre is not None and post is not None:
                events_by_type['spike'].append({'date': cur['d'], 'pre': round(pre, 1), 'post': round(post, 1), 'delta': round(post - pre, 2)})
        # Compressed rest <=4
        if cur['rest'] is not None and 0 < cur['rest'] <= 4:
            pre = _vel_avg_window(starts, i, True, 2)
            post = _vel_avg_window(starts, i, False, 2)
            if pre is not None and post is not None:
                events_by_type['compressedRest'].append({'date': cur['d'], 'pre': round(pre, 1), 'post': round(post, 1), 'delta': round(post - pre, 2)})
        # True short (<4 IP, low pitch ratio)
        if i >= 1:
            prev = starts[i - 1]
            cur_outs = ip_to_outs(cur['ip'])
            prev_outs = ip_to_outs(prev['ip'])
            if cur_outs < 12 and (prev_outs - cur_outs) >= 6 and prev['p']:
                ratio = cur['p'] / prev['p']
                if ratio <= SHORT_PITCH_RATIO:
                    pre = _vel_avg_window(starts, i, True, 2)
                    post = _vel_avg_window(starts, i, False, 2)
                    if pre is not None and post is not None:
                        events_by_type['trueShort'].append({'date': cur['d'], 'pre': round(pre, 1), 'post': round(post, 1), 'delta': round(post - pre, 2)})
        # Long gap >=10
        if cur['rest'] is not None and cur['rest'] >= 10:
            pre = _vel_avg_window(starts, i, True, 2)
            post = _vel_avg_window(starts, i, False, 2)
            if pre is not None and post is not None:
                events_by_type['longGap'].append({'date': cur['d'], 'pre': round(pre, 1), 'post': round(post, 1), 'delta': round(post - pre, 2)})
    summary = {}
    for k, evs in events_by_type.items():
        deltas = [e['delta'] for e in evs]
        summary[k] = {
            'n': len(evs),
            'meanDelta': round(_mean(deltas), 2) if deltas else None,
            'events': evs,
        }
    return summary

velocity_response_data = {name: compute_velocity_response(d['starts']) for name, d in pitcher_data.items()}


# -----------------------------------------------------------------------------
# Promotion windows (level transitions)
# -----------------------------------------------------------------------------

def _level_from_team(team_str):
    """Extract level token from teamWithLevel like 'Wisconsin Timber Rattlers (High-A)'."""
    if not team_str:
        return None
    # Look for parenthetical level
    if '(' in team_str and ')' in team_str:
        inside = team_str[team_str.index('(') + 1:team_str.rindex(')')]
        return inside.strip()
    return team_str.strip()

def compute_promotion_windows(starts):
    """Detect level transitions and report pre/post 3-start summaries."""
    levels = [_level_from_team(s.get('team', '')) for s in starts]
    promotions = []
    for i in range(1, len(levels)):
        if levels[i] and levels[i - 1] and levels[i] != levels[i - 1]:
            pre = starts[max(0, i - 3):i]
            post = starts[i:i + 3]
            if not pre or not post:
                continue
            pre_p = _mean([s['p'] for s in pre])
            post_p = _mean([s['p'] for s in post])
            pre_acwr = _mean([s['acwr'] for s in pre if s['acwr'] is not None])
            post_acwr = _mean([s['acwr'] for s in post if s['acwr'] is not None])
            pre_rest = _mean([s['rest'] for s in pre if s['rest'] and s['rest'] > 0])
            post_rest = _mean([s['rest'] for s in post if s['rest'] and s['rest'] > 0])
            pre_vel = _mean([s['vel'] for s in pre if s.get('vel') is not None])
            post_vel = _mean([s['vel'] for s in post if s.get('vel') is not None])
            # Recovery: how many post-promo starts before pitch count returns to pre-mean
            recovery_n = None
            if pre_p is not None:
                for j, s in enumerate(starts[i:i + 8]):
                    if s['p'] >= pre_p:
                        recovery_n = j + 1
                        break
            promotions.append({
                'date': starts[i]['d'],
                'fromLevel': levels[i - 1],
                'toLevel': levels[i],
                'preP': round(pre_p, 1) if pre_p is not None else None,
                'postP': round(post_p, 1) if post_p is not None else None,
                'preAcwr': round(pre_acwr, 2) if pre_acwr is not None else None,
                'postAcwr': round(post_acwr, 2) if post_acwr is not None else None,
                'preRest': round(pre_rest, 1) if pre_rest is not None else None,
                'postRest': round(post_rest, 1) if post_rest is not None else None,
                'preVel': round(pre_vel, 1) if pre_vel is not None else None,
                'postVel': round(post_vel, 1) if post_vel is not None else None,
                'velDelta': round(post_vel - pre_vel, 2) if (pre_vel is not None and post_vel is not None) else None,
                'recoveryStarts': recovery_n,
            })
    return promotions

promotion_data = {name: compute_promotion_windows(d['starts']) for name, d in pitcher_data.items()}
n_promotions = sum(len(p) for p in promotion_data.values())
print(f"  promotions detected: {n_promotions} across {sum(1 for p in promotion_data.values() if p)} pitchers", file=sys.stderr)


# -----------------------------------------------------------------------------
# Bootstrap CI helper
# -----------------------------------------------------------------------------

def bootstrap_ci(values, n_iter=1000, ci=0.90, stat='mean'):
    """Return (low, high) percentile CI of the chosen statistic. n=1 → None."""
    if not values or len(values) < 2:
        return None
    rng = random.Random(42)
    samples = []
    n = len(values)
    for _ in range(n_iter):
        sample = [values[rng.randrange(n)] for _ in range(n)]
        if stat == 'mean':
            samples.append(sum(sample) / n)
        elif stat == 'median':
            samples.append(_median(sample))
    samples.sort()
    lo_idx = int((1 - ci) / 2 * n_iter)
    hi_idx = int((1 + ci) / 2 * n_iter) - 1
    return (round(samples[lo_idx], 2), round(samples[hi_idx], 2))


# -----------------------------------------------------------------------------
# Age-group auto-computation (replaces hand-maintained numbers in overview_findings.json)
# -----------------------------------------------------------------------------

def _agg_acwr_py(starts):
    valid = [s['acwr'] for s in starts if s['acwr'] is not None]
    if not valid:
        return {'n': 0, 'mean': 0.0, 'max': 0.0, 'sweet': 0, 'sweetPct': 0.0}
    mean = sum(valid) / len(valid)
    mx = max(valid)
    sweet = sum(1 for x in valid if 0.8 <= x <= 1.3)
    return {'n': len(valid), 'mean': mean, 'max': mx, 'sweet': sweet, 'sweetPct': 100.0 * sweet / len(valid)}

def compute_age_group_stats(pitcher_data, meta, insufficient_history):
    """Auto-compute age-group averages from raw CSVs.

    Returns dict keyed by age group label ("18-19" / "20-21" / "22+") with
    n, pitchers, avg_ip, avg_max_p, avg_sweet_pct, avg_max_acwr. Pitchers
    with <4 starts (insufficient ACWR history) are excluded from sweet% and
    max_acwr averages but still counted for n and IP / max P.
    """
    groups = {}
    for name, d in pitcher_data.items():
        ag = meta[name].get('ageGroup')
        if not ag:
            continue
        groups.setdefault(ag, []).append(name)

    out = {}
    for label, names in groups.items():
        ips = []
        max_ps = []
        sweets = []
        max_acwrs = []
        for name in names:
            starts = pitcher_data[name]['starts']
            ips.append(sum(s['ipF'] for s in starts))
            max_ps.append(max(s['p'] for s in starts) if starts else 0)
            if name in insufficient_history:
                continue
            a = _agg_acwr_py(starts)
            if a['n'] > 0:
                sweets.append(a['sweetPct'])
                max_acwrs.append(a['max'])
        out[label] = {
            'n': len(names),
            'pitchers': sorted(names),
            'avg_ip': round(sum(ips) / len(ips), 1) if ips else 0,
            'avg_max_p': round(sum(max_ps) / len(max_ps)) if max_ps else 0,
            'avg_sweet_pct': round(sum(sweets) / len(sweets)) if sweets else 0,
            'avg_max_acwr': round(sum(max_acwrs) / len(max_acwrs), 2) if max_acwrs else 0.0,
            'ci_sweet_pct': bootstrap_ci(sweets) if len(sweets) >= 2 else None,
            'ci_max_p': bootstrap_ci(max_ps) if len(max_ps) >= 2 else None,
            'ci_ip': bootstrap_ci(ips) if len(ips) >= 2 else None,
            'ci_max_acwr': bootstrap_ci(max_acwrs) if len(max_acwrs) >= 2 else None,
        }
    return out

age_group_stats = compute_age_group_stats(pitcher_data, meta, insufficient_history)


# -----------------------------------------------------------------------------
# Background split (prep / college / international / unknown)
# -----------------------------------------------------------------------------

def compute_background_split(pitcher_data, meta, insufficient_history):
    groups = {}
    for name, d in pitcher_data.items():
        bg = meta[name].get('background', 'unknown')
        groups.setdefault(bg, []).append(name)
    out = {}
    for label, names in groups.items():
        ips = []
        max_ps = []
        sweets = []
        ppis = []
        for name in names:
            starts = pitcher_data[name]['starts']
            ips.append(sum(s['ipF'] for s in starts))
            max_ps.append(max(s['p'] for s in starts) if starts else 0)
            ppi_vals = [s['pPerIp'] for s in starts if s.get('pPerIp') is not None]
            if ppi_vals:
                ppis.append(_mean(ppi_vals))
            if name in insufficient_history:
                continue
            a = _agg_acwr_py(starts)
            if a['n'] > 0:
                sweets.append(a['sweetPct'])
        out[label] = {
            'n': len(names),
            'pitchers': sorted(names),
            'avg_ip': round(_mean(ips), 1) if ips else 0,
            'avg_max_p': round(_mean(max_ps)) if max_ps else 0,
            'avg_sweet_pct': round(_mean(sweets)) if sweets else 0,
            'avg_p_per_ip': round(_mean(ppis), 2) if ppis else None,
            'ci_sweet_pct': bootstrap_ci(sweets) if len(sweets) >= 2 else None,
        }
    return out

background_stats = compute_background_split(pitcher_data, meta, insufficient_history)


# -----------------------------------------------------------------------------
# Org aggregates with bootstrap CIs
# -----------------------------------------------------------------------------

def compute_org_aggregates_with_ci(pitcher_data, meta, insufficient_history):
    by_org = {}
    for name, d in pitcher_data.items():
        org = meta[name]['org']
        by_org.setdefault(org, []).append(name)
    out = {}
    for org, names in by_org.items():
        sweets = []
        max_acwrs = []
        max_ps = []
        ips = []
        ppis = []
        high_stress_pcts = []
        for name in names:
            starts = pitcher_data[name]['starts']
            ips.append(sum(s['ipF'] for s in starts))
            max_ps.append(max(s['p'] for s in starts) if starts else 0)
            ppi_vals = [s['pPerIp'] for s in starts if s.get('pPerIp') is not None]
            if ppi_vals:
                ppis.append(_mean(ppi_vals))
                hs = sum(1 for x in ppi_vals if x >= HIGH_STRESS_PPI)
                high_stress_pcts.append(100.0 * hs / len(ppi_vals))
            if name in insufficient_history:
                continue
            a = _agg_acwr_py(starts)
            if a['n'] > 0:
                sweets.append(a['sweetPct'])
                max_acwrs.append(a['max'])
        out[org] = {
            'n_pitchers': len(names),
            'pitchers': sorted(names),
            'mean_sweet_pct': round(_mean(sweets), 1) if sweets else None,
            'mean_max_acwr': round(_mean(max_acwrs), 2) if max_acwrs else None,
            'mean_max_p': round(_mean(max_ps), 1) if max_ps else None,
            'mean_ip': round(_mean(ips), 1) if ips else None,
            'mean_p_per_ip': round(_mean(ppis), 2) if ppis else None,
            'mean_high_stress_pct': round(_mean(high_stress_pcts), 1) if high_stress_pcts else None,
            'ci_sweet_pct': bootstrap_ci(sweets) if len(sweets) >= 2 else None,
            'ci_max_acwr': bootstrap_ci(max_acwrs) if len(max_acwrs) >= 2 else None,
            'ci_max_p': bootstrap_ci(max_ps) if len(max_ps) >= 2 else None,
            'ci_ip': bootstrap_ci(ips) if len(ips) >= 2 else None,
        }
    return out

org_aggregates = compute_org_aggregates_with_ci(pitcher_data, meta, insufficient_history)


# -----------------------------------------------------------------------------
# Sensitivity grid — recompute headlines under threshold variants
# -----------------------------------------------------------------------------

def compute_sensitivity_grid(pitcher_data, meta, insufficient_history):
    """For each headline metric, recompute under three threshold variants.
    Headlines: global sweet%, spike count, true-short count, tempered count,
    high-stress P/IP rate.
    """
    def _global_sweet(lo, hi):
        sweets = []
        for name, d in pitcher_data.items():
            if name in insufficient_history:
                continue
            valid = [s['acwr'] for s in d['starts'] if s['acwr'] is not None]
            if not valid:
                continue
            sweets.append(100.0 * sum(1 for x in valid if lo <= x <= hi) / len(valid))
        return round(_mean(sweets), 1) if sweets else None

    def _spike_count(thresh):
        n = 0
        for name, d in pitcher_data.items():
            for s in d['starts']:
                if s['acwr'] is not None and s['acwr'] > thresh:
                    n += 1
        return n

    def _true_short_count(ratio_cutoff):
        n = 0
        for name, d in pitcher_data.items():
            starts = d['starts']
            for i in range(1, len(starts)):
                prev = starts[i - 1]
                cur = starts[i]
                co = ip_to_outs(cur['ip'])
                po = ip_to_outs(prev['ip'])
                if co < 12 and (po - co) >= 6 and prev['p']:
                    if cur['p'] / prev['p'] <= ratio_cutoff:
                        n += 1
        return n

    def _tempered_count(ratio):
        n = 0
        for name, d in pitcher_data.items():
            starts = d['starts']
            for i, cur in enumerate(starts):
                if i < 4:
                    continue
                window = starts[max(0, i - 4):i]
                wm = max(s['p'] for s in window)
                if wm < 50:
                    continue
                if cur['p'] / wm > ratio:
                    continue
                prev = starts[i - 1]
                co = ip_to_outs(cur['ip'])
                po = ip_to_outs(prev['ip'])
                if co < 12 and (po - co) >= 6:
                    continue
                n += 1
        return n

    def _high_stress_rate(ppi_thresh):
        all_ppis = []
        for name, d in pitcher_data.items():
            for s in d['starts']:
                if s.get('pPerIp') is not None:
                    all_ppis.append(s['pPerIp'])
        if not all_ppis:
            return None
        return round(100.0 * sum(1 for x in all_ppis if x >= ppi_thresh) / len(all_ppis), 1)

    grid = {
        'sweet_bounds': {
            'default': {'label': '0.8–1.3', 'value': _global_sweet(0.8, 1.3)},
            'wider':   {'label': '0.7–1.4', 'value': _global_sweet(0.7, 1.4)},
            'tighter': {'label': '0.85–1.25', 'value': _global_sweet(0.85, 1.25)},
        },
        'spike_threshold': {
            'default': {'label': '>1.5', 'value': _spike_count(1.5)},
            'lower':   {'label': '>1.4', 'value': _spike_count(1.4)},
            'higher':  {'label': '>1.6', 'value': _spike_count(1.6)},
        },
        'true_short_ratio': {
            'default': {'label': '≤0.80', 'value': _true_short_count(0.80)},
            'tighter': {'label': '≤0.70', 'value': _true_short_count(0.70)},
            'looser':  {'label': '≤0.90', 'value': _true_short_count(0.90)},
        },
        'tempered_ratio': {
            'default': {'label': '≤0.75', 'value': _tempered_count(0.75)},
            'tighter': {'label': '≤0.70', 'value': _tempered_count(0.70)},
            'looser':  {'label': '≤0.80', 'value': _tempered_count(0.80)},
        },
        'high_stress_ppi': {
            'default': {'label': '≥18.0', 'value': _high_stress_rate(18.0)},
            'lower':   {'label': '≥17.0', 'value': _high_stress_rate(17.0)},
            'higher':  {'label': '≥19.0', 'value': _high_stress_rate(19.0)},
        },
    }
    # Flag metrics where the variants move > ±25% from default
    for k, v in grid.items():
        d = v['default']['value']
        sensitive = False
        if d not in (None, 0):
            for variant_key in v:
                if variant_key == 'default':
                    continue
                vv = v[variant_key]['value']
                if vv is None:
                    continue
                if abs(vv - d) / d > 0.25:
                    sensitive = True
                    break
        v['threshold_sensitive'] = sensitive
    return grid

sensitivity_grid = compute_sensitivity_grid(pitcher_data, meta, insufficient_history)
n_sensitive = sum(1 for v in sensitivity_grid.values() if v.get('threshold_sensitive'))
print(f"  sensitivity grid: {n_sensitive}/{len(sensitivity_grid)} metrics flagged threshold-sensitive (±25%)", file=sys.stderr)

# -----------------------------------------------------------------------------
# League-wide baseline (60+ IP MiLB starters/role-players, 18-22, 2023/2024/2025)
# Source: data/csvs/2nd set/{year} Pitchers 18-22 60IP.csv
# These are aggregated season totals (not per-game), used to give each org-page
# population context. Read once at build time; emitted to JS as LEAGUE_BASELINE
# and ORG_LEAGUE_POSITION.
# -----------------------------------------------------------------------------

def _age_bucket(age_avg):
    try:
        a = float(age_avg)
    except (TypeError, ValueError):
        return None
    if a < 20.0:   return '18-19'
    if a < 22.0:   return '20-21'
    return '22+'

def _safe_pct(s):
    """Parse '64.6%' or '64.6' → 64.6 (float)."""
    if s is None: return None
    s = str(s).strip()
    if not s or s in ('—', '-', 'NA', 'N/A'): return None
    if s.endswith('%'): s = s[:-1]
    try: return float(s)
    except ValueError: return None

def load_league_baseline():
    """
    Returns:
      LEAGUE_BASELINE[year][org_or_'__ALL__'][bucket_or_'__ALL__'] = {
          n, ip_mean, ip_median, gs_mean, p_mean, p_per_start_mean,
          k_pct_mean, strike_pct_mean, vel4s_mean
      }
    Pitches-per-start denominator filters to GS >= 5 (skip mostly-relievers).
    """
    league_dir = DATA / "csvs" / "2nd set"
    files = {
        2023: league_dir / "2023 Pitchers 18-22 60IP.csv",
        2024: league_dir / "2024 Pitchers 18-22 60IP.csv",
        2025: league_dir / "2025 Pitchers 18-22 60IP.csv",
    }
    out = {}
    for year, path in files.items():
        if not path.exists():
            print(f"  WARNING: {path} not found; skipping league baseline for {year}", file=sys.stderr)
            continue
        rows = []
        with open(path, encoding='utf-8') as f:
            for r in csv.DictReader(f):
                org = (r.get('newestOrg') or r.get('currentOrg') or '').strip()
                bucket = _age_bucket(r.get('SeasonAgeAvg'))
                if not org or not bucket: continue
                rows.append({
                    'org': org, 'bucket': bucket,
                    'ip': _safe_float(r.get('IP')),
                    'gs': _safe_int(r.get('GS')),
                    'p':  _safe_int(r.get('P')),
                    'k_pct': _safe_pct(r.get('K%')),
                    'strike_pct': _safe_pct(r.get('Strike%')),
                    'vel4s': _safe_float(r.get('Vel4S')),
                })
        # Group by org × bucket (and __ALL__ rollups)
        out[year] = {}
        groups = {}
        for r in rows:
            for org_key in (r['org'], '__ALL__'):
                for buck_key in (r['bucket'], '__ALL__'):
                    groups.setdefault(org_key, {}).setdefault(buck_key, []).append(r)
        for org_key, buckets in groups.items():
            out[year][org_key] = {}
            for buck_key, items in buckets.items():
                ips    = [x['ip'] for x in items if x['ip'] is not None]
                gss    = [x['gs'] for x in items]
                ps     = [x['p']  for x in items if x['p']  is not None]
                ppstart= [x['p'] / x['gs'] for x in items if x['p'] is not None and x['gs'] and x['gs'] >= 5]
                ks     = [x['k_pct'] for x in items if x['k_pct'] is not None]
                strs   = [x['strike_pct'] for x in items if x['strike_pct'] is not None]
                vels   = [x['vel4s'] for x in items if x['vel4s'] is not None]
                out[year][org_key][buck_key] = {
                    'n': len(items),
                    'ip_mean':         round(_mean(ips), 1)        if ips else None,
                    'ip_median':       round(_median(ips), 1)      if ips else None,
                    'gs_mean':         round(_mean(gss), 1)        if gss else None,
                    'p_mean':          round(_mean(ps))             if ps else None,
                    'p_per_start_mean':round(_mean(ppstart), 1)    if ppstart else None,
                    'k_pct_mean':      round(_mean(ks), 1)         if ks else None,
                    'strike_pct_mean': round(_mean(strs), 1)       if strs else None,
                    'vel4s_mean':      round(_mean(vels), 1)       if vels else None,
                }
    return out

def compute_org_league_position(league_baseline, ref_year=2025, ref_bucket='__ALL__'):
    """
    For each org present in the latest year, compute its rank among the 30 orgs
    on each metric (1 = highest). Used for the per-org-page 'X of N' chips.
    Returns:
      ORG_LEAGUE_POSITION[org] = {
        'year': ref_year, 'of_n': N,
        'metrics': {metric: {rank, value, p25, p50, p75}}
      }
    """
    if ref_year not in league_baseline:
        return {}
    year_data = league_baseline[ref_year]
    org_codes = [o for o in year_data if o != '__ALL__']
    metrics = ['ip_mean', 'p_per_start_mean', 'gs_mean', 'k_pct_mean', 'strike_pct_mean', 'vel4s_mean']
    # Build: per-metric, list of (org, value) sorted desc
    out = {}
    of_n = len(org_codes)
    for m in metrics:
        vals = []
        for o in org_codes:
            v = year_data[o].get(ref_bucket, {}).get(m)
            if v is not None: vals.append((o, v))
        vals.sort(key=lambda t: -t[1])
        # Compute quartiles across the values
        nums = sorted(v for _, v in vals)
        if not nums:
            continue
        def _q(p):
            idx = int(round((len(nums) - 1) * p))
            return nums[max(0, min(idx, len(nums)-1))]
        p25, p50, p75 = _q(0.25), _q(0.50), _q(0.75)
        for rank, (o, v) in enumerate(vals, start=1):
            out.setdefault(o, {'year': ref_year, 'of_n': of_n, 'metrics': {}})
            out[o]['metrics'][m] = {
                'rank': rank, 'value': v,
                'p25': p25, 'p50': p50, 'p75': p75,
            }
    return out

league_baseline = load_league_baseline()
n_seasons = sum(d.get('__ALL__', {}).get('__ALL__', {}).get('n', 0) for d in league_baseline.values())
print(f"  league baseline loaded: {n_seasons} pitcher-seasons across {len(league_baseline)} year files", file=sys.stderr)

org_league_position = compute_org_league_position(league_baseline, ref_year=2025)
print(f"  org league positions computed for {len(org_league_position)} orgs (2025 60+ IP pop)", file=sys.stderr)


# Override the numeric fields in overview.age_analysis.groups with auto-computed
# values. Keep the prose (label, takeaway) from JSON; replace the numbers so
# they never go stale when pitchers are added.
if 'age_analysis' in overview and 'groups' in overview['age_analysis']:
    for g in overview['age_analysis']['groups']:
        label = g.get('label', '')
        # Accept both "18-19" and "18-19 years old" forms
        key = label.split(' ')[0]
        stats = age_group_stats.get(key)
        if stats:
            g['n'] = stats['n']
            g['avg_ip'] = stats['avg_ip']
            g['avg_max_p'] = stats['avg_max_p']
            g['avg_sweet_pct'] = stats['avg_sweet_pct']
            g['avg_max_acwr'] = stats['avg_max_acwr']
            g['pitchers'] = stats['pitchers']


# -----------------------------------------------------------------------------
# Generate HTML
# -----------------------------------------------------------------------------

ORG_COLOR = {
    'MIL': '#BA7517', 'SEA': '#185FA5', 'NYM': '#534AB7', 'ATL': '#A32D2D',
    'TB': '#1D9E75', 'CLE': '#D4537E', 'NYY/CHW': '#5F5E5A', 'LAD': '#378ADD',
    'MIA': '#0F766E', 'NYY': '#D0D6D9', 'CLE/WAS': '#E4572E', 'WAS': '#AB0003',
    'DET': '#0C2340', 'BOS': '#BD3039'
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
    'SHORT_STARTS': short_start_aggregates,
    'INEFFICIENT_STARTS': inefficient_aggregates,
    'TEMPERED_STARTS': tempered_start_aggregates,
    'SCHEDULING_RESPONSE': scheduling_response,
    'AGE_GROUP_STATS': age_group_stats,
    'BACKGROUND_STATS': background_stats,
    'ORG_AGGREGATES': org_aggregates,
    'VOLATILITY': volatility_data,
    'EFFICIENCY': efficiency_data,
    'REST_INSTABILITY': rest_instability_data,
    'VELOCITY_RESPONSE': velocity_response_data,
    'PROMOTIONS': promotion_data,
    'SENSITIVITY': sensitivity_grid,
    'INSUFFICIENT_HISTORY': insufficient_history,
    'ORG_COLOR': ORG_COLOR,
    'LEAGUE_BASELINE': league_baseline,
    'ORG_LEAGUE_POSITION': org_league_position,
    'CROSS_DATASET': league_context_v2,
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
.league-context { background: var(--bg-subtle); border-radius: 10px; padding: 10px 12px 8px; margin-bottom: 14px; border: 1px solid var(--border); }
.league-context-header { font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-tertiary); margin-bottom: 6px; }
.league-chips { display: flex; gap: 8px; flex-wrap: wrap; }
.league-chip { background: var(--bg-card); border: 1px solid var(--border); border-radius: 8px; padding: 6px 10px; min-width: 110px; display: flex; flex-direction: column; gap: 1px; font-size: 12px; }
.league-chip-label { font-size: 10px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--text-tertiary); }
.league-chip strong { font-size: 13px; color: var(--text); }
.league-chip-val { color: var(--text-muted); font-size: 11px; }
.league-chip-pop { color: var(--text-tertiary); font-size: 10px; font-style: italic; }
.pop-chart-title { font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--text-tertiary); margin: 12px 0 4px; }
.league-context-detail { margin-top: 8px; }
.league-context-detail summary { font-size: 11px; color: var(--text-muted); cursor: pointer; padding: 4px 0; }
.league-context-table { font-size: 11px; }
.league-context-table th, .league-context-table td { padding: 4px 6px; text-align: right; }
.league-context-table th:first-child, .league-context-table td:first-child { text-align: left; }
.league-context-table .league-pop { color: var(--text-tertiary); }
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
  <button data-tab="shorts">Short starts</button>
  <button data-tab="promotions">Promotions</button>
  <button data-tab="best">Patterns</button>
  <button data-tab="ages">Age analysis</button>
  <button data-tab="methodology">Methodology</button>
</div></nav>
<main><div class="container">
<div class="tab-panel active" id="tab-overview"><div id="overview-content"></div></div>
<div class="tab-panel" id="tab-pitchers"><div class="sub-nav" id="pitcher-subnav"></div><div id="pitcher-detail"></div></div>
<div class="tab-panel" id="tab-orgs"><div class="sub-nav" id="org-subnav"></div><div id="org-detail"></div></div>
<div class="tab-panel" id="tab-shorts"><div id="shorts-content"></div></div>
<div class="tab-panel" id="tab-promotions"><div id="promotions-content"></div></div>
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
const { PITCHER_DATA, META, INJURIES, WEATHER, ORGS, OVERVIEW, BUILD_DATA, ASB_DATA, SHORT_STARTS, TEMPERED_STARTS, SCHEDULING_RESPONSE, AGE_GROUP_STATS, INSUFFICIENT_HISTORY, ORG_COLOR, INEFFICIENT_STARTS, BACKGROUND_STATS, ORG_AGGREGATES, VOLATILITY, EFFICIENCY, REST_INSTABILITY, VELOCITY_RESPONSE, PROMOTIONS, SENSITIVITY, LEAGUE_BASELINE, ORG_LEAGUE_POSITION, CROSS_DATASET } = PAYLOAD;

const FEATURED_ORGS_SET = new Set(['ATL','BOS','CLE','DET','LAD','MIA','MIL','NYM','NYY','SEA','TB']);
const _CD = {}; // Chart registry — destroyed before re-draw to avoid "canvas already in use"
function _destroyChart(id) { if (_CD[id]) { try { _CD[id].destroy(); } catch(e){} delete _CD[id]; } }
function _orgColor(o) { return ORG_COLOR[o] || '#888'; }
function _isFeatured(o) { return FEATURED_ORGS_SET.has(o); }

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

const TABS = ['overview', 'pitchers', 'orgs', 'shorts', 'promotions', 'best', 'ages', 'methodology'];

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
  // Decode hash segments — names with spaces (e.g. "Gill Hill") get URL-encoded
  // to "Gill%20Hill" by the browser; without decoding, META/ORGS lookups fail.
  const parts = location.hash.replace('#', '').split('/').map(s => {
    try { return decodeURIComponent(s); } catch (e) { return s; }
  });
  const tab = parts[0] || 'overview';
  const sub = parts[1];
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
    <div class="callout callout-info" style="margin-bottom:18px;border-left-width:4px;">
      <strong>About this study.</strong> A descriptive look at how MLB organizations manage young, valued starting pitchers during their <strong>first full affiliated MiLB season</strong>. It surfaces visible in-game starter usage — pitch counts, rest, low-IP outings, build-up shape, response to promotions — derived from game logs only. <strong>It does not capture total throwing workload</strong> (bullpens, side work, catch play, pregame, live BP) and is <strong>not an injury prediction tool</strong>. The sample is intentionally focused on pitchers who threw enough starts for org-level patterns to become visible; survivorship bias is a feature of the design, not an accident. See <a href="#methodology" style="color:inherit;text-decoration:underline;">Methodology</a> for inclusion criteria and limitations.
    </div>
    <h2>Summary</h2>
    <p class="lede">${OVERVIEW.lede}</p>
    <h2>The big picture</h2>
    <div class="two-col">${callouts}</div>
    <h2>Workload-visibility scorecard</h2>
    <p class="lede">Uncoupled rolling 4-start ACWR. Acute = current start pitches, Chronic = average of previous 3 starts. The 0.8–1.3 band is a common reference zone, not a target — we report it <em>paired with raw pitch counts</em>; ACWR alone can mislead, especially when the chronic baseline is low or volatile. Spike = &gt;1.5. Click any row to drill into the pitcher.</p>
    <div class="scorecard">
      <div class="scorecard-head"><div>pitcher · org · yr</div><div>GS</div><div>max P</div><div>ACWR max</div><div>% in 0.8–1.3 band</div><div>status</div></div>
      ${scorecard}
    </div>
    <h2>Pitch-count distribution per pitcher</h2>
    <p class="lede">p25 · median · p75 · max pitch count per pitcher. Compressed bars with a low max indicate a tighter usage envelope; wider bars indicate more variable outings. Descriptive only.</p>
    <div class="legend-row">
      <span><span class="legend-swatch" style="background:#888;opacity:0.25;"></span>p25-p75 range</span>
      <span><span class="legend-swatch" style="background:#555;width:3px;height:10px;"></span>median</span>
      <span><span class="legend-swatch" style="background:#555;border-radius:50%;"></span>max pitch count</span>
    </div>
    ${capHtml}
    <h2 style="margin-top:24px;">Injury watchlist</h2>
    <p class="lede">Confirmed or suspected injury situations with visible impact on workload data. Based on public reporting cross-referenced with CSV patterns. Listed for context — not used as outcome labels in any analysis on this site.</p>
    ${injuriesHtml}
    <h2>Patterns observed across the cohort</h2>
    ${patterns}
    ${renderPopulationResonances()}
    ${OVERVIEW.org_rankings ? `
      <details style="margin-top:32px;background:var(--bg-elev);border:1px solid var(--border);border-radius:8px;padding:14px 18px;">
        <summary style="cursor:pointer;font-weight:600;color:var(--text);font-size:15px;">Org-level descriptive snapshot — small samples, directional only ▾</summary>
        <p class="lede" style="margin-top:10px;font-size:12px;">Most orgs are represented by 1–3 pitchers in this sample. The rollups below are useful as a prompt to investigate, not as evidence of "team philosophy." We deliberately keep this section collapsed and below the per-pitcher views.</p>
        ${renderOrgRankings(OVERVIEW.org_rankings)}
      </details>
    ` : ''}
  `;
  setTimeout(() => {
    _drawReturnRates('pop-return-chart');
    _drawBuildup('pop-buildup-chart');
    _drawVolEff('pop-voleff-chart');
  }, 50);
}

function renderPopulationResonances() {
  const pr = OVERVIEW.population_resonances;
  if (!pr) return '';
  const items = pr.items.map(item => {
    return `<div class="callout callout-${item.tone}" style="margin-bottom:10px;font-size:13px;"><strong>${item.headline}</strong><br><span style="font-size:12px;">${item.body}</span></div>`;
  }).join('');
  return `
    <details open style="margin-top:32px;background:var(--bg-elev);border:1px solid var(--border);border-radius:8px;padding:14px 18px;">
      <summary style="cursor:pointer;font-weight:600;color:var(--text);font-size:15px;">${pr.title} ▾</summary>
      <p class="lede" style="margin-top:10px;font-size:12px;">${pr.intro}</p>
      <div style="margin-top:12px;">${items}</div>
      <h4 class="pop-chart-title">Same-org return rate — % of 60+ IP arms who returned with more IP (2023–2025)</h4>
      <div style="position:relative;height:380px;"><canvas id="pop-return-chart"></canvas></div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:14px;">
        <div>
          <h4 class="pop-chart-title">YoY IP buildup — avg season-over-season \u0394 (same-org repeat pairs)</h4>
          <div style="position:relative;height:310px;"><canvas id="pop-buildup-chart"></canvas></div>
        </div>
        <div>
          <h4 class="pop-chart-title">Volume vs efficiency — mean IP vs pitches per IP</h4>
          <div style="position:relative;height:310px;"><canvas id="pop-voleff-chart"></canvas></div>
        </div>
      </div>
    </details>
  `;
}

function renderOrgRankings(orgRank) {
  const tierHtml = orgRank.tiers.map(tier => {
    const orgs = tier.orgs.map(o => {
      const color = ORG_COLOR[o.org] || '#888';
      const isSingleton = o.n <= 1;
      const isSmall = o.n <= 2;
      const nColor = isSingleton ? 'var(--danger)' : isSmall ? 'var(--warn)' : 'var(--good)';
      const nBadge = isSingleton
        ? `<span class="pill pill-danger" title="Single-pitcher sample — directional only, not a trend.">n=${o.n} · single-pitcher</span>`
        : isSmall
          ? `<span class="pill pill-warn" title="Two-pitcher sample — treat as directional, not conclusive.">n=${o.n} · small sample</span>`
          : `<span class="pill pill-good">n=${o.n}</span>`;
      const rowOpacity = isSingleton ? 'opacity:0.85;' : '';
      return `<div class="org-rank-row" style="${rowOpacity}" onclick="location.hash='orgs/${o.org}'">
        <div class="org-rank-badge" style="background:${color};">${o.org}</div>
        <div class="org-rank-main">
          <div style="margin-bottom:6px;">${nBadge}</div>
          <div class="org-rank-stats">
            <span><strong>${o.sweet}%</strong><small>sweet</small></span>
            <span><strong>${o.max_acwr}</strong><small>max ACWR</small></span>
            <span><strong>${o.avg_ip}</strong><small>avg IP</small></span>
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
    <h3 style="margin-top:14px;">${orgRank.title}</h3>
    <p class="lede" style="font-size:12.5px;">${orgRank.intro}</p>
    <div class="callout callout-info" style="margin-bottom:14px;font-size:12px;"><strong>Sample-size reminder:</strong> <span class="pill pill-danger">n=1</span> rows reflect a single pitcher and should be read as <em>directional</em>, not as team-wide trends. <span class="pill pill-warn">n=2</span> rows are suggestive. Only when <span class="pill pill-good">n≥3</span> does a pattern start to become a claim. Pair every ACWR figure with raw pitch counts before drawing inferences.</div>
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

// ============================================================================
// Population-level charts (30-org, 2023-2025, 60+ IP dataset)
// ============================================================================

function _drawReturnRates(cid) {
  _destroyChart(cid);
  const ctx = document.getElementById(cid);
  if (!ctx || !window.Chart) return;
  const data = [...(CROSS_DATASET.health_all || [])].sort((a,b) => b.rate - a.rate);
  const bgColors = data.map(d => (_isFeatured(d.o) ? _orgColor(d.o) : '#888888') + (_isFeatured(d.o) ? 'dd' : '44'));
  const bdColors = data.map(d => _isFeatured(d.o) ? _orgColor(d.o) : 'transparent');
  _CD[cid] = new Chart(ctx, {
    type: 'bar',
    data: { labels: data.map(d => d.o), datasets: [{ data: data.map(d => Math.round(d.rate * 100)), backgroundColor: bgColors, borderColor: bdColors, borderWidth: data.map(d => _isFeatured(d.o) ? 1.5 : 0), borderRadius: 3 }] },
    options: {
      indexAxis: 'y', responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: ctx2 => { const d = data[ctx2.dataIndex]; return `${Math.round(d.rate*100)}% (${d.ret_n}/${d.n})`; } } } },
      scales: { x: { min:0, max:100, ticks: { callback: v=>v+'%', font:{size:10} }, grid:{color:'rgba(128,128,128,0.12)'} }, y: { ticks:{font:{size:10}}, grid:{display:false} } }
    }
  });
}

function _drawBuildup(cid) {
  _destroyChart(cid);
  const ctx = document.getElementById(cid);
  if (!ctx || !window.Chart) return;
  const data = [...(CROSS_DATASET.buildup_all || [])].sort((a,b) => b.diff - a.diff);
  _CD[cid] = new Chart(ctx, {
    type: 'bar',
    data: { labels: data.map(d=>d.o), datasets: [{ data: data.map(d=>d.diff), backgroundColor: data.map(d=>d.diff>=0?'#0f766ecc':'#c2410ccc'), borderColor: data.map(d=>_isFeatured(d.o)?_orgColor(d.o):'transparent'), borderWidth: data.map(d=>_isFeatured(d.o)?2:0), borderRadius:3 }] },
    options: {
      indexAxis:'y', responsive:true, maintainAspectRatio:false,
      plugins:{ legend:{display:false}, tooltip:{callbacks:{label: ctx2=>{ const d=data[ctx2.dataIndex]; return `${d.diff>=0?'+':''}${d.diff.toFixed(1)} IP avg (n=${d.n}, ${d.pct}% increased)`; }}} },
      scales:{ x:{ticks:{callback:v=>(v>0?'+':'')+v+' IP', font:{size:10}}, grid:{color:'rgba(128,128,128,0.12)'}}, y:{ticks:{font:{size:10}},grid:{display:false}} }
    }
  });
}

function _drawVolEff(cid) {
  _destroyChart(cid);
  const ctx = document.getElementById(cid);
  if (!ctx || !window.Chart) return;
  const raw = CROSS_DATASET.org_summary_all || [];
  _CD[cid] = new Chart(ctx, {
    type:'scatter',
    data:{ datasets:[{ data: raw.map(d=>({x:d.ip,y:d.pip,label:d.o})), backgroundColor: raw.map(d=>(_isFeatured(d.o)?_orgColor(d.o):'#888888')+(_isFeatured(d.o)?'cc':'44')), pointRadius: raw.map(d=>_isFeatured(d.o)?6:4), pointHoverRadius:8 }] },
    options:{
      responsive:true, maintainAspectRatio:false,
      plugins:{ legend:{display:false}, tooltip:{callbacks:{label: c=>{ const p=c.raw; return `${p.label}: ${p.x.toFixed(1)} IP · ${p.y.toFixed(2)} P/IP`; }}} },
      scales:{ x:{title:{display:true,text:'Mean IP',font:{size:10}},ticks:{font:{size:10}}}, y:{title:{display:true,text:'P/IP',font:{size:10}},ticks:{font:{size:10}}} }
    },
    plugins:[{ id:'volEffLabels', afterDatasetsDraw(chart){ const {ctx:c}=chart; c.save(); c.font='9px sans-serif'; const meta=chart.getDatasetMeta(0); raw.forEach((d,i)=>{ if(!_isFeatured(d.o)) return; const el=meta.data[i]; c.fillStyle=_orgColor(d.o); c.fillText(d.o,el.x+5,el.y-3); }); c.restore(); } }]
  });
}

function _drawAgeIp(cid) {
  _destroyChart(cid);
  const ctx = document.getElementById(cid);
  if (!ctx || !window.Chart) return;
  const ages=[18,19,20,21,22];
  const byAge={}; ages.forEach(a=>{byAge[a]={sn:0,sip:0};});
  (CROSS_DATASET.org_age_all||[]).forEach(r=>{ if(byAge[r.age]){byAge[r.age].sn+=r.n; byAge[r.age].sip+=r.ip*r.n;} });
  const vals=ages.map(a=>byAge[a].sn>0?+(byAge[a].sip/byAge[a].sn).toFixed(1):null);
  _CD[cid] = new Chart(ctx, {
    type:'bar',
    data:{ labels:ages.map(a=>'Age '+a), datasets:[{ data:vals, backgroundColor:['#c4b5fd88','#818cf8aa','#60a5facc','#34d399cc','#fbbf24cc'], borderRadius:4, borderWidth:0 }] },
    options:{
      responsive:true, maintainAspectRatio:false,
      plugins:{ legend:{display:false}, tooltip:{callbacks:{label:c=>{ const n=byAge[ages[c.dataIndex]].sn; return `${c.parsed.y} IP avg (n=${n} pitcher-seasons)`; }}} },
      scales:{ y:{min:60,title:{display:true,text:'Avg IP',font:{size:10}},ticks:{font:{size:10}}}, x:{ticks:{font:{size:10}}} }
    }
  });
}

function _drawAgeResults(cid) {
  _destroyChart(cid);
  const ctx = document.getElementById(cid);
  if (!ctx || !window.Chart) return;
  const raw = CROSS_DATASET.org_young_all || [];
  _CD[cid] = new Chart(ctx, {
    type:'scatter',
    data:{ datasets:[{ data:raw.map(d=>({x:d.age_vs_lvl,y:d.xprv,label:d.o})), backgroundColor:raw.map(d=>(_isFeatured(d.o)?_orgColor(d.o):'#888888')+(_isFeatured(d.o)?'cc':'44')), pointRadius:raw.map(d=>_isFeatured(d.o)?6:4), pointHoverRadius:8 }] },
    options:{
      responsive:true, maintainAspectRatio:false,
      plugins:{ legend:{display:false}, tooltip:{callbacks:{label:c=>{ const p=c.raw; return `${p.label}: age vs lvl ${p.x>=0?'+':''}${p.x.toFixed(2)}, xRV ${p.y.toFixed(4)}`; }}} },
      scales:{ x:{title:{display:true,text:'\u2190 younger for level  \u00b7  older for level \u2192',font:{size:10}},ticks:{font:{size:10}}}, y:{title:{display:true,text:'xPitchRV (lower = efficient)',font:{size:10}},ticks:{font:{size:10},callback:v=>v.toFixed(3)}} }
    },
    plugins:[{ id:'ageResLabels', afterDatasetsDraw(chart){ const {ctx:c}=chart; c.save(); c.font='9px sans-serif'; const meta=chart.getDatasetMeta(0); raw.forEach((d,i)=>{ if(!_isFeatured(d.o)) return; const el=meta.data[i]; c.fillStyle=_orgColor(d.o); c.fillText(d.o,el.x+5,el.y-3); }); c.restore(); } }]
  });
}

function _drawOrgAgeProfile(cid, orgKey) {
  _destroyChart(cid);
  const ctx = document.getElementById(cid);
  if (!ctx || !window.Chart) return;
  const lookup = orgKey.includes('/') ? orgKey.split('/')[0] : orgKey;
  const ages=[18,19,20,21,22];
  const raw=CROSS_DATASET.org_age_all||[];
  const orgMap={}; ages.forEach(a=>{orgMap[a]=null;});
  raw.filter(r=>r.o===lookup).forEach(r=>{ if(ages.includes(r.age)) orgMap[r.age]=r.ip; });
  const popMap={}; ages.forEach(a=>{popMap[a]={sn:0,sip:0};});
  raw.forEach(r=>{ if(popMap[r.age]){popMap[r.age].sn+=r.n; popMap[r.age].sip+=r.ip*r.n;} });
  const orgColor = _orgColor(lookup);
  _CD[cid] = new Chart(ctx, {
    type:'bar',
    data:{ labels:ages.map(a=>'Age '+a), datasets:[
      { label:lookup, data:ages.map(a=>orgMap[a]), backgroundColor:orgColor+'cc', borderColor:orgColor, borderWidth:1.5, borderRadius:3 },
      { label:'30-org avg', data:ages.map(a=>popMap[a].sn>0?+(popMap[a].sip/popMap[a].sn).toFixed(1):null), backgroundColor:'#88888840', borderColor:'#888888', borderWidth:1, borderRadius:3 }
    ] },
    options:{
      responsive:true, maintainAspectRatio:false,
      plugins:{ legend:{display:true,labels:{font:{size:10},boxWidth:10,padding:8}}, tooltip:{callbacks:{label:c=>`${c.dataset.label}: ${c.parsed.y==null?'\u2014':c.parsed.y.toFixed(1)+' IP'}`}} },
      scales:{ y:{min:60,title:{display:true,text:'Avg IP',font:{size:10}},ticks:{font:{size:10}}}, x:{ticks:{font:{size:10}}} }
    }
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

// League-context ribbon: where this org ranks among the 30 orgs in the 2025
// 60+ IP MiLB population (18-22 starters/role-players). Aggregated season
// totals only — directional, not start-by-start.
function renderLeagueContext(key) {
  // Most org keys map 1:1 to LEAGUE_BASELINE keys. Composite tags like 'NYY/CHW'
  // or 'CLE/WAS' don't have a league row — pick the primary.
  const lookup = key.includes('/') ? key.split('/')[0] : key;
  const pos = ORG_LEAGUE_POSITION && ORG_LEAGUE_POSITION[lookup];
  if (!pos) return '';
  const m = pos.metrics || {};
  const labelMap = {
    p_per_start_mean: 'P/start',
    ip_mean: 'IP',
    gs_mean: 'GS',
    vel4s_mean: 'Vel4S',
    k_pct_mean: 'K%',
    strike_pct_mean: 'Strike%',
  };
  // Primary 4 chips: P/start, IP, GS, Vel4S
  const chipKeys = ['p_per_start_mean', 'ip_mean', 'gs_mean', 'vel4s_mean'];
  const chips = chipKeys.filter(k => m[k]).map(k => {
    const r = m[k];
    const ord = (n) => { const j = n%10, j100 = n%100; if (j===1&&j100!==11) return n+'st'; if (j===2&&j100!==12) return n+'nd'; if (j===3&&j100!==13) return n+'rd'; return n+'th'; };
    return `<div class="league-chip"><span class="league-chip-label">${labelMap[k]}</span><strong>${ord(r.rank)} of ${pos.of_n}</strong><span class="league-chip-val">${typeof r.value === 'number' ? r.value.toFixed(1) : r.value}</span><span class="league-chip-pop">pop p50 ${typeof r.p50 === 'number' ? r.p50.toFixed(1) : r.p50}</span></div>`;
  }).join('');
  if (!chips) return '';
  // Per-bucket breakdown table (org vs all-30 by age bucket)
  const yr = pos.year;
  const yearData = (LEAGUE_BASELINE && LEAGUE_BASELINE[yr]) || {};
  const orgData = yearData[lookup] || {};
  const allData = yearData['__ALL__'] || {};
  const buckets = ['18-19', '20-21', '22+'];
  const bucketRows = buckets.map(b => {
    const o = orgData[b]; const a = allData[b];
    if (!o || !o.n) return '';
    return `<tr><td><strong>${b}</strong></td><td>${o.n}</td><td>${o.ip_mean ?? '—'}</td><td>${o.gs_mean ?? '—'}</td><td>${o.p_per_start_mean ?? '—'}</td><td>${o.vel4s_mean ?? '—'}</td><td class="league-pop">${a ? a.ip_mean : '—'}</td><td class="league-pop">${a ? a.gs_mean : '—'}</td><td class="league-pop">${a ? a.p_per_start_mean : '—'}</td></tr>`;
  }).filter(x => x).join('');
  const tableHtml = bucketRows ? `<details class="league-context-detail"><summary>Per-age-bucket breakdown — ${lookup} vs full 30-org population (${yr})</summary><div class="table-wrap"><table class="league-context-table"><thead><tr><th rowspan="2">Age</th><th rowspan="2">${lookup} n</th><th colspan="4">${lookup} mean</th><th colspan="3">All-30 mean</th></tr><tr><th>IP</th><th>GS</th><th>P/start</th><th>Vel4S</th><th>IP</th><th>GS</th><th>P/start</th></tr></thead><tbody>${bucketRows}</tbody></table></div></details>` : '';
  return `<div class="league-context"><div class="league-context-header">League position — ${yr} 60+ IP MiLB pop (18–22)${key !== lookup ? ` <span style="color:var(--text-tertiary);font-size:11px;">(showing ${lookup} for composite tag)</span>` : ''}</div><div class="league-chips">${chips}</div>${tableHtml}</div>`;
}

function renderCrossDataset(key) {
  // Reads from CROSS_DATASET.by_org[key] and ORGS[key].cross_finding.
  // Renders a compact chip strip (return rate + YoY IP avg) plus a one-line callout.
  const lookup = key.includes('/') ? key.split('/')[0] : key;
  const cd = CROSS_DATASET && CROSS_DATASET.by_org && CROSS_DATASET.by_org[lookup];
  const f = ORGS[key];
  if (!cd && !(f && f.cross_finding)) return '';

  const ord = (n) => { const j = n%10, j100 = n%100; if (j===1&&j100!==11) return n+'st'; if (j===2&&j100!==12) return n+'nd'; if (j===3&&j100!==13) return n+'rd'; return n+'th'; };
  let chipsHtml = '';
  if (cd) {
    // Return rate chip
    const rr = cd.return_rate;
    const rrPct = Math.round(rr * 100);
    const rrColor = rr >= 0.40 ? 'var(--good)' : rr >= 0.25 ? 'var(--info)' : rr === 0 ? 'var(--danger)' : 'var(--warn)';
    const rrChip = `<div class="league-chip"><span class="league-chip-label">Same-org return rate</span><strong style="color:${rrColor};">${rrPct}%</strong><span class="league-chip-val">${cd.return_n} of ${cd.return_cohort_n}</span><span class="league-chip-pop">60+ IP → more IP next yr</span></div>`;

    // YoY IP chip
    let yoyChip = '';
    if (cd.yoy_ip_avg !== null && cd.yoy_ip_avg !== undefined) {
      const yoy = cd.yoy_ip_avg;
      const yoyColor = yoy > 5 ? 'var(--good)' : yoy > 0 ? 'var(--info)' : 'var(--warn)';
      const yoySign = yoy >= 0 ? '+' : '';
      yoyChip = `<div class="league-chip"><span class="league-chip-label">YoY IP avg (same org)</span><strong style="color:${yoyColor};">${yoySign}${yoy.toFixed(1)}</strong><span class="league-chip-val">${cd.yoy_n_pairs} repeat pairs</span><span class="league-chip-pop">season-over-season Δ</span></div>`;
    }

    // P/IP efficiency chip
    const pip = cd.p_per_ip;
    const pipRank = cd.p_per_ip_rank_of_30;
    const pipColor = pipRank <= 5 ? 'var(--good)' : pipRank <= 15 ? 'var(--info)' : 'var(--warn)';
    const pipChip = `<div class="league-chip"><span class="league-chip-label">P/IP efficiency</span><strong style="color:${pipColor};">${ord(pipRank)} of 30</strong><span class="league-chip-val">${pip.toFixed(2)} P/IP</span><span class="league-chip-pop">lower = more efficient</span></div>`;

    chipsHtml = `<div class="league-context" style="margin-top:8px;"><div class="league-context-header">Cross-dataset signal — 30-org population study (2023–2025, 60+ IP)</div><div class="league-chips">${rrChip}${yoyChip}${pipChip}</div></div>`;
  }

  const calloutHtml = (f && f.cross_finding)
    ? `<div class="callout callout-info" style="font-size:12.5px;margin:8px 0 16px;border-left-color:var(--info);"><strong>Population signal:</strong> ${f.cross_finding}</div>`
    : '';

  const keySafe = key.replace('/', '_');
  const orgAgeRows = (CROSS_DATASET.org_age_all || []).filter(r => r.o === lookup);
  const ageCanvasHtml = orgAgeRows.length >= 2
    ? `<div style="margin-top:10px;"><div class="league-context-header">${lookup} \u2014 IP by age vs 30-org avg</div><div style="position:relative;height:180px;"><canvas id="org-age-chart-${keySafe}"></canvas></div></div>`
    : '';

  return chipsHtml + calloutHtml + ageCanvasHtml;
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
    ${renderLeagueContext(key)}
    ${renderCrossDataset(key)}
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
  const keySafe = key.replace('/', '_');
  setTimeout(() => _drawOrgAgeProfile('org-age-chart-' + keySafe, key), 50);
}

// ============================================================================
// Observed patterns tab
// ============================================================================

function renderBest() {
  // Renamed from "best practices" to "observed patterns" — descriptive, not prescriptive.
  const bp = OVERVIEW.observed_patterns || OVERVIEW.best_practices;
  const items = bp.items.map(i => `<div class="best-item"><div class="best-item-title">${i.title}</div><div class="best-item-body">${i.body}</div></div>`).join('');
  document.getElementById('best-content').innerHTML = `
    <h2>${bp.title}</h2>
    <p class="lede">${bp.intro}</p>
    <div class="callout callout-info" style="margin-bottom:14px;font-size:12.5px;"><strong>Framing:</strong> these are patterns we <em>observed</em> in arms that finished the season healthy and on rhythm. They are not "best practices" the analysis recommends; we cannot demonstrate causation, only describe what we saw across the visible game-log signal.</div>
    ${items}
    <h3>Pitchers whose seasons looked the cleanest on this signal</h3>
    <p class="lede" style="font-size:12px;">"Cleanest" here = high share of starts in the 0.8–1.3 ACWR band, plausible build-up shape, low rate of inefficient low-IP outings, no in-season injury flag. Read as four <em>case studies in what unbothered usage looked like</em>, not as a leaderboard.</p>
    <div class="two-col">
      <div class="callout callout-good"><strong>Parker Messick (CLE 2024, 23yo)</strong><br>138 IP · 28 GS · max 97P · 80% in-band. FSU college lefty, 2022 2nd rd. Lake County → Akron (AA). Eastern League All-Star. MLB debut April 2026 with a near-no-hitter in 11th start.</div>
      <div class="callout callout-good"><strong>Drue Hackenberg (ATL 2024, 22yo)</strong><br>129 IP · 25 GS · max 97P · 91% in-band. Virginia Tech college righty, 2023 2nd rd. Rome → Mississippi → Gwinnett (3 levels). Clean health across aggressive promotions.</div>
    </div>
    <div class="two-col">
      <div class="callout callout-good"><strong>Woodrow Ford (SEA 2025, 20yo)</strong><br>125 IP · 23 GS · max 89P · 100% in-band. 2022 2nd rd. Modesto (Low-A). Held 7-day rotation for 20 of 22 rest gaps. Only Low-A arm in this group — heavy innings at the lowest full-season level were possible here.</div>
      <div class="callout callout-good"><strong>Jonathan Santucci (NYM 2025, 22yo)</strong><br>122 IP · 26 GS · max 86P · 96% in-band. 2024 2nd rd. Brooklyn → Binghamton. Steady High-A → AA progression, opener to peak with no injury disruptions.</div>
    </div>
  `;
}

// ============================================================================
// Promotions tab — pre/post snapshots around level transitions
// ============================================================================
function renderPromotions() {
  const all = [];
  Object.keys(PROMOTIONS || {}).forEach(name => {
    (PROMOTIONS[name] || []).forEach(pr => all.push({ name, m: META[name], ...pr }));
  });
  if (!all.length) {
    document.getElementById('promotions-content').innerHTML = '<h2>Promotions</h2><p class="lede">No level transitions detected in this cohort.</p>';
    return;
  }
  // Aggregate deltas
  const deltaP = all.filter(a => a.preP != null && a.postP != null).map(a => a.postP - a.preP);
  const deltaRest = all.filter(a => a.preRest != null && a.postRest != null).map(a => a.postRest - a.preRest);
  const deltaVel = all.filter(a => a.velDelta != null).map(a => a.velDelta);
  const _mean = xs => xs.length ? (xs.reduce((s, x) => s + x, 0) / xs.length) : null;
  const meanDp = _mean(deltaP);
  const meanDr = _mean(deltaRest);
  const meanDv = _mean(deltaVel);
  const recoveries = all.filter(a => a.recoveryStarts != null).map(a => a.recoveryStarts);
  const meanRecov = _mean(recoveries);
  const fmt = (v, suf = '') => v == null ? '—' : (v > 0 ? '+' : '') + (Math.abs(v) < 10 ? v.toFixed(2) : v.toFixed(1)) + suf;

  const rows = all.sort((a, b) => a.name.localeCompare(b.name)).map(p => {
    const color = ORG_COLOR[p.m.org] || '#888';
    const dp = (p.preP != null && p.postP != null) ? p.postP - p.preP : null;
    const dr = (p.preRest != null && p.postRest != null) ? p.postRest - p.preRest : null;
    const dpColor = dp == null ? 'var(--text-tertiary)' : dp <= -10 ? 'var(--good)' : dp <= 0 ? 'var(--info)' : 'var(--warn)';
    const drColor = dr == null ? 'var(--text-tertiary)' : dr >= 1 ? 'var(--good)' : dr <= -1 ? 'var(--warn)' : 'var(--text-muted)';
    const dvColor = p.velDelta == null ? 'var(--text-tertiary)' : p.velDelta >= 0 ? 'var(--good)' : p.velDelta <= -0.5 ? 'var(--warn)' : 'var(--text-muted)';
    return `<tr onclick="location.hash='pitchers/${p.name}'" style="cursor:pointer;">
      <td><span class="pill" style="background:${color}22;color:${color};">${p.m.org}</span></td>
      <td><strong>${p.name}</strong> <span style="font-size:10px;color:var(--text-tertiary);">${p.m.yr} · age ${p.m.age}</span></td>
      <td>${p.date}</td>
      <td style="font-size:11px;">${p.fromLevel} → <strong>${p.toLevel}</strong></td>
      <td style="text-align:center;">${p.preP == null ? '—' : p.preP}</td>
      <td style="text-align:center;">${p.postP == null ? '—' : p.postP}</td>
      <td style="text-align:center;color:${dpColor};font-weight:600;">${fmt(dp, 'P')}</td>
      <td style="text-align:center;">${p.preRest == null ? '—' : p.preRest + 'd'} → ${p.postRest == null ? '—' : p.postRest + 'd'} <span style="color:${drColor};font-weight:600;">(${fmt(dr, 'd')})</span></td>
      <td style="text-align:center;color:${dvColor};font-weight:600;">${fmt(p.velDelta, 'mph')}</td>
      <td style="text-align:center;">${p.recoveryStarts == null ? '—' : p.recoveryStarts}</td>
    </tr>`;
  }).join('');

  document.getElementById('promotions-content').innerHTML = `
    <h2>Promotions — pre/post 3-start snapshots</h2>
    <p class="lede">Each row is a level transition (Low-A → High-A, High-A → AA, etc.) detected from the <code>teamWithLevel</code> field in the CSV. Pre-3 = mean across the three starts immediately before the move. Post-3 = the three starts immediately after. <strong>Recovery</strong> = number of post-promo starts before pitch count first reaches the pre-promo mean (8-start lookahead; "—" = did not recover within the window).</p>
    <p class="lede" style="font-size:12px;"><strong>Caveats:</strong> 3-start windows are thin and noisy; one bad start swings the mean. We don't normalize for opponent or schedule. Velocity comparisons can shift simply because radar guns / parks differ across affiliates. Read each row as a single case, not as proof of an org pattern.</p>
    <div class="stats-grid">
      <div class="stat"><div class="stat-label">Promotions detected</div><div class="stat-value">${all.length}</div></div>
      <div class="stat"><div class="stat-label">Pitchers promoted</div><div class="stat-value">${new Set(all.map(a => a.name)).size}</div></div>
      <div class="stat"><div class="stat-label">Mean Δ pitch count</div><div class="stat-value">${fmt(meanDp, 'P')}</div></div>
      <div class="stat"><div class="stat-label">Mean Δ rest</div><div class="stat-value">${fmt(meanDr, 'd')}</div></div>
      <div class="stat"><div class="stat-label">Mean Δ velocity</div><div class="stat-value">${fmt(meanDv, 'mph')}</div></div>
      <div class="stat"><div class="stat-label">Median recovery starts</div><div class="stat-value">${meanRecov == null ? '—' : meanRecov.toFixed(1)}</div></div>
    </div>
    <div class="table-wrap"><table>
      <thead><tr>
        <th>Org</th>
        <th>Pitcher</th>
        <th>Date</th>
        <th>Transition</th>
        <th style="text-align:center;">Pre-3 P</th>
        <th style="text-align:center;">Post-3 P</th>
        <th style="text-align:center;">Δ P</th>
        <th style="text-align:center;">Rest pre → post (Δ)</th>
        <th style="text-align:center;">Δ Vel</th>
        <th style="text-align:center;">Recovery</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table></div>
  `;
}

// ============================================================================
// Ages tab
// ============================================================================

function renderAges() {
  const a = OVERVIEW.age_analysis;
  const groupsHtml = a.groups.map(g => {
    const ciSweet = g.ci_sweet_pct ? `<div class="stat-sub">[${g.ci_sweet_pct[0].toFixed(0)}, ${g.ci_sweet_pct[1].toFixed(0)}]</div>` : (g.n <= 1 ? '<div class="stat-sub">n=1, no CI</div>' : '');
    const ciP = g.ci_max_p ? `<div class="stat-sub">[${g.ci_max_p[0].toFixed(0)}, ${g.ci_max_p[1].toFixed(0)}]</div>` : '';
    const ciIp = g.ci_ip ? `<div class="stat-sub">[${g.ci_ip[0].toFixed(0)}, ${g.ci_ip[1].toFixed(0)}]</div>` : '';
    return `
    <div class="age-group-card">
      <div class="age-group-head"><div class="age-group-label">${g.label}</div><div class="age-group-n">n = ${g.n}</div></div>
      <div class="age-group-stats">
        <div><div class="stat-label">avg IP</div><div class="stat-value">${g.avg_ip}</div>${ciIp}</div>
        <div><div class="stat-label">avg max P</div><div class="stat-value">${g.avg_max_p}</div>${ciP}</div>
        <div><div class="stat-label">avg in-band %</div><div class="stat-value">${g.avg_sweet_pct}%</div>${ciSweet}</div>
      </div>
      <div class="age-group-pitchers">${g.pitchers.map(p => `<a href="#pitchers/${p}" style="color:var(--text-muted);text-decoration:none;border-bottom:1px dotted;">${p}</a>`).join(' · ')}</div>
      <div class="age-group-takeaway">${g.takeaway}</div>
    </div>
  `;}).join('');
  const conclusionsHtml = a.conclusions.map(c => `<div class="finding"><div class="finding-body">${c}</div></div>`).join('');

  // Background split (prep / college / international / unknown). Structurally
  // present; populated where the draft string + age-at-draft was unambiguous.
  let bgHtml = '';
  if (typeof BACKGROUND_STATS !== 'undefined' && BACKGROUND_STATS) {
    const order = ['prep', 'college', 'international', 'unknown'];
    const rows = order.filter(k => BACKGROUND_STATS[k]).map(k => {
      const s = BACKGROUND_STATS[k];
      const ci = s.ci_sweet_pct ? ` <span style="font-size:10px;color:var(--text-tertiary);">[${s.ci_sweet_pct[0].toFixed(0)}, ${s.ci_sweet_pct[1].toFixed(0)}]</span>` : '';
      return `<tr>
        <td><strong>${k}</strong></td>
        <td style="text-align:center;">${s.n}</td>
        <td style="text-align:center;">${s.avg_ip}</td>
        <td style="text-align:center;">${s.avg_max_p}</td>
        <td style="text-align:center;">${s.avg_sweet_pct}%${ci}</td>
        <td style="text-align:center;">${s.avg_p_per_ip == null ? '—' : s.avg_p_per_ip}</td>
        <td style="font-size:10px;color:var(--text-muted);">${s.pitchers.join(' · ')}</td>
      </tr>`;
    }).join('');
    bgHtml = `
      <h3 style="margin-top:32px;">Split by amateur background</h3>
      <p class="lede" style="font-size:12.5px;">Prep / college / international / unknown — populated from draft string + age-at-draft where unambiguous; left as <em>unknown</em> otherwise. <strong>n is small per background — directional only.</strong> Sweet% bracketed values are 90% bootstrap CIs.</p>
      <div class="table-wrap"><table>
        <thead><tr><th>Background</th><th style="text-align:center;">n</th><th style="text-align:center;">avg IP</th><th style="text-align:center;">avg max P</th><th style="text-align:center;">avg in-band %</th><th style="text-align:center;">avg P/IP</th><th>pitchers</th></tr></thead>
        <tbody>${rows}</tbody>
      </table></div>
    `;
  }

  document.getElementById('ages-content').innerHTML = `
    <h2>${a.title}</h2>
    <p class="lede">${a.intro}</p>
    ${groupsHtml}
    <h3>Observations across age groups</h3>
    ${conclusionsHtml}
    ${bgHtml}
    <div style="margin-top:36px;border-top:1px solid var(--border);padding-top:24px;">
      <h2 style="margin-top:0;">Population context — 30-org age profile (2023\u201325, 60+ IP)</h2>
      <p class="lede" style="font-size:12.5px;">These charts pull from the full 30-org 60+ IP MiLB population analyzed separately (2023\u201325). Each org's sample spans all three seasons combined; read as directional population signal, not per-season movement. Featured orgs (colored dots) are the ones studied at per-pitcher depth on this site.</p>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:16px;">
        <div>
          <h4 class="pop-chart-title">IP by age \u2014 population-weighted avg (all 30 orgs)</h4>
          <div style="position:relative;height:240px;"><canvas id="age-ip-chart"></canvas></div>
        </div>
        <div>
          <h4 class="pop-chart-title">Age vs level \u00d7 pitch efficiency (xPitchRV proxy, lower = better)</h4>
          <div style="position:relative;height:240px;"><canvas id="age-results-chart"></canvas></div>
        </div>
      </div>
    </div>
  `;
  setTimeout(() => {
    _drawAgeIp('age-ip-chart');
    _drawAgeResults('age-results-chart');
  }, 50);
}

// ============================================================================
// Short-start cross-org view
// ============================================================================

function renderShortStarts() {
  const S = SHORT_STARTS;
  if (!S) { document.getElementById('shorts-content').innerHTML = '<p class="lede">Short-start aggregation not available.</p>'; return; }

  // Per-org summary, sorted by median reframe% ascending (lower = more tempered)
  const orgRows = S.orgs.map(o => {
    const color = ORG_COLOR[o.org] || '#888';
    const reframeColor = o.medianReframe === null ? 'var(--text-tertiary)' : o.medianReframe <= 80 ? 'var(--good)' : o.medianReframe <= 100 ? 'var(--info)' : 'var(--warn)';
    const reframeText = o.medianReframe === null ? '—' : `${o.medianReframe}%`;
    const coverage = `${o.nPitchers}/${o.orgPitcherCount}`;
    return `<tr onclick="location.hash='orgs/${o.org}'" style="cursor:pointer;">
      <td><span class="pill" style="background:${color}22;color:${color};font-weight:600;">${o.org}</span></td>
      <td style="text-align:center;">${o.nEvents}</td>
      <td style="text-align:center;">${coverage}</td>
      <td style="text-align:center;color:${reframeColor};font-weight:600;">${reframeText}</td>
      <td style="text-align:center;">${o.skippedTurns}</td>
      <td style="text-align:center;">${o.endOfSeason}</td>
    </tr>`;
  }).join('');

  // Per-event table — sorted by org, then pitcher, then date
  const eventRows = S.events.map(e => {
    const color = ORG_COLOR[e.org] || '#888';
    const reframeColor = e.nextPctPrev === null ? 'var(--text-tertiary)' : e.nextPctPrev <= 80 ? 'var(--good)' : e.nextPctPrev <= 100 ? 'var(--info)' : 'var(--warn)';
    const seasonMaxColor = e.nextPctSeasonMax == null ? 'var(--text-tertiary)' : e.nextPctSeasonMax <= 80 ? 'var(--good)' : e.nextPctSeasonMax <= 100 ? 'var(--info)' : 'var(--warn)';
    const restColor = e.nRest === null ? 'var(--text-tertiary)' : e.nRest >= 10 ? 'var(--danger)' : e.nRest <= 5 ? 'var(--info)' : 'var(--text-muted)';
    const nextCell = e.endOfSeason
      ? '<span style="color:var(--text-tertiary);font-style:italic;">end of season</span>'
      : `${e.nIp} IP · ${e.nP}P<br><span style="font-size:10px;color:${reframeColor};font-weight:600;" title="% of pre-short start's pitches">${e.nextPctPrev}% pre</span> · <span style="font-size:10px;color:${seasonMaxColor};font-weight:600;" title="% of pitcher's season-max pitches-so-far at the time of the short start">${e.nextPctSeasonMax == null ? '—' : e.nextPctSeasonMax + '%'} of max</span>`;
    const restCell = e.nRest === null ? '—' : `<span style="color:${restColor};font-weight:${e.nRest >= 10 ? '600' : '400'};">${e.nRest}d</span>${e.skipped ? ' <span class="pill pill-danger" style="font-size:8px;">skipped</span>' : ''}`;
    const injBadge = e.injurySeverity
      ? `<span class="pill ${e.injurySeverity.indexOf('TJ') >= 0 || e.injurySeverity === 'in-season' ? 'pill-danger' : e.injurySeverity === 'nagging-undiagnosed' ? 'pill-warn' : 'pill-neutral'}" style="font-size:8px;" title="${e.injuryLabel}">inj</span>`
      : '';
    return `<tr onclick="location.hash='pitchers/${e.pitcher}'" style="cursor:pointer;">
      <td><span class="pill" style="background:${color}22;color:${color};">${e.org}</span></td>
      <td><strong>${e.pitcher}</strong> ${injBadge}</td>
      <td>${e.yr}</td>
      <td>${e.sDate}</td>
      <td>${e.prevIp} IP · ${e.prevP}P</td>
      <td style="color:var(--text-muted);">${e.sIp} IP · ${e.sP}P <span style="font-size:10px;color:var(--text-tertiary);">(${e.pctPrev}% prev · ${e.pctSeasonMax == null ? '—' : e.pctSeasonMax + '% max)'}</span></td>
      <td>${restCell}</td>
      <td>${nextCell}</td>
    </tr>`;
  }).join('');

  // Headline card stats
  const globalMedian = S.globalMedianReframe === null ? '—' : `${S.globalMedianReframe}%`;
  const globalMean = S.globalMeanReframe === null ? '—' : `${S.globalMeanReframe}%`;

  // Tempered-starts block
  const T = TEMPERED_STARTS;
  const temperedOrgRows = T ? T.orgs.map(o => {
    const color = ORG_COLOR[o.org] || '#888';
    const priorColor = o.medianPctPriorMax == null ? 'var(--text-tertiary)' : o.medianPctPriorMax <= 60 ? 'var(--good)' : o.medianPctPriorMax <= 70 ? 'var(--info)' : 'var(--warn)';
    return `<tr onclick="location.hash='orgs/${o.org}'" style="cursor:pointer;">
      <td><span class="pill" style="background:${color}22;color:${color};font-weight:600;">${o.org}</span></td>
      <td style="text-align:center;">${o.nEvents}</td>
      <td style="text-align:center;">${o.nPitchers}/${o.orgPitcherCount}</td>
      <td style="text-align:center;color:${priorColor};font-weight:600;">${o.medianPctPriorMax == null ? '—' : o.medianPctPriorMax + '%'}</td>
      <td style="text-align:center;">${o.medianPctSeasonMax == null ? '—' : o.medianPctSeasonMax + '%'}</td>
    </tr>`;
  }).join('') : '';

  const temperedEventRows = T ? T.events.map(e => {
    const color = ORG_COLOR[e.org] || '#888';
    const injBadge = e.injurySeverity
      ? `<span class="pill ${e.injurySeverity.indexOf('TJ') >= 0 || e.injurySeverity === 'in-season' ? 'pill-danger' : e.injurySeverity === 'nagging-undiagnosed' ? 'pill-warn' : 'pill-neutral'}" style="font-size:8px;" title="${e.injuryLabel}">inj</span>`
      : '';
    const nextCell = e.nDate
      ? `${e.nIp} IP · ${e.nP}P <span style="font-size:10px;color:var(--text-tertiary);">(${e.nextPctPriorMax}% of prior max)</span>`
      : '<span style="color:var(--text-tertiary);font-style:italic;">end of season</span>';
    return `<tr onclick="location.hash='pitchers/${e.pitcher}'" style="cursor:pointer;">
      <td><span class="pill" style="background:${color}22;color:${color};">${e.org}</span></td>
      <td><strong>${e.pitcher}</strong> ${injBadge}</td>
      <td>${e.yr}</td>
      <td>${e.sDate}</td>
      <td>${e.sIp} IP · ${e.sP}P</td>
      <td style="font-size:10px;color:var(--text-muted);">prior max ${e.priorMaxP}P · season max ${e.seasonMaxToDate}P</td>
      <td style="color:var(--warn);font-weight:600;">${e.pctPriorMax}% / ${e.pctSeasonMax == null ? '—' : e.pctSeasonMax + '%'}</td>
      <td>${nextCell}</td>
    </tr>`;
  }).join('') : '';

  // Scheduling-response block
  const SR = SCHEDULING_RESPONSE;
  const schedOrgRows = SR ? SR.orgs.map(o => {
    const color = ORG_COLOR[o.org] || '#888';
    const pctColor = o.addedRestPct >= 50 ? 'var(--good)' : o.addedRestPct >= 25 ? 'var(--info)' : 'var(--text-muted)';
    return `<tr onclick="location.hash='orgs/${o.org}'" style="cursor:pointer;">
      <td><span class="pill" style="background:${color}22;color:${color};font-weight:600;">${o.org}</span></td>
      <td style="text-align:center;">${o.nEvents}</td>
      <td style="text-align:center;color:${pctColor};font-weight:600;">${o.nAddedRest}/${o.nEvents} · ${o.addedRestPct}%</td>
      <td style="text-align:center;">${o.medianDeltaRest == null ? '—' : (o.medianDeltaRest > 0 ? '+' : '') + o.medianDeltaRest + 'd'}</td>
      <td style="text-align:center;color:var(--text-tertiary);">${o.endOfSeason}</td>
    </tr>`;
  }).join('') : '';

  const schedEventRows = SR ? SR.events.map(e => {
    const color = ORG_COLOR[e.org] || '#888';
    const flagPills = e.flags.map(f => `<span class="pill pill-warn" style="font-size:9px;">${f}</span>`).join(' ');
    const deltaColor = e.deltaRest === null ? 'var(--text-tertiary)' : e.deltaRest >= 2 ? 'var(--good)' : e.deltaRest <= -1 ? 'var(--warn)' : 'var(--text-muted)';
    const deltaText = e.deltaRest === null ? '—' : `${e.deltaRest > 0 ? '+' : ''}${e.deltaRest}d`;
    const reboundBits = [];
    if (e.reboundVel !== null) reboundBits.push(`velo ${e.reboundVel > 0 ? '+' : ''}${e.reboundVel}mph`);
    if (e.reboundStrike !== null) reboundBits.push(`strike ${e.reboundStrike > 0 ? '+' : ''}${e.reboundStrike}pp`);
    const reboundText = e.endOfSeason ? '<span style="color:var(--text-tertiary);font-style:italic;">EOS</span>' : (reboundBits.length ? reboundBits.join(' · ') : '—');
    return `<tr onclick="location.hash='pitchers/${e.pitcher}'" style="cursor:pointer;">
      <td><span class="pill" style="background:${color}22;color:${color};">${e.org}</span></td>
      <td><strong>${e.pitcher}</strong></td>
      <td>${e.yr}</td>
      <td>${e.sDate}</td>
      <td>${flagPills}</td>
      <td style="font-size:10px;color:var(--text-muted);">${e.baselineVel == null ? '—' : e.baselineVel + 'mph'} / ${e.baselineStrike == null ? '—' : e.baselineStrike + '%'} → ${e.curVel == null ? '—' : e.curVel + 'mph'} / ${e.curStrike == null ? '—' : e.curStrike + '%'}</td>
      <td style="text-align:center;">${e.nRest == null ? '—' : e.nRest + 'd'}<br><span style="font-size:10px;color:${deltaColor};font-weight:600;">${deltaText}</span></td>
      <td style="font-size:10px;">${reboundText}</td>
    </tr>`;
  }).join('') : '';

  document.getElementById('shorts-content').innerHTML = `
    <h2>How organizations handle unprompted short starts</h2>
    <p class="lede">
      A <strong>true short-workload</strong> start = less than 4.0 IP <em>and</em> at least 2 full innings shorter than the previous start <em>and</em> the pitch count was also at most 80% of the previous start's pitch count. The pitch-count guard is the new piece: it removes outings where IP collapsed but the pitch count was held — those are <strong>inefficient low-IP outings</strong>, surfaced in their own table below. The key descriptive question: <strong>when a starter is pulled early on light pitches, does the next start come back at a tempered level or jump back to normal workload?</strong>
    </p>
    <p class="lede" style="font-size:12.5px;">
      Two framing lenses: <strong>% of pre-short start</strong> = did the org temper the NEXT start relative to what the pitcher was doing right before the chase? <strong>% of season-max-to-date</strong> = is that next start low relative to what the pitcher has carried all year? Both are reported so you can read the same event two ways. Median next-start-as-% of pre-short across the dataset: <strong>${globalMedian}</strong> (mean ${globalMean}). ${S.totalEvents} qualifying events across ${S.totalPitchersWithShort} of ${Object.keys(PITCHER_DATA).length} pitchers.
    </p>

    <div class="stats-grid">
      <div class="stat"><div class="stat-label">Short-start events</div><div class="stat-value">${S.totalEvents}</div></div>
      <div class="stat"><div class="stat-label">Pitchers affected</div><div class="stat-value">${S.totalPitchersWithShort}<span class="stat-sub">/${Object.keys(PITCHER_DATA).length}</span></div></div>
      <div class="stat"><div class="stat-label">Median reframe %</div><div class="stat-value">${globalMedian}</div></div>
      <div class="stat"><div class="stat-label">Mean reframe %</div><div class="stat-value">${globalMean}</div></div>
      <div class="stat"><div class="stat-label">Skipped-turn heuristic*</div><div class="stat-value">${S.totalSkipped}</div></div>
    </div>

    <h3>Per-org summary (sorted by median reframe %, ascending)</h3>
    <p class="lede" style="font-size:12px;">Lower median reframe = more tempered re-entry. "Coverage" = pitchers with ≥1 short start / total pitchers sampled from that org. Skipped-turn heuristic = next start's rest ≥ 10 days; most orgs normal-rest 5&ndash;8 days so ≥10d implies a skipped rotation slot. End-of-season = the short start was the last outing of the season (no next-start to analyze).</p>
    <div class="table-wrap"><table>
      <thead><tr><th>Org</th><th style="text-align:center;">Events</th><th style="text-align:center;">Coverage</th><th style="text-align:center;">Median reframe %</th><th style="text-align:center;">Skipped*</th><th style="text-align:center;">End-of-season</th></tr></thead>
      <tbody>${orgRows}</tbody>
    </table></div>
    <div class="callout callout-info" style="font-size:11.5px;">
      <strong>Reading note:</strong> with n=1–3 per org the per-org medians are more a prompt to investigate than a conclusion. The <em>event-level</em> table below is where the real signal lives — sort by pitcher to see each case's story. With only ${S.totalEvents} events across the whole dataset, no single org has enough short starts for the summary to be called a "team philosophy" on its own.
    </div>

    <h3>All short-start events</h3>
    <p class="lede" style="font-size:12px;">Click a row to drill into the pitcher. "inj" badge = the pitcher had an injury event that season (not necessarily tied to this specific short start). Percentages shown <em>prev</em> = % of pre-short start's pitches, <em>max</em> = % of pitcher's season-max pitch count at the time of the short start.</p>
    <div class="table-wrap"><table>
      <thead><tr>
        <th>Org</th>
        <th>Pitcher</th>
        <th>Year</th>
        <th>Short date</th>
        <th>Pre-short start</th>
        <th>Short start (% prev / % max)</th>
        <th>Next rest</th>
        <th>Next start (% pre · % max)</th>
      </tr></thead>
      <tbody>${eventRows}</tbody>
    </table></div>

    ${(typeof INEFFICIENT_STARTS !== 'undefined' && INEFFICIENT_STARTS && INEFFICIENT_STARTS.totalEvents > 0) ? `
      <h3 style="margin-top:32px;">Inefficient low-IP outings — same pitch count crammed into fewer innings</h3>
      <p class="lede" style="font-size:12.5px;">
        These are &lt;4 IP starts where the pitch count was held (or rose) relative to the previous start — a high-stress outing, <strong>not a short-workload event</strong>. Surfaced separately so the bucket above stays clean. Mean P/IP across these events: <strong>${INEFFICIENT_STARTS.globalMeanPperIp == null ? '—' : INEFFICIENT_STARTS.globalMeanPperIp}</strong> (vs. roughly 15–17 P/IP on a typical start).
      </p>
      <div class="table-wrap"><table>
        <thead><tr>
          <th>Org</th><th>Pitcher</th><th>Year</th><th>Date</th>
          <th>Previous start</th><th>This outing</th><th>P/IP</th><th>% of prev P</th>
        </tr></thead>
        <tbody>${INEFFICIENT_STARTS.events.map(e => {
          const color = ORG_COLOR[e.org] || '#888';
          const ppiColor = e.pPerIp != null && e.pPerIp >= 22 ? 'var(--danger)' : e.pPerIp != null && e.pPerIp >= 18 ? 'var(--warn)' : 'var(--text-muted)';
          return `<tr onclick="location.hash='pitchers/${e.pitcher}'" style="cursor:pointer;">
            <td><span class="pill" style="background:${color}22;color:${color};">${e.org}</span></td>
            <td><strong>${e.pitcher}</strong></td>
            <td>${e.yr}</td>
            <td>${e.sDate}</td>
            <td>${e.prevIp} IP · ${e.prevP}P</td>
            <td>${e.sIp} IP · ${e.sP}P</td>
            <td style="color:${ppiColor};font-weight:600;">${e.pPerIp == null ? '—' : e.pPerIp}</td>
            <td>${e.pctPrev}%</td>
          </tr>`;
        }).join('')}</tbody>
      </table></div>
      <p class="lede" style="font-size:11px;color:var(--text-tertiary);margin-top:8px;">Threshold: cur P / prev P &gt; 0.80 (vs. ≤ 0.80 for the true-short table above). Sensitivity to this 0.80 cutoff is reported on the <a href="#methodology" style="color:inherit;text-decoration:underline;">Methodology</a> tab.</p>
    ` : ''}

    <h3>Takeaways (directional — small samples)</h3>
    <div class="finding"><div class="finding-title">Most orgs re-enter slightly below the pre-short workload, not above it</div><div class="finding-body">Median reframe across the full dataset sits near ${globalMedian}, meaning the typical org cuts the next start's pitch count modestly relative to the pre-short outing. Very few events show &gt;110% — orgs are not pushing pitchers harder after a chased start.</div></div>
    <div class="finding"><div class="finding-title">Skipped turns are rare but informative</div><div class="finding-body">Only ${S.totalSkipped} of ${S.totalEvents} events have a next-rest ≥ 10 days. These are the "extra rest between starts" cases; in this dataset they cluster with injury flags (Cunningham NYY shoulder IL) or the All-Star break window (Harrison TB). Whether the extra rest was a deliberate response or a scheduling accident is not something the CSV can tell us.</div></div>
    <div class="finding"><div class="finding-title">End-of-season short starts are structurally different</div><div class="finding-body">${S.events.filter(e => e.endOfSeason).length} of the ${S.totalEvents} events were the pitcher's final outing — the CSV shows no next start, which is consistent with a season-ending shutdown rather than a reactive pull. These have no "next start" to measure and should not be read as chased starts.</div></div>

    <p class="lede" style="font-size:11px;color:var(--text-tertiary);margin-top:20px;">*Skipped-turn is a rest-based heuristic, not a reported roster move. Where the next rest ≥ 10 days we flag it as likely-skipped; the CSV alone cannot confirm whether the extra rest reflects an org decision, a scheduling gap, or an undiagnosed injury.</p>

    <h2 style="margin-top:40px;">Tempered starts — deliberately light outings (companion lens)</h2>
    <p class="lede">
      The short-start detector above catches the "chased mid-game" scenario. This second detector catches a different phenomenon: a start where the pitch count is <strong>≤ 75% of the pitcher's running max across his prior 4 starts</strong>, but the outing wasn't ended prematurely (so it doesn't appear in the chased table). This isolates outings that look like <em>planned tempering</em> — a deliberately light day rather than a cut-short game. Events that overlap the chased-start definition are excluded so the two tables are distinct.
    </p>
    <p class="lede" style="font-size:12px;">
      <strong>Caveats:</strong> This detector cannot distinguish intent from circumstance. A ≤75% outing can reflect a deliberate org decision, a rainout-compressed short start, or a pitcher getting hit early and pulled defensively. The value is that it surfaces events the chased-start filter misses (e.g. 4.0 IP at 50P after a 5.0 IP / 80P start). Read these as "events worth investigating," not as confirmed org philosophy.
    </p>
    ${T && T.totalEvents > 0 ? `
    <div class="stats-grid">
      <div class="stat"><div class="stat-label">Tempered events</div><div class="stat-value">${T.totalEvents}</div></div>
      <div class="stat"><div class="stat-label">Pitchers affected</div><div class="stat-value">${T.totalPitchersWithTempered}<span class="stat-sub">/${Object.keys(PITCHER_DATA).length}</span></div></div>
      <div class="stat"><div class="stat-label">Median % of prior max</div><div class="stat-value">${T.globalMedianPctPriorMax == null ? '—' : T.globalMedianPctPriorMax + '%'}</div></div>
      <div class="stat"><div class="stat-label">Median % of season max</div><div class="stat-value">${T.globalMedianPctSeasonMax == null ? '—' : T.globalMedianPctSeasonMax + '%'}</div></div>
    </div>
    <h3>Per-org summary</h3>
    <div class="table-wrap"><table>
      <thead><tr><th>Org</th><th style="text-align:center;">Events</th><th style="text-align:center;">Coverage</th><th style="text-align:center;">Median % prior-max</th><th style="text-align:center;">Median % season-max</th></tr></thead>
      <tbody>${temperedOrgRows}</tbody>
    </table></div>
    <h3>All tempered-start events</h3>
    <div class="table-wrap"><table>
      <thead><tr>
        <th>Org</th>
        <th>Pitcher</th>
        <th>Year</th>
        <th>Date</th>
        <th>Tempered start</th>
        <th>Baselines</th>
        <th>% prior / season max</th>
        <th>Next start</th>
      </tr></thead>
      <tbody>${temperedEventRows}</tbody>
    </table></div>
    ` : `<p class="lede" style="font-style:italic;">No qualifying tempered-start events detected with current thresholds (prior-4 max ≥ 50P, current ≤ 75% of that max, not chased, not in first 4 starts).</p>`}

    <h2 style="margin-top:40px;">Scheduling response to performance regression (exploratory)</h2>
    <p class="lede">
      Does an organization lengthen the next rest window when a pitcher has a bad start? This section flags starts where <strong>fastball velocity dropped ≥ 1.0 mph below the rolling 3-start baseline</strong>, or <strong>Strike% dropped ≥ 5 percentage points</strong>, or both. After each flagged start we compare next-rest to the pitcher's own median rest. "Added rest" = next rest ≥ baseline rest + 2 days.
    </p>
    <p class="lede" style="font-size:12px;">
      <strong>Caveats — read this block as exploratory.</strong> A 3-start rolling baseline is thin; velocity naturally varies ±1 mph start-to-start. We don't control for weather, opponent, or schedule off-days. "Added rest" does <em>not</em> prove the team responded to the regression — it could be a rainout, a scheduled rotation day, or coincidence. With ${SR ? SR.totalPitchersFlagged : 0} flagged pitchers this is a first-pass lens, not a verdict.
    </p>
    ${SR && SR.totalEvents > 0 ? `
    <div class="stats-grid">
      <div class="stat"><div class="stat-label">Regression events flagged</div><div class="stat-value">${SR.totalEvents}</div></div>
      <div class="stat"><div class="stat-label">Pitchers flagged</div><div class="stat-value">${SR.totalPitchersFlagged}<span class="stat-sub">/${Object.keys(PITCHER_DATA).length}</span></div></div>
      <div class="stat"><div class="stat-label">Added-rest response</div><div class="stat-value">${SR.totalAddedRest}<span class="stat-sub">/${SR.totalEvents} · ${SR.addedRestPct}%</span></div></div>
      <div class="stat"><div class="stat-label">End-of-season flags</div><div class="stat-value">${SR.totalEndOfSeason}<span class="stat-sub">no next-start</span></div></div>
    </div>
    <h3>Per-org summary (sorted by added-rest %)</h3>
    <div class="table-wrap"><table>
      <thead><tr><th>Org</th><th style="text-align:center;">Events</th><th style="text-align:center;">Added rest (≥ base+2d)</th><th style="text-align:center;">Median Δ-rest</th><th style="text-align:center;">End-of-season</th></tr></thead>
      <tbody>${schedOrgRows}</tbody>
    </table></div>
    <h3>All flagged regression events</h3>
    <p class="lede" style="font-size:12px;">Click a row to drill into the pitcher. "Δ-rest" = next-start rest minus this pitcher's median rest.</p>
    <div class="table-wrap"><table>
      <thead><tr>
        <th>Org</th>
        <th>Pitcher</th>
        <th>Year</th>
        <th>Date</th>
        <th>Flags</th>
        <th>3-start baseline → this start</th>
        <th>Next rest / Δ</th>
        <th>Next-start rebound</th>
      </tr></thead>
      <tbody>${schedEventRows}</tbody>
    </table></div>
    <p class="lede" style="font-size:11px;color:var(--text-tertiary);margin-top:12px;">Fastball velocity uses the CSV's <code>Vel4S</code> column; Strike% is the <code>Strike%</code> column. "Rebound" compares next-start velo/strike to the flagged start's values (positive = improvement). End-of-season events are shown but excluded from the added-rest pct calculation-by-definition since there's no next rest.</p>
    ` : `<p class="lede" style="font-style:italic;">No qualifying regression events detected with current thresholds.</p>`}
  `;
}

// ============================================================================
// Methodology tab
// ============================================================================

function renderMethodology() {
  // Sensitivity grid panel (built from SENSITIVITY payload)
  let sensHtml = '';
  if (typeof SENSITIVITY !== 'undefined' && SENSITIVITY) {
    const labelMap = {
      sweet_bounds: 'In-band ACWR % (global mean)',
      spike_threshold: 'Total ACWR-spike events',
      true_short_ratio: 'True short-workload events',
      tempered_ratio: 'Tempered-start events',
      high_stress_ppi: 'High-stress P/IP rate (%)'
    };
    const rows = Object.keys(SENSITIVITY).map(k => {
      const v = SENSITIVITY[k];
      const flag = v.threshold_sensitive ? ' <span class="pill pill-warn" style="font-size:9px;">threshold-sensitive</span>' : '';
      const cell = (variant) => v[variant] ? `<td style="text-align:center;"><div style="font-size:10px;color:var(--text-tertiary);">${v[variant].label}</div><div style="font-weight:600;">${v[variant].value == null ? '—' : v[variant].value}</div></td>` : '<td>—</td>';
      // Each metric has 'default' + two alternative variants
      const variantKeys = Object.keys(v).filter(x => x !== 'threshold_sensitive');
      return `<tr>
        <td><strong>${labelMap[k] || k}</strong>${flag}</td>
        ${variantKeys.map(cell).join('')}
      </tr>`;
    }).join('');
    sensHtml = `
      <h3 style="margin-top:32px;">Sensitivity to thresholds</h3>
      <p>Headline metrics under three threshold variants per knob. <strong>threshold-sensitive</strong> = at least one variant moves &gt; ±25% from the default. Read this as a calibration check: where a variant is flagged, do not over-interpret the headline number.</p>
      <div class="table-wrap"><table>
        <thead><tr><th>Metric</th><th style="text-align:center;">Default</th><th style="text-align:center;">Variant A</th><th style="text-align:center;">Variant B</th></tr></thead>
        <tbody>${rows}</tbody>
      </table></div>
    `;
  }

  document.getElementById('methodology-content').innerHTML = `
    <h2>Methodology</h2>
    <h3>What this study is</h3>
    <p>A descriptive study of how MLB organizations manage young, valued starting pitchers during their <strong>first full affiliated MiLB season</strong>. The unit of analysis is the in-game starter outing: pitch counts, rest days, IP, velocity, strike%, and derived metrics (ACWR, P/IP, P/BF). All findings are descriptive — we report what we saw, not what should happen.</p>
    <h3>What this study is not</h3>
    <ul>
      <li>Not a measure of total throwing workload. Bullpens, side work, catch play, pregame, and live BP are not in the CSVs and are not included in any metric on this site.</li>
      <li>Not an injury prediction model. We list known injury context for transparency; we do not use it as an outcome label or a target.</li>
      <li>Not a "best practices" guide. Where the data shows orgs that managed a season cleanly, we describe what they did — we do not claim it caused the outcome.</li>
      <li>Not a leaderboard. Per-org rollups are demoted into a collapsed section; sample sizes are small per org and the comparison is fragile.</li>
    </ul>
    <h3>Inclusion criteria</h3>
    <p>A pitcher qualifies for the cohort when ALL of the following hold:</p>
    <ul>
      <li>Started in April of the season covered by the CSV (no late call-ups, no rehab-only seasons).</li>
      <li>Accumulated enough starts that org-level usage patterns become visible (≥ ~17 starts in this sample).</li>
      <li>Was a valued org asset — top draft pick, notable IFA bonus, or known top-30 prospect — so org behavior reflects deliberate management rather than disposable depth-arm usage.</li>
      <li>The CSV covers the pitcher's first full affiliated MiLB season (<code>firstFullSeason: true</code> in metadata).</li>
    </ul>
    <p>Survivorship bias is intentional. We are deliberately filtering to arms whose seasons produced enough innings for management patterns to be readable. A pitcher who blew out in April or never reached affiliated ball would not show us anything about in-season management decisions.</p>
    <h3>Limitations</h3>
    <ul>
      <li>n is small. 24 pitchers across 11 orgs; most orgs are 1–3 pitchers. All aggregates carry wide uncertainty (90% bootstrap CIs reported on org and age rollups).</li>
      <li>The CSV cannot disambiguate intent from circumstance. A 4 IP / 50P outing might be a planned tempering, a rainout-shortened start, or a pitcher chased after a poor inning. Where we surface "tempered starts" or "scheduling response," read these as <em>events worth investigating</em>, not as confirmed org philosophy.</li>
      <li>Velocity comparisons across affiliates can shift due to differences in radar guns, parks, and operators — not just the pitcher.</li>
      <li>"Background" (prep / college / international) is populated where the draft string + age-at-draft is unambiguous; "unknown" remains where it is not.</li>
    </ul>
    <h3>Data source</h3>
    <p>TruMedia pitching KPIs export, full-season game logs. Game-by-game records include date, opponent, IP, pitches, BF, result, strike rate, velocity, breaking ball metrics, and batted ball outcomes. This analysis uses IP, pitches, BF, rest days, velocity, strike%, and derived workload metrics.</p>
    <h3>ACWR calculation</h3>
    <p>Uncoupled rolling 4-start ACWR, adapted from Gabbett (2016) for starting pitchers on a weekly rotation:</p>
    <div class="kpi-block"><div class="kpi-block-label">formula</div><div class="kpi-block-value">ACWR<sub>i</sub> = P<sub>i</sub> / mean(P<sub>i-3</sub>, P<sub>i-2</sub>, P<sub>i-1</sub>)</div></div>
    <p>Valid for starts i ≥ 4. Pitchers with fewer than 4 starts are excluded from org/age in-band % and max-ACWR averages; they are still listed in per-pitcher volume counts. <strong>ACWR alone can mislead</strong>, especially when the chronic baseline is low or volatile — we always pair it with raw pitch counts. Interpretation bounds (inclusive):</p>
    <div class="table-wrap"><table>
      <thead><tr><th>Range (inclusive bounds)</th><th>Common reference label</th></tr></thead>
      <tbody>
        <tr><td>&gt; 1.50</td><td>Spike — large jump vs. recent baseline</td></tr>
        <tr><td>1.31 – 1.50</td><td>Elevated relative to baseline</td></tr>
        <tr><td>0.80 – 1.30</td><td>Reference band ("sweet spot" in the literature)</td></tr>
        <tr><td>0.50 – 0.79</td><td>Below baseline (deload / piggyback / shortened)</td></tr>
        <tr><td>&lt; 0.50</td><td>Sharp drop (typical post-injury or first start back)</td></tr>
      </tbody>
    </table></div>
    <p>Uncoupled (exclude current start from chronic baseline) preferred over coupled because the prior-3-start average better reflects what the pitcher has been accustomed to.</p>
    <h3>Short-start definitions (split into two buckets)</h3>
    <p><strong>True short-workload start.</strong> All three of: (1) &lt; 4.0 IP, (2) ≥ 2 full IP shorter than the previous start, (3) cur P ≤ 80% of prev P. The pitch-count guard removes outings where IP collapsed but the pitch count was held — those are surfaced separately. This bucket is what feeds the bounce-back / re-entry analysis.</p>
    <p><strong>Inefficient low-IP start.</strong> &lt; 4.0 IP and ≥ 2 IP shorter than previous, but cur P &gt; 80% of prev P. Same low-IP outing, but the workload was held — a high-stress / inefficient outing, not a short-workload event. Reported in its own table on the Short-starts tab.</p>
    <h3>"% of previous" framing</h3>
    <p>For true-short aftermath, the NEXT start's pitch count is compared to the PRE-SHORT start (the one before the short one). This describes whether the next outing was tempered relative to the workload the pitcher was carrying right before the short.</p>
    <h3>Volatility, efficiency, rest-instability, velocity-response, promotions</h3>
    <p>Per-pitcher metrics: ACWR SD / CV, count of crossings of 1.3 and 1.5; mean P/IP and P/BF, share of starts at P/IP ≥ 18 (high-stress rate); rest SD, share at exactly 7 days, compressed-rest count (≤4d) and long-rest count (≥10d). For five event types (ACWR spike, compressed rest, true-short, long gap, promotion) we report mean Vel4S across the 2 starts before vs. the 2 starts after. Promotions are detected from the <code>teamWithLevel</code> field; we report pre/post 3-start means on pitches, ACWR, rest, and velocity, plus the number of post-promo starts before pitch count returned to the pre-promo mean (8-start lookahead).</p>
    <h3>Uncertainty bands</h3>
    <p>All org and age aggregates are reported with 90% bootstrap CIs (n_iter=1000, fixed seed for reproducibility). With n as small as 1–3 per org, CIs are wide — that is honest, not a flaw. n=1 rows show "n=1, no CI" rather than a fake interval.</p>
    ${sensHtml}
    <h3>Age group definitions</h3>
    <p>18-19yo, 20-21yo, 22+yo. Age is as of the season covered by the CSV (not current age). For pitchers who turned 20 during the season, they are in the 18-19 group if they were 19 at season start.</p>
    <h3>Weather caveat</h3>
    <p>CSV data does not include weather fields. Unusual gaps (8+ days without known injury or All-Star break) may reflect weather-related rainouts. Short rest windows (&lt; 5 days) can indicate compressed rotations after rainouts. Attribution of suspicious gaps is tracked in <code>data/weather_flags.json</code> based on reporting and game-log context.</p>
    <h3>Repo structure</h3>
    <div class="kpi-block"><div class="kpi-block-value" style="font-family:monospace;white-space:pre;font-size:11px;">pitcher-workload-research/
├── data/
│   ├── csvs/              TruMedia exports — drop new ones here
│   ├── metadata.json      Pitcher meta (org, yr, age, draft, background, firstFullSeason)
│   ├── injury_flags.json  Per-pitcher injury context
│   ├── weather_flags.json Per-pitcher gap attribution
│   ├── org_findings.json  Per-org qualitative writeups
│   └── overview_findings.json  Top-level patterns and callouts
├── scripts/
│   └── build.py           Regenerates docs/index.html
├── docs/
│   └── index.html         The deliverable (GitHub Pages)
└── README.md</div></div>
    <p>To add a pitcher: drop CSV in data/csvs/, add entry to metadata.json (set <code>firstFullSeason</code> and <code>background</code>), optionally add injury/weather notes, run scripts/build.py, commit &amp; push.</p>
  `;
}

// ============================================================================
// Initialize
// ============================================================================

renderOverview();
renderPitcherSubnav();
renderOrgSubnav();
renderShortStarts();
renderPromotions();
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
with open(OUT, 'w', encoding='utf-8') as f:
    f.write(html)

print(f"\nBuilt {OUT}", file=sys.stderr)
print(f"  {len(pitcher_data)} pitchers", file=sys.stderr)
print(f"  {len(orgs)} organizations", file=sys.stderr)
print(f"  {OUT.stat().st_size:,} bytes", file=sys.stderr)
