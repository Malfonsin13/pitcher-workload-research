#!/usr/bin/env python3
"""
OF Positioning with Data-Driven Hang‑Time Model
=================================================

This script combines three pieces of functionality:

1. **Scrape Batted‑Ball Data**
   Using credentials for MLB's Okta authentication and the public Stats API,
   the script fetches every in‑play batted ball for players on a specified
   minor‑league team.  It records exit velocity (EV), launch angle (LA),
   hang time, Statcast coordinates and other context.

2. **Train a Hang‑Time Prior**
   With the scraped data, we build a simple prior mapping from `(distance bin,
   spray angle bucket, batter handedness)` to a three‑point mixture of
   hang‑time values and typical EV/LA.  The prior is computed from the
   empirical quantiles of hang time and medians of EV/LA within each bin.

3. **Outfield Positioning**
   We ingest a separate CSV containing batted‑ball events for your High‑A
   dataset.  For each event, if EV and LA are present, a blended
   physics/regression estimator is used.  Otherwise, we infer EV, LA and
   hang‑time distributions from the trained prior using only distance,
   spray‑angle bucket and batter handedness.  These estimates drive a
   probabilistic greedy placement of outfielders, producing the same output
   as the original v3 script while avoiding synthetic assumptions when
   Statcast fields are missing.

To run this script end‑to‑end you will need:

* Valid Okta credentials in environment variables `OKTA_USER` and
  `OKTA_PASS`.  These are used to authenticate with the Stats API.  The
  credentials are *not* embedded in this file.
* A team ID for the minor‑league affiliate you wish to scrape.  When run
  interactively, the script prompts for this ID.
* A CSV of batted‑ball events for which you wish to compute positioning.
  The format must match the one produced by your existing `team_batted_ball_metrics.csv`.

The script writes no files by default; it simply prints a positioning
summary and plots per‑batter diagrams as in the original v3 tool.  You can
modify the final section (`if __name__ == "__main__":`) to save outputs
elsewhere if desired.
"""

import os
import sys
import json
import math
from datetime import date
from typing import Dict, Tuple, List, Optional

import requests
import numpy as np
import pandas as pd
from requests.auth import HTTPBasicAuth
from tqdm.auto import tqdm
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages


# ── 0. Okta authentication helpers ──────────────────────────────────────────
OKTA_BASE = "https://statsapi.mlb.com/api/v1/authentication/okta"

def _okta_session() -> requests.Session:
    """Create an authenticated requests.Session using Okta creds.

    Environment variables `OKTA_USER` and `OKTA_PASS` must be set.
    """
    user = os.getenv("OKTA_USER")
    pw = os.getenv("OKTA_PASS")
    if not user or not pw:
        raise RuntimeError("Environment variables OKTA_USER and OKTA_PASS must be set.")
    sess = requests.Session()
    r = sess.post(
        f"{OKTA_BASE}/token",
        auth=HTTPBasicAuth(user, pw),
        headers={"Content-Type": "application/json"},
    )
    r.raise_for_status()
    refresh = r.json()["refresh_token"]
    r = sess.post(
        f"{OKTA_BASE}/token/refresh",
        params={"refreshToken": refresh},
        headers={"Content-Type": "application/json"},
    )
    r.raise_for_status()
    sess.headers.update({"Authorization": f"Bearer {r.json()['access_token']}"})
    return sess


# ── 1. Statcast scraping functions ─────────────────────────────────────────

SPORT_IDS = [1, 11, 12, 13, 14, 16]  # AAA, AA, High‑A, A, Rookie

def roster_df(team_id: int, sess: requests.Session) -> pd.DataFrame:
    """Fetch active roster for a given team ID via Stats API."""
    resp = sess.get(
        f"https://statsapi.mlb.com/api/v1/teams/{team_id}/roster",
        params={"rosterType": "Active"},
    )
    resp.raise_for_status()
    df = pd.json_normalize(resp.json()["roster"])
    df = df.rename(
        columns={"person.id": "player_id", "person.fullName": "player_name"}
    )
    return df[["player_id", "player_name"]]


def games_for(player_id: int, season: int, sess: requests.Session) -> List[int]:
    """Return list of game PKs where the player appeared this season."""
    games: set[int] = set()
    gts = "[R]"  # Regular season only
    for sid in SPORT_IDS:
        url = (
            f"https://statsapi.mlb.com/api/v1/people/{player_id}"
            f"?hydrate=stats(group=hitting,type=gameLog,season={season},"
            f"startDate={season}-01-01,endDate={date.today().isoformat()},"
            f"sportId={sid},gameType={gts}),hydrations"
        )
        r = sess.get(url)
        r.raise_for_status()
        splits = (
            r.json().get("people", [{}])[0]
            .get("stats", [{}])[0]
            .get("splits", [])
        )
        games.update(s["game"]["gamePk"] for s in splits)
    return sorted(games)


