# MiLB Pitcher Workload Research

A descriptive study of how MLB organizations manage young, valued starting pitchers during their **first full affiliated MiLB season**. Surfaces visible in-game starter usage — pitch counts, rest, low-IP outings, build-up shape, response to promotions — derived from game logs only. Rebuilds into a standalone HTML page every time new data is added.

**Inclusion criteria.** Pitchers who (1) started in April, (2) accumulated enough starts for org-level patterns to be visible, (3) were valued org assets (top draft pick, notable IFA bonus, or known top-30 prospect), and (4) were in their first full affiliated MiLB season. Survivorship bias is intentional; the study is deliberately filtered to arms whose seasons produced enough innings for management decisions to be readable.

**Limitations.** Not a measure of total throwing workload (bullpens, side work, catch play, pregame, and live BP are not in the CSVs). Not an injury prediction tool — we list known injury context for transparency, never as a target. Per-org sample sizes are small (1–3 pitchers in most cases); aggregates are reported with 90% bootstrap CIs.

Currently covers **24 pitchers across 11 organizations**, spanning 2024–2025 seasons, ages 18–23, from first full pro debuts through AAA.

Author: Marcelo Alfonsin

## Live page

Once you've pushed this repo to GitHub and enabled Pages, the site lives at:
`https://<your-username>.github.io/<repo-name>/`

The entire deliverable is `docs/index.html` — standalone, no server required, just CDN-loaded Chart.js.

---

## Headline observations (n=24)

**Highest-IP seasons that finished healthy (95+ IP, ≥80% in-band ACWR, max ≤1.4, no in-season injury flag):**
Hackenberg (ATL, 129 IP, 91% in-band, 1.17 max ACWR, 3 levels), Ford (SEA, 125 IP, 100%), Santucci (NYM, 122 IP, 96%), McLean (NYM, 110 IP), Baumann (ATL, 99 IP), White (MIA, 96 IP). All six showed consistent 6–7 day rhythm, pitch-count caps expanding in step with promotions, ACWR max under 1.4, and no unexplained mid-season gaps. Read as case studies of what unbothered usage looked like in this cohort, not as best practices.

**Age-group observation — in-band ACWR % is U-shaped across this cohort, not linear:**
- 18–19 (n=9): avg 81 IP, 82 max P, **85% in-band**, 1.33 max ACWR — tight ranges, most uniform usage
- 20–21 (n=7): avg 103 IP, 88 max P, **76% in-band**, 1.54 max ACWR — most variable middle band
- 22+ (n=8): avg 111 IP, 94 max P, **83% in-band**, 1.40 max ACWR — workhorse cohort, ratios stabilize

**Organization-level snapshot** (unweighted mean of per-pitcher in-band ACWR %; n=1–3 per org, directional only — demoted into a collapsed `<details>` block on the live site):
- **Cleanest:** NYM 93.3% (n=2) · ATL 93.0% (n=3) · CLE/WAS 87.5% (n=1)
- **Middle:** MIA 84.4 (n=2) · LAD 83.8 (n=2) · CLE 82.1 (n=2) · NYY 81.7 (n=2) · SEA 78.9 (n=3)
- **Most aggressive:** MIL 75.7 (n=3) · NYY/CHW 73.7 (n=1) · TB 68.9 (n=3)

With most orgs at n=1–2, these rankings are starting points for investigation, not team-wide trends. Only ATL, MIL, SEA, and TB clear n=3.

**Visible workload is necessary context, not sufficient evidence of injury risk:**
Extended rest gaps (>15 days) coincide with reported injuries, but that is largely because the gap IS the IL stint — it is confirmatory, not predictive. 5 of 6 pitchers with 15+ day gaps had injury issues (Meccage, Meyer, Cunningham, Hess, Nichols); White's 20-day gap was the 2024 Futures Game plus a planned skip. Of 5 pitchers with ACWR spikes above 1.5, only Nichols had an injury pattern overlapping the spike. Cijntje's three spikes landed during his low-pitch-count piggyback phase (3-start chronic baseline at 30–50P makes ACWR mathematically volatile) — they read as metric artifacts, not workload overload. Knoth's January 2025 TJ had no visible warning in his 2024 volume data; the CSV does not see bullpens, mechanics, or perceived effort.

