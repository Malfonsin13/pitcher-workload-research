# MiLB Pitcher Workload Research

Growing research database tracking young MLB organization starting pitchers across their developmental years. Tracks pitch counts, rest patterns, ACWR-based workload spikes, injury history, and build-up profiles — rebuilds into a standalone HTML page every time new data is added.

Currently covers **24 pitchers across 11 organizations**, spanning 2024–2025 seasons, ages 18–23, from first-year pro debuts through Triple-A promotions.

Author: Marcelo Alfonsin

## Live page

Once you've pushed this repo to GitHub and enabled Pages, the site lives at:
`https://<your-username>.github.io/<repo-name>/`

The entire deliverable is `docs/index.html` — standalone, no server required, just CDN-loaded Chart.js.

---

## Headline findings (n=24)

**Best-practices innings-eaters (95+ IP, clean ACWR, healthy):**
Hackenberg (ATL, 129 IP, 91% sweet, 1.17 max ACWR, 3 levels), Ford (SEA, 125 IP, 100% sweet), Santucci (NYM, 122 IP, 96% sweet), McLean (NYM, 110 IP), Baumann (ATL, 99 IP), White (MIA, 96 IP). All six: consistent 6–7 day rhythm, progressive cap expansion tied to promotions, ACWR max under 1.4, zero unexplained mid-season gaps.

**Age-group pattern — ACWR discipline is U-shaped, not linear:**
- 18–19 (n=9): avg 81 IP, 82 max P, **85% ACWR sweet**, 1.33 max ACWR — tight leash, most uniform
- 20–21 (n=7): avg 103 IP, 88 max P, **76% sweet**, 1.54 max ACWR — the messy middle
- 22+ (n=8): avg 111 IP, 94 max P, **83% sweet**, 1.40 max ACWR — workhorse zone, discipline recovers

**Organization discipline ranking** (unweighted mean of per-pitcher ACWR sweet%; n=1–3 per org, directional):
- **Cleanest:** NYM 93.3% (n=2) · ATL 93.0% (n=3) · CLE/WAS 87.5% (n=1)
- **Middle:** MIA 84.4 (n=2) · LAD 83.8 (n=2) · CLE 82.1 (n=2) · NYY 81.7 (n=2) · SEA 78.9 (n=3)
- **Most aggressive:** MIL 75.7 (n=3) · NYY/CHW 73.7 (n=1) · TB 68.9 (n=3)

With most orgs at n=1–2, these rankings are starting points for investigation, not team-wide trends. Only ATL, MIL, SEA, and TB clear n=3.

**Invisible injuries remain the unsolved problem — but "rest gap = injury signal" is mostly descriptive, not predictive:**
Extended rest gaps (>15 days) coincide with reported injuries, but that's largely because the gap IS the IL stint — it's confirmation, not a warning signal. 5 of 6 pitchers with 15+ day gaps had injury issues (Meccage, Meyer, Cunningham, Hess, Nichols); White's 20-day gap was the 2024 Futures Game plus a planned skip. Meanwhile, of 5 pitchers with ACWR spikes above 1.5, only 1 (Nichols) had an injury pattern overlapping the spike — Cijntje's spikes were a piggyback-to-rotation role change, Messick spiked twice and stayed healthy, Ziehl's came in a mid-season trade rebuild, Gill Hill had no formal injury. Knoth's January 2025 TJ had ZERO warning signs in his 2024 volume data — the scariest case in the dataset.

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
  "note": "2024 Middle Tennessee draftee, first full pro season"
}
```

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
- **`data/overview_findings.json`** — top-level callouts, key patterns, best practices, age analysis. This is where cross-org conclusions live. If a new pitcher breaks or confirms a pattern, rewrite here.

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

**Short-start definition:** Less than 4.0 IP AND at least 2 full innings shorter than the previous start. There is no explicit exclusion for consistent short-usage (openers, piggyback) — the "≥2 IP shorter than previous" guard *naturally* filters most of those cases, since a uniformly short pattern never creates a 2-IP drop against its own baseline.

**% of previous framing:** For short-start aftermath, the NEXT start's pitch count is compared to the PRE-SHORT start. Answers: did the org plan a shorter next outing, or restart normal workload?

**Org discipline ranking:** unweighted mean of per-pitcher sweet% across each org's sample. A pitcher with 8 starts weighs the same as a pitcher with 28 starts — a deliberate simplicity trade-off given the small per-org samples. Read with a sample-size qualifier: at n=1–2, the ranking is directional only.

**Age groups:** 18–19, 20–21, 22+. Age is as of the season covered by the CSV. The per-group numbers (avg IP, avg max P, avg sweet%, avg max ACWR) are auto-computed from the CSVs at build time — not hand-maintained — so they always reflect the current dataset.

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