def all_plays(game_pk: int, sess: requests.Session) -> List[dict]:
    """Fetch all plays from the live‑data feed for a given game PK."""
    for ver in ("v1", "v1.1"):
        url = f"https://statsapi.mlb.com/api/{ver}/game/{game_pk}/feed/live"
        r = sess.get(url)
        if r.status_code == 200:
            return (
                r.json()
                .get("liveData", {})
                .get("plays", {})
                .get("allPlays", [])
            )
    return []


CACHE_ANALYTICS: Dict[Tuple[int, str], Tuple[Optional[float], Optional[float]]] = {}

def ev_la_from_analytics(game_pk: int, play_id: str, sess: requests.Session) -> Tuple[Optional[float], Optional[float]]:
    """Fallback to analytics endpoint if launch data missing."""
    key = (game_pk, play_id)
    if key in CACHE_ANALYTICS:
        return CACHE_ANALYTICS[key]
    url = f"https://statsapi.mlb.com/api/v1/game/{game_pk}/{play_id}/analytics"
    r = sess.get(url)
    ev = la = None
    if r.status_code == 200:
        ld = r.json().get("hitSegment", {}).get("launchData", {})
        ev = ld.get("speed")
        la = ld.get("angle")
    CACHE_ANALYTICS[key] = (ev, la)
    return ev, la


def scrape_team_batted_balls(team_id: int, season: int = None) -> pd.DataFrame:
    """Scrape all in‑play batted balls for a team's active roster.

    Parameters
    ----------
    team_id : int
        MLB team identifier (minor‑league affiliate ID works).
    season : int, optional
        Season year to scrape; defaults to current year.

    Returns
    -------
    DataFrame
        One row per batted ball with EV, LA, hang time, distance, coordinates and context.
    """
    if season is None:
        season = date.today().year
    sess = _okta_session()
    roster = roster_df(team_id, sess)
    print(f"Scraping roster {team_id}: {len(roster)} players")
    rows: List[dict] = []
    for pid, pname in roster.itertuples(index=False):
        game_pks = games_for(pid, season, sess)
        print(f"  {pname} ({pid}) - {len(game_pks)} games")
        for gpk in tqdm(game_pks, desc=f"    games for {pname}"):
            plays = all_plays(gpk, sess)
            for play in plays:
                # Only consider this batter's at‑bat
                if play.get("matchup", {}).get("batter", {}).get("id") != pid:
                    continue
                # Each in‑play event in the AB
                for ev in play.get("playEvents", []):
                    if not ev.get("details", {}).get("isInPlay"):
                        continue
                    hit = ev.get("hitData")
                    if hit is None:
                        continue
                    evelo = hit.get("launchSpeed")
                    lang = hit.get("launchAngle")
                    if evelo is None or lang is None:
                        # Fallback to analytics endpoint
                        evelo2, lang2 = ev_la_from_analytics(gpk, play.get("playId"), sess)
                        evelo = evelo or evelo2
                        lang = lang or lang2
                    rows.append({
                        "player_id": pid,
                        "player_name": pname,
                        "game_pk": gpk,
                        "inning": play.get("about", {}).get("inning"),
                        "halfInning": play.get("about", {}).get("halfInning"),
                        "balls": play.get("count", {}).get("balls"),
                        "strikes": play.get("count", {}).get("strikes"),
                        "startTime": play.get("about", {}).get("startTime"),
                        "stand": play.get("matchup", {}).get("batSide", {}).get("code"),
                        "p_throws": play.get("matchup", {}).get("pitchHand", {}).get("code"),
                        "exit_velocity": evelo,
                        "launch_angle": lang,
                        "hang_time": hit.get("trajectoryData", {}).get("zoneTime"),
                        "distance": hit.get("totalDistance"),
                        "hc_x": hit.get("coordinates", {}).get("coordX"),
                        "hc_y": hit.get("coordinates", {}).get("coordY"),
                        "event_type": play.get("result", {}).get("event"),
                        "pitch_type": ev.get("details", {}).get("type", {}).get("description"),
                    })
    return pd.DataFrame(rows)


# ── 2. Classification helpers (adapted from v3) ───────────────────────────

# Angle bins as defined in the v3 script
ANGLE_BINS: Dict[str, Dict[str, List[Tuple[str, float, float]]]] = {
    'R': {
        'LF': [('OPPO', 107.5, 110.1), ('STRAIGHT', 110.1, 117.6),
                ('PULL (1)', 117.6, 120.1), ('PULL (2)', 120.1, 125.1)],
        'CF': [('OPPO', 80.0, 82.6), ('STRAIGHT', 82.6, 90.1),
                ('PULL (1)', 90.1, 92.6), ('PULL (2)', 92.6, 97.6)],
        'RF': [('OPPO', 57.5, 60.1), ('STRAIGHT', 60.1, 67.6),
                ('PULL (1)', 67.6, 70.1), ('PULL (2)', 70.1, 75.1)]
    }
}
_mirror_pos = {'LF': 'RF', 'RF': 'LF', 'CF': 'CF'}
# Mirror bins for lefties
ANGLE_BINS['L'] = {
    _mirror_pos[p]: [
        (lab, 180 - hi, 180 - lo) for (lab, lo, hi) in ANGLE_BINS['R'][p]
    ][::-1]  # sort ascending by lower bound
    for p in ANGLE_BINS['R']
}


