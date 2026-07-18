<p align="center">
  <img src="2025-porsche-taycan.webp" alt="Porsche Taycan" width="600"/>
</p>

<h1 align="center">Porsche Taycan Market Analysis</h1>

<p align="center">
  <strong>Scrape, filter, trend, score, value, and compare Porsche Taycan listings on sahibinden.com</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11+-blue?style=flat-square&logo=python&logoColor=white" alt="Python"/>
  <img src="https://img.shields.io/badge/rebrowser--playwright-automation-2EAD33?style=flat-square&logo=playwright&logoColor=white" alt="rebrowser-playwright"/>
  <img src="https://img.shields.io/badge/jupyter-notebook-F37626?style=flat-square&logo=jupyter&logoColor=white" alt="Jupyter"/>
  <img src="https://img.shields.io/badge/plotly-interactive%20charts-3F4F75?style=flat-square&logo=plotly&logoColor=white" alt="Plotly"/>
  <img src="https://img.shields.io/badge/sqlite-database-003B57?style=flat-square&logo=sqlite&logoColor=white" alt="SQLite"/>
  <img src="https://img.shields.io/badge/google%20sheets-cockpit-34A853?style=flat-square&logo=googlesheets&logoColor=white" alt="Google Sheets"/>
</p>

---

## What is this?

