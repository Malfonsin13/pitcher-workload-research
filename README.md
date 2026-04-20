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

**Organization discipline ranking** (avg ACWR sweet% across sampled pitchers):
- **Cleanest:** NYM 93.3% · ATL 93.0% · CLE/WAS 87.5%
- **Middle:** MIA 84.4 · LAD 83.8 · CLE 82.1 · NYY 81.7 · SEA 78.9
- **Most aggressive:** MIL 75.7 · NYY/CHW 73.7 · TB 68.9

**Invisible injuries remain the unsolved problem:**
Extended rest gaps (>15 days) correlate with injury more reliably than ACWR spikes. 5 of 6 pitchers with 15+ day gaps had injury issues; only 2 of 5 pitchers with ACWR spikes above 1.5 did (one of those two was a mid-season trade, not an injury). Knoth's January 2025 TJ had ZERO warning signs in his 2024 volume data — scariest case in the dataset.

**Hard cap patterns cluster clearly by age and org:**
LAD tightest at 75P ceiling. SEA scales with age (Sloan 72 → Ford 89 → Cijntje 99 at AA). CLE age-calibrated (Doughty 80 → Messick 97). NYY most aggressive at 94–99P for first-pro-season college arms — both Cunningham and Hess had injury flags. TB/ATL aggressive at the young end (Caminiti 93 at 18-19).

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
Sweet spot: 0.8–1.3. Spike: >1.5.

**Short-start definition:** Less than 4.0 IP AND at least 2 full innings shorter than the previous start. Excludes consistent short-usage patterns.

**% of previous framing:** For short-start aftermath, the NEXT start's pitch count is compared to the PRE-SHORT start. Answers: did the org plan a shorter next outing, or restart normal workload?

**Age groups:** 18–19, 20–21, 22+. Age is as of the season covered by the CSV.

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