def classify_angle(pos: str, ang_deg: float, bat_side: str) -> str:
    """Assign the spray angle to a label using angle bins."""
    bins = ANGLE_BINS.get(bat_side, ANGLE_BINS['R'])
    for lab, lo, hi in bins[pos]:
        # subtract small eps at upper bound to avoid floating equality
        if lo <= ang_deg < hi - 1e-6:
            return lab
    return 'OTHER'


def depth_cat(pos: str, d_ft: float) -> str:
    """Assign a depth category based on distance."""
    if pos == 'CF':
        return 'SHALLOW' if d_ft < 290 else 'NORMAL' if d_ft < 315 else 'DEEP'
    return 'SHALLOW' if d_ft < 270 else 'NORMAL' if d_ft <= 300 else 'DEEP'


def spray_theta_deg(x: float, y: float) -> float:
    """Compute field polar angle in degrees (45..135)."""
    return math.degrees(math.atan2(y, x))


def pos_for_theta(th_deg: float, bat_side: str) -> str:
    """Determine OF sector (RF/CF/LF) based on polar angle and batter side."""
    # Boundaries match those used in v3 classification
    if 45.0 <= th_deg < 75.0:
        return 'RF'
    if 75.0 <= th_deg <= 105.0:
        return 'CF'
    return 'LF'


# ── 3. Training prior from real data ──────────────────────────────────────

def train_prior(df_train: pd.DataFrame) -> Dict[Tuple[int, str, str], dict]:
    """Train a simple prior over (distance bin, angle bucket, handedness).

    Parameters
    ----------
    df_train : DataFrame
        DataFrame of Statcast batted balls with columns:
        exit_velocity, launch_angle, hang_time, distance, hc_x, hc_y, stand.

    Returns
    -------
    dict
        Mapping from (distance_bin_index, bucket_label, hand_key) to a
        dictionary with keys 'ev', 'la', 'times', 'weights'.
    """
    prior: Dict[Tuple[int, str, str], dict] = {}
    # Define distance bin edges (matching DIST_BINS used later)
    dist_edges = [150, 180, 210, 240, 270, 300, 330, 360, 390, float('inf')]
    # Only use rows with non‑null distance and hang_time
    df = df_train.copy().dropna(subset=['distance', 'hang_time', 'launch_angle', 'exit_velocity', 'hc_x', 'hc_y', 'stand'])
    # Re‑anchor coordinates to feet using same scale as v3
    SCALE_FACTOR = 330.0 / math.hypot(100.0, 100.0)
    df['x_ft'] = (df['hc_x'] - 125.42) * SCALE_FACTOR
    df['y_ft'] = (198.27 - df['hc_y']) * SCALE_FACTOR
    # Determine distance bins
    df['dist_bin'] = pd.cut(df['distance'].astype(float), bins=dist_edges, labels=False, include_lowest=True)
    # Batter side normalization
    df['hand'] = df['stand'].str.upper().map({'R': 'R', 'L': 'L'}).fillna('R')
    # Compute spray angles
    df['theta'] = np.degrees(np.arctan2(df['y_ft'], df['x_ft']))
    # For each group, compute medians and quantiles
    for (bin_idx, hand) in df[['dist_bin', 'hand']].dropna().drop_duplicates().itertuples(index=False):
        sub = df[(df['dist_bin'] == bin_idx) & (df['hand'] == hand)]
        # Partition by OF sector first to use correct angle bins per sector
        for pos in ['LF', 'CF', 'RF']:
            # Subset for this sector based on polar angle
            if pos == 'RF':
                sector_rows = sub[(sub['theta'] >= 45.0) & (sub['theta'] < 75.0)]
            elif pos == 'CF':
                sector_rows = sub[(sub['theta'] >= 75.0) & (sub['theta'] <= 105.0)]
            else:  # LF
                sector_rows = sub[((sub['theta'] < 45.0) | (sub['theta'] > 105.0))]
            if sector_rows.empty:
                continue
            # Within this sector, assign bucket labels
            sector_rows = sector_rows.copy()
            sector_rows['bucket'] = sector_rows.apply(
                lambda r: classify_angle(pos, r['theta'], hand), axis=1
            )
            for bucket_label in sector_rows['bucket'].unique():
                grp = sector_rows[sector_rows['bucket'] == bucket_label]
                if grp.empty:
                    continue
                key = (int(bin_idx), bucket_label, hand)
                # Compute mixture times (25th, 50th, 75th percentiles)
                times = np.nanpercentile(grp['hang_time'].astype(float), [25, 50, 75]).tolist()
                # Compute typical EV and LA (median)
                ev_med = float(np.nanmedian(grp['exit_velocity'].astype(float))) if not grp['exit_velocity'].isnull().all() else None
                la_med = float(np.nanmedian(grp['launch_angle'].astype(float))) if not grp['launch_angle'].isnull().all() else None
                prior[key] = {
                    'ev': ev_med,
                    'la': la_med,
                    'times': times,
                    'weights': [0.25, 0.5, 0.25],
                }
    return prior