A complete pipeline for finding strong used Porsche Taycan candidates in Turkey. It scrapes Taycan listings from [sahibinden.com](https://www.sahibinden.com), stores every scrape run in SQLite, and analyzes the history three ways:

1. **Jupyter notebook** (`analysis.ipynb`, 16 sections) — filters high-risk cars, tracks asking-price movement, scores listings, fits a hedonic fair-value model, and surfaces top picks.
2. **Bargain signal** (`scraper/signals.py`) — detects motivated sellers from listing bumps and price cuts across runs, no detail pages needed.
3. **Google Sheets cockpit** (`sync_all_cars_sheet.py`) — one row per car ever seen, with ranks, scores, fair-value/offer columns, and manual-note columns that survive refreshes.

**The problem it solves:** The Turkish used car market is noisy. Gallery listings can obscure damage histories, cheap cars can have accident baggage, and ad titles are inconsistent. This tool gives you a structured market view: current candidates, segment price trends across scrape runs, seller-motivation signals, a model-based fair price and offer band for every car, and a shortlist to inspect manually.

## Important interpretation rules

- A listing that disappears is **not confirmed sold**. It may have sold, expired, been withdrawn, been relisted under another ID, or been removed by a search-filter change. The notebook calls these rows "No Longer Listed" and treats them as an availability signal only.
- Prices are **asking prices in nominal TL**, not transaction prices. Historical charts show seller expectations, not final sale prices.
- The date sahibinden displays is a **bump date, not a creation date** — roughly two-thirds of cars get re-bumped. It is useless for "how fresh is this ad?" but great as a seller-motivation signal (see below).
- Feature counts are a soft signal. Some listings parse with zero features, which often means unknown equipment rather than a poorly optioned car.
- The value score and fair-value model are shortlist tools. Final decisions still need Porsche service records, warranty/battery confirmation, Tramer/bodywork checks, tire/brake review, and an inspection.

## How the scoring works

The notebook applies a **three-stage pipeline**:

### Stage 1 — Disqualification

Cars are hard-filtered out by default if they have:
- **Heavy damage record** (Agir Hasar Kaydi: Evet) — these are now also excluded *at the search source*, so new scans never even see them; historical rows are filtered via the `v_buyable` SQL view
- **3+ changed body parts** (structural damage on a Porsche is a dealbreaker)

Newer cars with changed parts are handled more carefully:
- **2023+ with changed parts** is kept visible by default, but flagged as high scrutiny and penalized in scoring.
- Set `DISQUALIFY_NEW_CAR_CHANGED = True` if you want the older ultra-conservative behavior that hard-rejects these cars.

### Stage 2 — Derived Metrics

For every surviving listing, the notebook computes:

| Metric | What it tells you |
|---|---|
| `km_per_year` | Usage intensity (15k/yr is average, 30k+ is a red flag) |
| `damage_severity` | Normalized 0-1 scale combining changed, painted, and local-painted parts |
| `is_clean` | True if zero bodywork of any kind (hatasiz) |
| `is_bayi` | True if listing mentions authorized dealer origin (Dogus, bayi) |
| `battery` | Inferred Performance Battery vs Performance Battery Plus capacity |
| Risk flags | High km/year, 2023+ changed-part risk, many painted panels, gallery with unknown damage record |

### Stage 3 — Value Score (0-100)

A weighted composite of five factors:

```
Price competitiveness (25%)  — z-score within model/year group
Mileage for age (20%)        — actual vs expected km
Damage severity (20%)        — fewer damaged panels = higher score
Feature count (10%)          — equipment level relative to market
Depreciation resistance (25%) — 2024+ facelift >> pre-facelift
```

Then the notebook applies final adjustments:
- **Trim multiplier** — GTS (x1.10), Turbo S (x1.08), Turbo (x1.05), 4S (x1.00), base (x0.95)
- **Hatasiz bonus** — +5 points for zero bodywork
- **Bayi bonus** — +3 points for authorized dealer origin
- **Newer changed-part penalty** — -7 points for 2023+ cars with changed body parts

## Bargain signal (motivated sellers)

Because the displayed listing date is a bump date, a car that keeps getting re-bumped — especially with price cuts along the way — is a motivated seller with bargaining room. Every scrape run rebuilds the `listing_signals` table from the full price/bump history:

- **bump_count** — how many times the ad was refreshed
- **days_on_market** — first-seen to last-seen span
- **price_drop_pct / num_price_cuts** — total asking-price retreat across runs (real cars have dropped 1.9M-3.2M TL over months)
- **motivation_score (0-100)** — weighted composite; weights and caps live in `scraper/config.py`

The signal is **fully list-based** — a cheap `--list-only` run refreshes it completely. The scraper prints the top candidates after every run; notebook **Section 15** has the ranked report, signal charts, and per-car price timelines.

## Fair value & offer engine

`valuation.py` (mirrored in notebook **Section 16**) fits a hedonic regression — log(price) on trim, registration year, km with age-bucketed slopes, painted panels, changed-part class, declared Tramer, and body type — over the buyable universe, then derives per car:

- **fair_ask** — what the car *should* be listed at, and **bargain_pct** (under/over fair ask)
- **open / settle** — a suggested offer band, driven by the motivation signal and capped by fair value
- **What-if columns** — TL impact of one more painted panel, a changed panel, +10k km, or +1 year of age
- **Sanity flags** — `trim_suspect` (hp/traction contradicts the claimed trim, i.e. mislabeled ad), `tramer_tl` (Tramer amount confessed in the free-text description), `verify_first` (bargain too good to be true until proven otherwise)

These columns flow into both the notebook and the Google Sheet.

## Historical price trends

The notebook includes a historical trend section that reads all usable scrape runs from `taycan.db`. It charts median asking price by model/year segment, for example `2023 GTS`, across scrape dates. It intentionally ignores the current `is_active` flag for historical snapshots, because old rows can be marked inactive later even though they were present during their original scrape.

## Final output

A unified **Top 15 Candidates** table where each car has auto-generated reasoning (e.g. "Flagship Turbo S at 18% below market median · Barely driven · Zero damage + dealer origin") and buyer-profile tags:

| Tag | Criteria | Who it's for |
|---|---|---|
| **SAFE** | Clean + 2023+ + <=15k km/yr | Buyers who want zero risk |
| **VALUE** | No high-km risk + no newer changed-part flag + <=1 changed part | Buyers who want the best deal |

Plus a ready-to-paste **AI prompt** with the same 15 cars including their reasoning and tags, and the **All Cars Google Sheet** for day-to-day shortlist management (sortable by rank, value score, motivation score, bargain %, with your own notes preserved across syncs).

---

## Project Structure

```
taycan-analysis/
├── scraper/
│   ├── browser.py           # Connects to your running Chrome via CDP; stealth JS; PX sensor arm/disarm
│   ├── list_scraper.py      # Search results scraper (always a full sweep)
│   ├── detail_scraper.py    # Detail scraper + PerimeterX-aware click-through backlog drain
│   ├── navigate.py          # safe_goto, block-page detection (BlockedError), trusted listing clicks
│   ├── human_behavior.py    # Bezier mouse movement, scroll and dwell simulation
│   ├── signals.py           # Bargain signal: bumps, price drops, motivation score
│   ├── parsers.py           # HTML parsing logic
│   └── config.py            # URLs, selectors, pacing, PX sensor patterns
├── db/
│   ├── schema.sql           # SQLite schema (listings, damage_parts, features, listing_signals, v_buyable)
│   └── database.py          # Database helpers
├── tests/                   # pytest suite (signals, block detection, detail backlog, PX navigation)
├── analysis.ipynb           # Main analysis notebook (16 sections)
├── run_scraper.py           # CLI entry point (flags below)
├── valuation.py             # Hedonic fair-value model + offer engine (shared with Section 16)
├── sync_all_cars_sheet.py   # Google Sheets "All Cars" cockpit sync (+ local CSV export)
├── start_chrome.sh          # Launch Chrome with remote debugging for the scraper
├── setup.sh                 # Install dependencies + patch the driver
├── patch_driver.sh          # Rename __pw/__playwright globals in the rebrowser driver
├── notebook.sh              # Activate the venv and open the notebook
├── taycan.db                # SQLite database (tracked in git, with real data)
└── README.md
```

## Quick Start

### 1. Setup

```bash
git clone https://github.com/orcunbaslak/porsche-taycan-analysis.git && cd porsche-taycan-analysis
python -m venv .venv && source .venv/bin/activate
./setup.sh                               # pip install -r requirements.txt + patch the driver
pip install -r requirements-google.txt   # optional: only needed for the Google Sheets sync
```

> `setup.sh` runs `patch_driver.sh` for you. Re-run `./patch_driver.sh` any time you reinstall or upgrade `rebrowser-playwright` — the patch renames the driver's `__playwright`/`__pw` globals that bot detectors look for.

### 2. Start Chrome

The scraper does **not** launch its own browser. It connects over CDP to a Chrome you start yourself:

```bash
./start_chrome.sh
```

This launches Chrome with remote debugging on port 9222 and a dedicated persistent profile in `~/.taycan-chrome` (quit your regular Chrome first, Cmd+Q). The first time, log into sahibinden.com in that window — the session persists across launches. Keep this Chrome open while scraping.

### 3. Scrape

```bash
python run_scraper.py                  # Full scan: all list pages + details for new cars
python run_scraper.py --list-only     # List pages only (~6 requests); fully refreshes the bargain signal
python run_scraper.py --resume        # No list sweep: drain the detail backlog via PX-aware click-through
python run_scraper.py --max-details 6 # Cap detail fetches this run (default 3); rest retried next run
python run_scraper.py --bot-check     # Verify stealth on bot-check sites (never touches sahibinden)
```

`run_scraper.py` flags:

| Flag | What it does |
|---|---|
| *(none)* | Full sweep of all search pages, mark disappeared listings inactive, copy known details, then fetch details for new cars |
| `--list-only` | Search pages only. Cheapest run; the bargain signal is fully list-based, so this is the **routine refresh** |
| `--resume` | Drains the *global* detail backlog (every active listing never detailed in any run), using the PerimeterX-aware click-through — no list sweep |
| `--max-details N` | Cap detail fetches per run (default 3; pass a large number to disable) |
| `--delay S` | Override the base delay between list requests |
| `--headless` | Headless mode |
| `--bot-check` | Open bot-detection test pages (browserscan etc.) and wait for manual inspection |

**Recommended workflow:** alternate cheap `--list-only` runs (signal refresh) and `--resume` runs (detail drain), with cool-downs in between. If sahibinden rate-limits, the run aborts cleanly with status `blocked` — let the profile/IP rest before retrying.

### 4. Analyze

```bash
./notebook.sh          # or: jupyter notebook analysis.ipynb
```

Run all cells top-to-bottom. The notebook has 16 sections:

| # | Section | What it does |
|---|---|---|
| 1 | Data Loading | Loads latest scrape run from SQLite |
| — | Date Range Filter | Interactive slider to exclude stale listings |
| 2 | Disqualification | Hard-filters heavy damage, 3+ changed parts; flags newer changed-part cars |
| 3 | Derived Metrics | Computes km/year, damage severity, battery, clean/bayi flags, risk flags |
| 4 | Price Analysis | Histograms, scatter plots, price-per-km |
| 5 | Value Score | Composite scoring with decomposed breakdown table |
| 6 | Damage Analysis | Pie/box/bar charts of body condition |
| 7 | Feature Comparison | Equipment frequency and price correlation |
| 8 | Depreciation | OLS trendlines, depreciation curves, sweet spots |
| 9 | Facelift (2024+) | Dedicated analysis for facelift models |
| 10 | Historical Price Trends | Median asking-price movement by model/year across scrape runs |
| 11 | Delisting / Availability | Active vs no-longer-listed comparison without assuming sold status |
| 12 | Top Candidates | Ranked list with auto-generated reasoning and tags |
| 13 | AI Recommendation | Copy-paste prompt for LLM second opinion |
| 14 | Interactive Browser | Sortable table + dropdown detail viewer |
| 15 | Bargain Signal | Bump counts, price-drop history, motivation score, per-car price timelines |
| 16 | Fair Value & Offer Calculator | Hedonic fair ask, bargain %, offer bands, what-if columns |

### 5. Sync the Google Sheet (optional)

```bash
python sync_all_cars_sheet.py --local-only            # write taycan_all_cars_sheet.csv only
export BW_SESSION="$(bw unlock --raw)"                # unlock Bitwarden for the service-account key
python sync_all_cars_sheet.py                         # CSV + push to the "All Cars" sheet
```

One row per `sahibinden_id` ever seen (including no-longer-listed cars), scored and ranked in-process, with valuation columns from `valuation.py` and manual columns (e.g. `my_priority`) preserved across refreshes. Spreadsheet id and credential lookup are baked in; override with `--spreadsheet-id` / `--service-account`. See `docs/google-sheet-workflow.md`.

## Anti-Detection

sahibinden.com sits behind a serious anti-bot stack (PerimeterX/HUMAN behavioral scoring, Cloudflare Bot Management, reCAPTCHA Enterprise). The scraper's approach, in layers:

- **rebrowser-playwright** instead of vanilla Playwright — fixes the CDP `Runtime.enable` leak.
- **Patched driver** (`patch_driver.sh`) — renames `__playwright`/`__pw` globals in the driver JS.
- **Your real Chrome over CDP** (`start_chrome.sh`) — real browser fingerprint, persistent logged-in session; stealth JS is injected via `Page.addScriptToEvaluateOnNewDocument`.
- **Human-shaped navigation** — detail pages are opened by *clicking the real listing anchor* on the search page (trusted click, same-origin `Sec-Fetch-Site`, proper `Referer`) instead of `page.goto`, with Bezier-curve mouse movement and human dwell times (`human_behavior.py`). The PerimeterX sensor is warmed up once to mint a healthy risk token, then blocked (`browser.disarm_px`) so it can't re-score the automated burst.
- **Block detection** — `navigate.py` recognizes the rate-limit page even when it arrives via a delayed client-side redirect, raises `BlockedError`, and the run aborts cleanly with status `blocked` instead of hammering on.
- **Data hygiene** — sahibinden honeypot decoy rows (sub-10-digit listing IDs) are dropped at ingest; heavy-damage cars are excluded at the search URL itself.

Verify the stealth setup safely anytime with `python run_scraper.py --bot-check`.

## Tech Stack

- **[rebrowser-playwright](https://github.com/rebrowser/rebrowser-playwright)** — leak-patched browser automation over your real Chrome
- **[BeautifulSoup](https://www.crummy.com/software/BeautifulSoup/)** — HTML parsing
- **[pandas](https://pandas.pydata.org/)** — Data manipulation
- **[statsmodels](https://www.statsmodels.org/)** — Hedonic fair-value regression
- **[Plotly](https://plotly.com/python/)** — Interactive charts
- **[Jupyter](https://jupyter.org/)** — Notebook interface
- **[SQLite](https://sqlite.org/)** — Local database (zero config)
- **[gspread-style Google APIs](https://developers.google.com/sheets/api)** — Sheets cockpit sync
- **[pytest](https://pytest.org/)** — Test suite (`pytest -q`)

## Notes

- The database file (`taycan.db`) is **tracked in git** with real scrape history
- Designed for macOS — use `gtimeout` instead of `timeout` in shell commands
- Heavy-damage cars are excluded at the search source; for historical rows use the `v_buyable` view (latest active row per car, heavy damage excluded, `hdr_verified=0` = never-detailed/unknown)
- Cross Turismo (station wagon) variants are excluded from analysis
- Every scan is a full list sweep, so the inactive/no-longer-listed signal is always meaningful (the old `--full` flag is retired)
- Historical trend charts are nominal TL asking-price trends; add FX or inflation adjustment separately if needed
- Scraping likely violates sahibinden.com's terms of service; this is a personal-use research project — keep volumes low and cool down between runs

---

<p align="center">
  <sub>Built for personal car shopping. Not affiliated with Porsche or sahibinden.com.</sub>
</p>