**Short-start handling — split into two buckets:**
A "true short-workload" start = <4.0 IP AND ≥2 IP shorter than the previous start AND pitch count ≤ 80% of the previous start's pitch count. The pitch-count guard is new in this iteration: it filters out outings where IP collapsed but the workload was held — those are now reported as **inefficient low-IP outings** in their own table. After the split: 38 true-short events across 18 pitchers; 17 inefficient-low-IP events across 12 pitchers. Median next-start as % of pre-short across the true-short bucket is reported on the **Short starts** tab.

**Promotions — pre/post 3-start snapshots:**
Each level transition (Low-A → High-A, etc.) is detected from the `teamWithLevel` field. The **Promotions** tab reports pre-3 vs post-3 means for pitch count, ACWR, rest, and velocity, plus the number of post-promo starts before pitch count returned to the pre-promo mean. 21 transitions across 17 pitchers in this cohort.

**Scheduling response to performance regression — exploratory:**
Flags starts where fastball velocity dropped ≥1.0 mph below the rolling 3-start baseline OR Strike% dropped ≥5 pp, then checks whether the next rest window expanded beyond the pitcher's baseline rest. First-pass only (thin rolling baseline, uncontrolled for weather/opponent) — a lens for investigation, not a verdict. Lives in the **Short starts** tab alongside tempered-start detection.

**Sensitivity to thresholds:**
Headline metrics (in-band %, spike count, true-short count, tempered count, high-stress P/IP rate) are recomputed under three threshold variants per knob. Variants moving > ±25% from the default are flagged **threshold-sensitive** on the Methodology tab — read those headlines with extra hedging.

**Hard cap patterns cluster clearly by age and org — within small samples:**
LAD sits tightest at a ~75P ceiling (Patick, Zazueta), though both are 19-20yo so age-appropriate scaling is confounded with org philosophy (n=2, directional). SEA's caps climb across its 3-pitcher sample (Sloan 72 at 19 Low-A → Ford 89 at 20 Low-A → Cijntje 99 at 21 AA) — age and level are confounded, we can't separate them at n=3. CLE is age-calibrated in the 2-pitcher sample (Doughty 80 at 19, Messick 97 at 23). NYY's two 2024 college draftees (Cunningham, Hess) both ran 94–99P in their first pro season and both had in-season disruptions — a cohort to track in 2026, not yet a proven causal link at n=2. TB was aggressive (87–92P) across its 3 sampled 20-21yo arms. ATL's Caminiti at 93P in 18-19 is one pitcher at that age in that org — directional.

---

## Repo structure

```
pitcher-workload-research/
├── data/
│   ├── csvs/                    # TruMedia pitching KPI exports
│   ├── metadata.json            # pitcher meta (org, yr, age, draft, etc)
│   ├── injury_flags.json        # per-pitcher injury context
│   ├── weather_flags.json       # per-pitcher gap attribution (ASB, trades, rainouts)
│   ├── org_findings.json        # per-org qualitative writeups
│   └── overview_findings.json   # top-level callouts, key patterns, age analysis
├── scripts/
│   └── build.py                 # reads everything → generates docs/index.html
├── docs/
│   └── index.html               # the deliverable (~180KB, self-contained)
├── .gitignore
└── README.md
```

---

## Adding a new pitcher

Three-step loop:

**1. Drop the TruMedia CSV** in `data/csvs/`. Use the naming convention `F__Lastname_-_Pitching_KPIs.csv` (matches the TruMedia export). Example: `J__Hamm_-_Pitching_KPIs.csv`.

**2. Add an entry to `data/metadata.json`** keyed by surname:

```json
"Hamm": {
  "csv": "J__Hamm_-_Pitching_KPIs.csv",
  "org": "DET",
  "yr": 2025,
  "age": 22,
  "ageGroup": "22+",
  "team": "West Michigan→Erie",
  "level": "High-A→AA",
  "draft": "2024, 5th rd",
  "background": "college",
  "firstFullSeason": true,
  "note": "2024 Middle Tennessee draftee, first full pro season"
}
```

`background` is one of `prep | college | international | unknown` (leave as `unknown` if not unambiguous from draft string + age-at-draft). `firstFullSeason` is `true` if the season covered by the CSV qualifies as the pitcher's first full affiliated MiLB season — required for inclusion in this study's cohort.

**3. Run the build:**

```bash
python3 scripts/build.py
```