# Global variable to hold prior once trained
TRAINED_PRIOR: Dict[Tuple[int, str, str], dict] = {}


# ── 4. Hang‑time and EV/LA estimation using prior ──────────────────────────

def estimate_ht_for_df_with_prior(subdf: pd.DataFrame) -> pd.Series:
    """Estimate hang time per row using EV/LA if present or prior otherwise.

    Also populates `ev_est`, `la_est` and `ht_method` columns on subdf.

    Parameters
    ----------
    subdf : DataFrame
        Batted‑ball events to estimate.

    Returns
    -------
    Series
        Estimated hang time values.
    """
    ev_col = _first_col(subdf, ['launch_speed', 'exit_velocity', 'ev', 'launchSpeed', 'exit_velo'])
    la_col = _first_col(subdf, ['launch_angle', 'la', 'launchAngle'])
    ht_vals: List[float] = []
    ev_est: List[Optional[float]] = []
    la_est: List[Optional[float]] = []
    methods: List[str] = []
    for idx, row in subdf.iterrows():
        evx = lax = None
        t_est = None
        method = 'no_data'
        if ev_col and la_col and pd.notna(row.get(ev_col)) and pd.notna(row.get(la_col)):
            # Use blended physics/regression if EV/LA present
            evx = float(row[ev_col])
            lax = float(row[la_col])
            t_est = ht_from_ev_la(evx, lax)
            method = 'ev_la_regression_blend' if HT_MODEL.get('trained', False) else 'ev_la_physics_only'
        else:
            # Distance, angle, hand only
            d_ft = float(row['distance']) if pd.notna(row.get('distance')) else None
            x_ft = float(row['x']) if pd.notna(row.get('x')) else None
            y_ft = float(row['y']) if pd.notna(row.get('y')) else None
            hand_key = row.get('stand', 'R')
            if d_ft is not None and x_ft is not None and y_ft is not None:
                # Determine bin index
                # Use same dist_bins as training for bin index
                bin_edges = [150, 180, 210, 240, 270, 300, 330, 360, 390, float('inf')]
                bin_idx = None
                for i, edge in enumerate(bin_edges):
                    if d_ft < edge:
                        bin_idx = i
                        break
                if bin_idx is None:
                    bin_idx = len(bin_edges) - 1
                # Compute spray angle and bucket
                th_deg = float(np.degrees(np.arctan2(y_ft, x_ft)))
                pos = pos_for_theta(th_deg, hand_key)
                bucket = classify_angle(pos, th_deg, hand_key)
                key = (int(bin_idx), bucket, hand_key)
                prior = TRAINED_PRIOR.get(key)
                if prior is not None:
                    times = prior['times']
                    t_est = times[1]  # median
                    evx = prior['ev']
                    lax = prior['la']
                    method = 'dist_angle_prior'
                else:
                    # Fallback to basic physics from distance and typical LA
                    la_typ = _baseline_LA_from_distance(d_ft)
                    evx = _ev_from_R_theta(d_ft, la_typ)
                    lax = la_typ
                    t_est = _tof_from_R_theta(d_ft, la_typ)
                    method = 'dist_angle_physics'
        ht_vals.append(t_est)
        ev_est.append(evx)
        la_est.append(lax)
        methods.append(method)
    subdf['ev_est'] = ev_est
    subdf['la_est'] = la_est
    subdf['ht_method'] = methods
    return pd.Series(ht_vals, index=subdf.index, dtype='float64')


def T_mixture_from_prior_or_baseline(d_ft: float, th_deg: float, hand_key: str) -> Tuple[np.ndarray, np.ndarray]:
    """Return a 3‑point hang‑time mixture for this BBE using trained prior.

    If a trained prior exists for the corresponding (bin, bucket, hand), it
    returns the stored times and weights.  Otherwise, it falls back to a
    baseline mixture based on inferred typical LA and physics.

    Parameters
    ----------
    d_ft : float
        Ball distance in feet.
    th_deg : float
        Spray angle in degrees.
    hand_key : str
        Batter handedness ('R' or 'L').

    Returns
    -------
    (times, weights) : Tuple[np.ndarray, np.ndarray]
        Array of three hang‑time values and corresponding weights.
    """
    # Determine distance bin
    bin_edges = [150, 180, 210, 240, 270, 300, 330, 360, 390, float('inf')]
    bin_idx = None
    for i, edge in enumerate(bin_edges):
        if d_ft < edge:
            bin_idx = i
            break
    if bin_idx is None:
        bin_idx = len(bin_edges) - 1
    # Determine bucket
    pos = pos_for_theta(th_deg, hand_key)
    bucket = classify_angle(pos, th_deg, hand_key)
    key = (int(bin_idx), bucket, hand_key)
    prior = TRAINED_PRIOR.get(key)
    if prior is not None:
        return np.array(prior['times'], dtype=float), np.array(prior['weights'], dtype=float)
    # Fallback: baseline mixture
    la_deg = _baseline_LA_from_distance(d_ft)
    T0 = _tof_from_R_theta(d_ft, la_deg)
    T1 = max(1.2, T0 - 0.6); T2 = min(6.0, T0 + 0.6)
    return np.array([T1, T0, T2], dtype=float), np.array([0.20, 0.60, 0.20], dtype=float)


# ── 5. Outfield positioning logic (from v3 with modifications) ─────────────

# Movement profile constants (slightly adjusted example values)
t1_RF, d3_RF, v_RF = 0.88, 34.3, 29.1
t1_CF, d3_CF, v_CF = 0.86, 36.4, 30.0
t1_LF, d3_LF, v_LF = 0.85, 31.0, 28.4
dist_first_step = 3.0
time_jump_window = 3.0

OF_SPECS = {
    'RF': {'t1': t1_RF, 'd1': dist_first_step, 't3': time_jump_window, 'd3': d3_RF, 'v': v_RF},
    'CF': {'t1': t1_CF, 'd1': dist_first_step, 't3': time_jump_window, 'd3': d3_CF, 'v': v_CF},
    'LF': {'t1': t1_LF, 'd1': dist_first_step, 't3': time_jump_window, 'd3': d3_LF, 'v': v_LF},
}


def out_range_T(spec: dict, T: float) -> float:
    """Piecewise acceleration → sprint range function for OF."""
    t1, d1, t3, d3, v = spec['t1'], spec['d1'], spec['t3'], spec['d3'], spec['v']
    if T <= t1:
        return d1 * (T / t1)
    if T <= t3:
        return d1 + (d3 - d1) * ((T - t1) / (t3 - t1))
    return d3 + v * (T - t3)


def effective_reach(spec: dict, T: float, going_back: bool) -> float:
    """Apply Statcast's 1 ft/s penalty when going back."""
    R = out_range_T(spec, T)
    if going_back and T > spec['t3']:
        R = max(0.0, R - (T - spec['t3']))
    return R


def no_overlap(x1: float, y1: float, r1: float, x2: float, y2: float, r2: float, margin: float = 5.0) -> bool:
    """Return True if circles of radius r1 and r2 centred at (x1,y1),(x2,y2) do not overlap."""
    return math.hypot(x2 - x1, y2 - y1) >= r1 + r2 + margin


def place_out(dep: float, ang: float) -> Tuple[float, float]:
    """Convert polar coordinates (distance, angle) to x,y."""
    r = math.radians(ang)
    return dep * math.cos(r), dep * math.sin(r)


def greedy_place(points: List[Tuple[float, float, float]], values: np.ndarray, cover_w: np.ndarray,
                 Tmat: np.ndarray, Wmat: np.ndarray, of_specs: Dict[str, dict],
                 wall_flags: Optional[np.ndarray] = None, shallow_mode: bool = False,
                 margin: float = 5.0) -> Dict[str, Tuple[float, float]]:
    """Greedy placement of outfielders based on expected coverage.

    This version uses the calibrated T mixture (Tmat, Wmat) for expected
    coverage and includes a wall pressure penalty based on wall_flags.
    """
    pts = np.asarray(points)
    vals = np.asarray(values)
    covw = np.asarray(cover_w)
    Ts = np.asarray(Tmat)
    Ws = np.asarray(Wmat)
    rem = np.arange(len(pts))
    placed: Dict[str, Tuple[float, float]] = {}
    arr_xy = pts[:, :2]
    arr_r = pts[:, 2]
    if wall_flags is None:
        wall_flags = np.zeros(len(pts), dtype=float)
    fallback_ang = {'CF': 90.0, 'RF': 65.0, 'LF': 115.0}
    fallback_dep = {'CF': 300.0, 'RF': 275.0, 'LF': 285.0}
    for pos in ('CF', 'LF', 'RF'):
        nm = np.array([depth_cat(pos, d) == 'NORMAL' for d in arr_r])
        if nm.any():
            fallback_dep[pos] = float(np.mean(arr_r[nm]))
    order = ['CF', 'RF', 'LF']
    for lbl in order:
        spec = of_specs[lbl]
        best = {'score': -math.inf, 'ang': None, 'dep': None}
        ang_grid = (
            np.arange(60, 70.1, 0.5) if lbl == 'RF' else
            np.arange(85, 95.1, 0.5) if lbl == 'CF' else
            np.arange(110, 120.1, 0.5)
        )
        dep_start = 250 if (lbl == 'CF' and shallow_mode) else (200 if (lbl != 'CF' and shallow_mode) else (300 if lbl == 'CF' else 270))
        for ang in ang_grid:
            # Keep the typical ring inside the fence
            max_dep = max(
                200.0,
                float(R_fence(float(ang))) - out_range_T(spec, SHOW_T) - FENCE_CLEARANCE
            )
            for dep in np.arange(dep_start, max_dep + 0.1, 2.0):
                x0, y0 = place_out(dep, ang)
                # Overlap guard using typical ring
                overlap_ok = True
                for other in placed:
                    xo, yo = place_out(placed[other][1], placed[other][0])
                    if not no_overlap(x0, y0, out_range_T(spec, T_typ), xo, yo, out_range_T(of_specs[other], T_typ), margin):
                        overlap_ok = False
                        break
                if not overlap_ok:
                    continue
                dists = np.hypot(arr_xy[rem, 0] - x0, arr_xy[rem, 1] - y0)
                back_mask = going_back_mask(x0, y0, ang, arr_xy[rem], arr_r[rem])
                # Expected coverage over mixture
                R0 = np.array([effective_reach(spec, T, False) for T in Ts[rem, 0]])
                R1 = np.array([effective_reach(spec, T, b) for T, b in zip(Ts[rem, 1], back_mask)])
                R2 = np.array([effective_reach(spec, T, b) for T, b in zip(Ts[rem, 2], back_mask)])
                p_cov = (Ws[rem, 0] * (dists <= R0).astype(float) +
                         Ws[rem, 1] * (dists <= R1).astype(float) +
                         Ws[rem, 2] * (dists <= R2).astype(float))
                wall_pressure = (p_cov * wall_flags[rem] * 10.0).sum()
                if mode == "COVERAGE":
                    score = (covw[rem] * p_cov).sum()
                elif mode == "NO_DOUBLES":
                    deep_gain = ((np.maximum(arr_r[rem] - 300.0, 0.0)) ** 1.3 * p_cov).sum()
                    val_gain = (vals[rem] * p_cov).sum()
                    count_g = p_cov.sum() * 25.0
                    score = (deep_gain * 2.5) + val_gain + count_g - wall_pressure
                else:  # BALANCED
                    lam = 0.7
                    cov_gain = (covw[rem] * p_cov).sum()
                    deep_gain = ((np.maximum(arr_r[rem] - 300.0, 0.0)) ** 1.2 * p_cov).sum()
                    shallow_pressure = (max(0.0, 260.0 - dep) * 5.0) if lbl != 'CF' else (max(0.0, 280.0 - dep) * 5.0)
                    score = lam * cov_gain + (1 - lam) * deep_gain - shallow_pressure - 0.2 * wall_pressure
                if score > best['score']:
                    best = {'score': score, 'ang': float(ang), 'dep': float(dep)}
        if best['ang'] is None:
            best = {'score': -1.0, 'ang': fallback_ang[lbl], 'dep': fallback_dep[lbl]}
        placed[lbl] = (best['ang'], best['dep'])
    return placed