That's it. The HTML regenerates with the new pitcher included in:
- The scorecard (ACWR metrics)
- Hard cap ranking
- Organization tab (if it's an existing org — writeup prose may need updating)
- Age analysis group (counts and averages recompute automatically)
- All sub-nav lists

### Optional extras

If the pitcher had an injury, add them to `data/injury_flags.json`:

```json
"Hamm": {
  "severity": "in-season",
  "label": "Oblique — 3 weeks",
  "note": "Placed on IL 6/15/25 with oblique strain, activated 7/8/25. Data shows a 23-day gap."
}
```

If they had unexplained gaps, add to `data/weather_flags.json`:

```json
"Hamm": [
  {"date": "7/22/25", "detail": "14-day gap covering Eastern League ASB (+5d)"}
]
```

Severity tags recognized for coloring: `season-ender-TJ`, `in-season`, `nagging-undiagnosed`, `pre-season`, `late-season`, `workload-tempering`, `org-change`, `minor`, `unique-role`.

---

## Updating conclusions

When new data shifts the story, edit the qualitative JSON files:

- **`data/org_findings.json`** — per-org prose (rhythm, cap, buildup, short-start handling, injury patterns, strengths, concerns). If adding a pitcher to an existing org, check whether the narrative still holds. If adding a pitcher to a NEW org, add a new key.
- **`data/overview_findings.json`** — top-level callouts, key patterns, observed_patterns block, age analysis. This is where cross-cohort observations live. If a new pitcher breaks or confirms a pattern, rewrite here.

The quantitative sections (scorecard, hard cap rankings, age group averages, injury counts) all recompute automatically from the raw CSVs. You never hand-edit numbers.

---

## Pushing to GitHub

### One-time setup

```bash
cd /path/to/this/folder
git init
git add .
git commit -m "Initial commit: 24 pitchers, 11 orgs"

# Create an empty repo on GitHub (don't initialize with README)
# Then:
git remote add origin https://github.com/<your-username>/pitcher-workload-research.git
git branch -M main
git push -u origin main
```

### Enable GitHub Pages

1. Go to repo **Settings** → **Pages**
2. Source: **Deploy from a branch**
3. Branch: **main** / folder: **`/docs`**
4. Save. After ~30 seconds your site is live at `https://<your-username>.github.io/pitcher-workload-research/`

### Future updates

```bash
# After adding a pitcher
python3 scripts/build.py
git add data/ docs/index.html
git commit -m "Add Jaden Hamm (DET 2025)"
git push
```

GitHub Pages rebuilds automatically within a minute.

---

## Methodology

Full methodology is documented inside the deliverable under the **Methodology** tab, but the short version:

**ACWR** (Acute:Chronic Workload Ratio) — uncoupled rolling 4-start:
```
ACWR_i = P_i / mean(P_{i-3}, P_{i-2}, P_{i-1})
```
Sweet spot: 0.8–1.3 (bounds inclusive on both ends). Spike: >1.5. Valid for starts i ≥ 4; pitchers with fewer than 4 starts are excluded from sweet%/max-ACWR aggregates and the build script emits a stderr warning for them.

**Short-start definitions — split into two buckets:**
- **True short-workload start.** All three of: (1) < 4.0 IP, (2) ≥ 2 full IP shorter than the previous start, (3) cur P ≤ 80% of prev P. The pitch-count guard removes outings where IP collapsed but the pitch count was held.
- **Inefficient low-IP start.** < 4.0 IP and ≥ 2 IP shorter than previous, but cur P > 80% of prev P. Same low-IP outing, but the workload was held — a high-stress outing, not a short-workload event. Reported in its own table.

**% of previous framing:** For true-short aftermath, the NEXT start's pitch count is compared to the PRE-SHORT start. Describes whether the next outing was tempered relative to the workload the pitcher was carrying right before the short.

**Org rollups.** Unweighted mean of per-pitcher metrics across each org's sample. A pitcher with 8 starts weighs the same as a pitcher with 28 starts — a deliberate simplicity trade-off given the small per-org samples. Reported with 90% bootstrap CIs (n_iter=1000, fixed seed). Demoted into a collapsed `<details>` block on the live site — directional only at n=1–3.

**Age groups:** 18–19, 20–21, 22+. Age is as of the season covered by the CSV. Per-group numbers (avg IP, avg max P, avg in-band %, avg max ACWR) are auto-computed at build time and reported with bootstrap CIs.

**Background split.** Each pitcher carries a `background` field (prep / college / international / unknown). A small split table on the Ages tab reports per-background n, avg IP, max P, in-band %, and P/IP. n is small per background — directional only.

**Sensitivity grid.** Headline metrics are recomputed under three threshold variants per knob: ACWR sweet bounds (0.8–1.3 vs 0.7–1.4 vs 0.85–1.25), spike threshold (>1.5 vs >1.4 vs >1.6), true-short pitch ratio (≤0.80 vs ≤0.70 vs ≤0.90), tempered ratio (≤0.75 vs ≤0.70 vs ≤0.80), high-stress P/IP (≥18 vs ≥17 vs ≥19). Variants moving > ±25% from the default are flagged threshold-sensitive on the Methodology tab.

---

## Current dataset

| # | Pitcher | Org | Year | Age | Level | Draft |
|---|---|---|---|---|---|---|
| 1 | Cole Caminiti | ATL | 2025 | 19 | Rookie → Low-A | 2024, 1st (#24) |
| 2 | Drue Hackenberg | ATL | 2024 | 22 | High-A → AA → AAA | 2023, 2nd (#59) |
| 3 | Garrett Baumann | ATL | 2024 | 20 | Low-A → High-A | 2023, 4th (#123) |
| 4 | Parker Messick | CLE | 2024 | 23 | High-A → AA | 2022, 2nd (#54) |
| 5 | Braylon Doughty | CLE | 2025 | 19 | Low-A | 2024, CB-A (#36) |
| 6 | Alex Clemmey | CLE/WAS | 2024 | 19 | Low-A | 2023, 2nd (#58) |
| 7 | Ben Hess | NYY | 2025 | 22 | High-A → AA | 2024, 1st (#26) |
| 8 | Bryce Cunningham | NYY | 2025 | 22 | High-A | 2024, 2nd (#53) |
| 9 | Jonathan Santucci | NYM | 2025 | 22 | High-A → AA | 2024, 2nd (#46) |
| 10 | Nolan McLean | NYM | 2024 | 22 | High-A → AA | 2023, 3rd (#91) |
| 11 | Blake Birchard | MIL | 2025 | 22 | High-A | 2023, 5th (#155) |
| 12 | Brett Meccage | MIL | 2025 | 19 | Low-A | 2024, 2nd (#57) |
| 13 | Josh Knoth | MIL | 2024 | 18 | Low-A | 2023, CB-A (#33) |
| 14 | Ryan Sloan | SEA | 2025 | 19 | Low-A → High-A | 2024, 2nd (#55) |
| 15 | Woodrow Ford | SEA | 2025 | 20 | Low-A | 2022, 2nd (#74) |
| 16 | Jurrangelo Cijntje | SEA | 2025 | 21 | High-A → AA | 2024, 1st (#15) |
| 17 | Trevor Harrison | TB | 2025 | 20 | Low-A → High-A | 2023, 5th (#156) |
| 18 | TJ Nichols | TB | 2024 | 21 | Low-A | 2023, 6th (#183) |
| 19 | Gary Gill Hill | TB | 2024 | 21 | Low-A | 2023, 6th (#172) |
| 20 | Sean Patick | LAD | 2025 | 20 | Low-A → High-A | 2023, 18th |
| 21 | Carlos Zazueta | LAD | 2024 | 19 | Rookie → Low-A | INT'L 2022 |
| 22 | Thomas White | MIA | 2024 | 19 | Low-A → High-A | 2023, CB-A (#35) |
| 23 | Noble Meyer | MIA | 2024 | 19 | Low-A → High-A | 2023, 1st (#10) |
| 24 | Gage Ziehl | NYY/CHW | 2025 | 22 | Low-A → High-A | 2024, 4th (#119) |

---

## Suggested next additions

Organizations under-represented or missing that would strengthen the dataset:

**DET (own org — highest priority):**
- Jaden Hamm (2024, 5th rd, RHP Middle Tennessee)
- Owen Hall (2023, 2nd rd)

**HOU (not yet in dataset — tests HOU pitching dev reputation):**
- Alonzo Tredwell (2023, 2nd rd)
- Ethan Pecko (2024, 2nd rd)

**BOS (not yet in dataset):**
- Juan Valera
- Jedixson Paez

**More CLE (test the tight-leash vs workhorse thesis further):**
- Other young arms in the system

**Expand ATL, NYY, TB** — each has an interesting pattern worth more data points.

---

## License

Personal research repository. Data sourced from TruMedia Networks. Analysis and interpretation © Marcelo Alfonsin.