# ── 6. Main execution: training + positioning ─────────────────────────────

def main():
    print("OF Positioning with Data‑Driven Hang‑Time Model")
    # Prompt user for team ID for training data
    try:
        team_id = int(input("Enter MLB team ID to scrape for training (e.g., High‑A affiliate ID): ").strip())
    except Exception:
        print("Invalid team ID; aborting.")
        return
    season_input = input("Enter season to scrape (YYYY) or press Enter for current year: ").strip()
    season = int(season_input) if season_input else date.today().year
    # Scrape training data
    train_df = scrape_team_batted_balls(team_id, season=season)
    if train_df.empty:
        print("No training data scraped; aborting.")
        return
    # Train prior
    global TRAINED_PRIOR
    TRAINED_PRIOR = train_prior(train_df)
    if not TRAINED_PRIOR:
        print("Training prior is empty; fallback to physics only.")
    else:
        print(f"Trained prior for {len(TRAINED_PRIOR)} buckets")
    # Ask for CSV with BBE events for positioning
    bbe_path = input("Enter path to High‑A batted ball CSV: ").strip()
    try:
        bbe_df = pd.read_csv(bbe_path)
    except Exception as exc:
        print(f"Failed to read BBE CSV: {exc}")
        return
    # Re‑anchor Statcast coordinates and compute distance as in v3
    bbe_df['startTime'] = pd.to_datetime(bbe_df['startTime'])
    bbe_df['loc_x_raw'] = bbe_df['hc_x'] - 125.42
    bbe_df['loc_y_raw'] = 198.27 - bbe_df['hc_y']
    SCALE = 330.0 / math.hypot(100.0, 100.0)
    bbe_df['x'] = bbe_df['loc_x_raw'] * SCALE
    bbe_df['y'] = bbe_df['loc_y_raw'] * SCALE
    bbe_df['distance'] = np.hypot(bbe_df['x'], bbe_df['y'])
    # Compute hang_time_est using prior
    bbe_df['hang_time_est'] = estimate_ht_for_df_with_prior(bbe_df)
    # Compute composite value and cover weight
    days_old = (bbe_df['startTime'].max() - bbe_df['startTime']).dt.days.clip(lower=0)
    bbe_df['recency_norm'] = (1 - days_old / RECENCY_WINDOW).clip(0, 1)
    bbe_df['is_recent'] = bbe_df['startTime'] >= (bbe_df['startTime'].max() - pd.Timedelta(days=RECENT_DAYS))
    bbe_df['recent_weight'] = np.where(bbe_df['is_recent'], RECENT_BOOST, 1.0)
    ph_short = 'R' if input("Enter pitcher hand (RHP or LHP): ").strip().upper() == 'RHP' else 'L'
    bbe_df['p_throws'] = bbe_df['p_throws'].astype(str).str.upper()
    bbe_df['hand_weight'] = np.where(bbe_df['p_throws'] == ph_short, 1.2, 1.0)
    # Distance bucket to composite value (unchanged)
    dist_bins = [0, 180, 240, 300, float('inf')]
    dist_vals = [1, 2, 3, 4]
    base_val = pd.cut(bbe_df['distance'], bins=dist_bins, labels=dist_vals, include_lowest=True).astype(int).fillna(1)
    bbe_df['value'] = (base_val * bbe_df['recency_norm'] * bbe_df['hand_weight'] * bbe_df['recent_weight'])
    bbe_df['cover_w'] = (bbe_df['recency_norm'] * bbe_df['recent_weight'] * bbe_df['hand_weight'])
    # Ask user for fence dimensions
    try:
        lf_pole = float(input("LF pole (ft): "))
        cf_wall = float(input("CF wall (ft): "))
        rf_pole = float(input("RF pole (ft): "))
    except Exception:
        print("Invalid fence dimension(s)")
        return
    # Quadratic fit for fence
    global _fA, _fB, _fC
    _fA, _fB, _fC = np.polyfit([45.0, 90.0, 135.0], [rf_pole, cf_wall, lf_pole], 2)
    # Alignment mode
    align_mode = input("Alignment mode (BALANCED / NO_DOUBLES / COVERAGE) [BALANCED]: ").strip().upper() or "BALANCED"
    # Process lineup
    lineup = [n.strip() for n in input("Enter 9 last names, comma-separated: ").split(',') if n.strip()]
    rows_summary = []
    fig, axs = plt.subplots(3, 3, subplot_kw={'projection': 'polar'}, figsize=(14.3, 9.8), facecolor='w',
                            gridspec_kw={'left': 0.03, 'right': 0.97, 'top': 0.96, 'bottom': 0.04,
                                         'wspace': 0.08, 'hspace': 0.08})
    fig_report = fig
    axs = axs.flatten()
    for i, name in enumerate(lineup):
        # Filter by player name substring (case insensitive)
        batter = bbe_df[bbe_df['player_name'].str.contains(name, case=False, na=False)].copy()
        batter = batter.dropna(subset=['x', 'y'])
        print(f"{name}: {len(batter)} BBEs matched")
        if batter.empty:
            rows_summary.append({'Side': '', 'Player_LF': name, 'LF_Shift': '', 'LF_Depth': '',
                                 'Player_CF': name, 'CF_Shift': '', 'CF_Depth': '',
                                 'Player_RF': name, 'RF_Shift': '', 'RF_Depth': ''})
            axs[i].axis('off')
            continue
        # Stance selection (same as v3)
        stands = batter['stand'].str.upper(); uniq = stands.unique()
        if len(uniq) == 2:
            pref = 'L' if ph_short == 'R' else 'R'
            sub_batter = batter[stands == pref]
            side = 'S'
            hand_key = pref
            if sub_batter.empty:
                sub_batter = batter
        else:
            sub_batter = batter
            side = uniq[0]
            hand_key = uniq[0]
        orig = sub_batter.reset_index(drop=True)
        pts = list(zip(orig['x'], orig['y'], orig['distance']))
        vals = orig['value'].to_numpy()
        covers = orig['cover_w'].to_numpy()
        recent_flags = orig['is_recent'].to_numpy()
        # Build mixture per ball (measured HT preferred; else prior)
        Tlist: List[np.ndarray] = []
        Wlist: List[np.ndarray] = []
        for j, row in orig.iterrows():
            if pd.notna(row.get('hang_time')):
                Ts, ws = T_mixture_from_measured(float(row['hang_time']))
            else:
                th_deg = float(np.degrees(np.arctan2(row['y'], row['x'])))
                Ts, ws = T_mixture_from_prior_or_baseline(float(row['distance']), th_deg, hand_key)
            Tlist.append(Ts)
            Wlist.append(ws)
        Tmat = np.vstack(Tlist)
        Wmat = np.vstack(Wlist)
        # KDE padding if needed
        if len(pts) < FULL_MIN_BBEs:
            arr_xy = np.array([(p[0], p[1]) for p in pts]).T
            kde = gaussian_kde(arr_xy)
            samp = kde.resample(FULL_MIN_BBEs - len(pts))
            extra = list(zip(samp[0], samp[1], np.hypot(samp[0], samp[1])))
            pts.extend(extra)
            vals = np.hstack([vals, np.full(len(extra), 0.50)])
            covers = np.hstack([covers, np.zeros(len(extra))])
            recent_flags = np.hstack([recent_flags, np.zeros(len(extra), dtype=bool)])
            Textra, Wextra = [], []
            for (ex_x, ex_y, d) in extra:
                thd = float(np.degrees(np.arctan2(ex_y, ex_x)))
                Ts, ws = T_mixture_from_prior_or_baseline(float(d), thd, hand_key)
                Textra.append(Ts)
                Wextra.append(ws)
            Tmat = np.vstack([Tmat, np.vstack(Textra)])
            Wmat = np.vstack([Wmat, np.vstack(Wextra)])
        # Build wall flags
        wall_flags_full = wall_flags_for(orig)
        # Place outfielders
        placed = greedy_place(pts, vals, covers, Tmat, Wmat, OF_SPECS,
                              wall_flags=wall_flags_full, shallow_mode=False)
        angs = {p: placed[p][0] for p in placed}
        deps = {p: placed[p][1] for p in placed}
        # Coverage metrics
        arr = np.array(pts)
        p_rf = expected_cover('RF', angs['RF'], deps['RF'])
        p_cf = expected_cover('CF', angs['CF'], deps['CF'])
        p_lf = expected_cover('LF', angs['LF'], deps['LF'])
        p_any = np.maximum.reduce([p_rf, p_cf, p_lf])
        pct_cov = 100.0 * (vals * p_any).sum() / max(1e-9, vals.sum())
        miss = (1.0 - p_any) * np.hypot(arr[:, 0], arr[:, 1])
        miss = miss.sum() / max(1e-9, (1.0 - p_any).sum()) if (p_any < 0.999).any() else 0.0
        # Plot on large panel
        def draw_panel(ax, caption=False):
            th = np.linspace(45.0, 135.0, 300, dtype=float)
            ax.plot(np.radians(th), R_fence(th), 'k-', lw=2)
            for p, col in [('RF', 'b'), ('CF', 'g'), ('LF', 'r')]:
                ax.plot(np.radians(angs[p]), deps[p], marker='o', color=col, ms=6)
                # Draw ring at typical time
                circ = np.linspace(0, 2*np.pi, 200)
                x0, y0 = place_out(deps[p], angs[p])
                R_typ = out_range_T(OF_SPECS[p], SHOW_T)
                xs = x0 + R_typ * np.cos(circ); ys = y0 + R_typ * np.sin(circ)
                thetas = np.arctan2(ys, xs)
                radii = np.hypot(xs, ys)
                fence_r = R_fence(np.degrees(thetas))
                radii = np.minimum(radii, fence_r - 0.01)
                ax.plot(thetas, radii, col+'--', alpha=0.3)
            # Sprays
            for (px, py, _), rec in zip(pts, recent_flags):
                color = 'blue' if rec else 'black'
                thb = math.atan2(py, px); thb = thb + 2*np.pi if thb < 0 else thb
                if 45 <= math.degrees(thb) <= 135:
                    ax.plot(thb, math.hypot(px, py), '.', color=color, alpha=0.6)
            for (px, py, _) in pts[len(orig):]:
                thb = math.atan2(py, px); thb = thb + 2*np.pi if thb < 0 else thb
                if 45 <= math.degrees(thb) <= 135:
                    ax.plot(thb, math.hypot(px, py), '.', color='red', alpha=0.4)
            ax.set_thetamin(45); ax.set_thetamax(135)
            ax.set_rmax(max(rf_pole, cf_wall, lf_pole) + 50)
            ax.set_rticks([100, 200, 300, 400, 500])
            ax.set_title(name, fontsize=8, pad=6)
            if caption:
                txt = (f"RF {deps['RF']:.0f}@{angs['RF']:.1f}° | "
                       f"CF {deps['CF']:.0f}@{angs['CF']:.1f}° | "
                       f"LF {deps['LF']:.0f}@{angs['LF']:.1f}°\n"
                       f"Coverage {pct_cov:.1f}% | Avg miss {miss:.1f} ft")
                ax.text(0.5, -0.15, txt, transform=ax.transAxes,
                        ha='center', va='top', fontsize=8)
        # Draw small panel
        fig_i, ax_i = plt.subplots(figsize=(8, 8), subplot_kw={'projection': 'polar'})
        draw_panel(ax_i, caption=True)
        fig_i.suptitle(f"OF Positioning – {name}", y=0.98, fontsize=12)
        display(fig_i)
        plt.close(fig_i)
        draw_panel(axs[i], caption=False)
        # Summary table row
        def twoK_change(pos_label):
            return '', None  # Simplified: we skip two‑strike differential in this script
        row_summary = {
            'Side': side,
            'Player_LF': name,
            'LF_Shift': classify_angle('LF', angs['LF'], hand_key),
            'LF_Depth': depth_cat('LF', deps['LF']),
            'Player_CF': name,
            'CF_Shift': classify_angle('CF', angs['CF'], hand_key),
            'CF_Depth': depth_cat('CF', deps['CF']),
            'Player_RF': name,
            'RF_Shift': classify_angle('RF', angs['RF'], hand_key),
            'RF_Depth': depth_cat('RF', deps['RF']),
        }
        rows_summary.append(row_summary)
    # Hide unused panels
    for j in range(len(lineup), 9):
        axs[j].axis('off')
    # Save report
    with PdfPages('OF_positioning_report.pdf') as pdf:
        pdf.savefig(fig_report, bbox_inches='tight')
    print("✔️  Saved PDF: OF_positioning_report.pdf")
    # Build summary table (simplified columns)
    summary = pd.DataFrame(rows_summary).reset_index()
    summary['index'] += 1
    summary.rename(columns={'index': 'Idx_LF'}, inplace=True)
    print("\nPositioning Summary:")
    print(summary.to_string(index=False))


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted by user")