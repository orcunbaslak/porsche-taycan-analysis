<p align="center">
  <img src="2025-porsche-taycan.webp" alt="Porsche Taycan" width="600"/>
</p>

<h1 align="center">Porsche Taycan Market Analysis</h1>

<p align="center">
  <strong>Scrape, filter, trend, score, and compare Porsche Taycan listings on sahibinden.com</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11+-blue?style=flat-square&logo=python&logoColor=white" alt="Python"/>
  <img src="https://img.shields.io/badge/playwright-automation-2EAD33?style=flat-square&logo=playwright&logoColor=white" alt="Playwright"/>
  <img src="https://img.shields.io/badge/jupyter-notebook-F37626?style=flat-square&logo=jupyter&logoColor=white" alt="Jupyter"/>
  <img src="https://img.shields.io/badge/plotly-interactive%20charts-3F4F75?style=flat-square&logo=plotly&logoColor=white" alt="Plotly"/>
  <img src="https://img.shields.io/badge/sqlite-database-003B57?style=flat-square&logo=sqlite&logoColor=white" alt="SQLite"/>
</p>

---

## What is this?

A complete pipeline for finding strong used Porsche Taycan candidates in Turkey. It scrapes Taycan listings from [sahibinden.com](https://www.sahibinden.com), stores every scrape run in SQLite, and runs a Jupyter notebook analysis that filters high-risk cars, tracks historical asking-price movement, scores current listings, and surfaces the top picks.

**The problem it solves:** The Turkish used car market is noisy. Gallery listings can obscure damage histories, cheap cars can have accident baggage, and ad titles are inconsistent. This tool gives you a structured market view: current candidates, segment price trends across scrape runs, condition/provenance risk flags, and a shortlist to inspect manually.

## Important interpretation rules

- A listing that disappears is **not confirmed sold**. It may have sold, expired, been withdrawn, been relisted under another ID, or been missed by a partial scrape. The notebook calls these rows "No Longer Listed" and treats them as an availability signal only.
- Prices are **asking prices in nominal TL**, not transaction prices. Historical charts show seller expectations, not final sale prices.
- Feature counts are a soft signal. Some listings parse with zero features, which often means unknown equipment rather than a poorly optioned car.
- The value score is a shortlist tool. Final decisions still need Porsche service records, warranty/battery confirmation, Tramer/bodywork checks, tire/brake review, and an inspection.

## How the scoring works

The notebook applies a **three-stage pipeline**:

### Stage 1 — Disqualification

Cars are hard-filtered out by default if they have:
- **Heavy damage record** (Agir Hasar Kaydi: Evet)
- **3+ changed body parts** (structural damage on a Porsche is a dealbreaker)

Newer cars with changed parts are handled more carefully:
- **2023+ with changed parts** is kept visible by default, but flagged as high scrutiny and penalized in scoring.
- Set `DISQUALIFY_NEW_CAR_CHANGED = True` in the notebook if you want the older ultra-conservative behavior that hard-rejects these cars.

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

## Historical price trends

The notebook now includes a historical trend section that reads all usable scrape runs from `taycan.db`. It charts median asking price by model/year segment, for example `2023 GTS`, across scrape dates. It intentionally ignores the current `is_active` flag for historical snapshots, because old rows can be marked inactive later even though they were present during their original scrape.

Default historical filters:
- Uses completed or interrupted runs with at least 200 detailed non-Cross-Turismo listings
- Excludes Station Wagon / Cross Turismo body types
- Applies the same hard damage filters as the current candidate pool
- Requires each model/year segment to appear in at least 3 usable runs

## Final output

A unified **Top 15 Candidates** table where each car has auto-generated reasoning (e.g. "Flagship Turbo S at 18% below market median · Barely driven · Zero damage + dealer origin") and buyer-profile tags:

| Tag | Criteria | Who it's for |
|---|---|---|
| **SAFE** | Clean + 2023+ + <=15k km/yr | Buyers who want zero risk |
| **VALUE** | No high-km risk + no newer changed-part flag + <=1 changed part | Buyers who want the best deal |

Plus a ready-to-paste **AI prompt** with the same 15 cars including their reasoning and tags, so you can get a second opinion from Claude, ChatGPT, or any LLM.

---

## Project Structure

```
taycan-analysis/
├── scraper/
│   ├── browser.py           # Playwright browser setup (Chrome profile)
│   ├── list_scraper.py      # Search results page scraper
│   ├── detail_scraper.py    # Individual listing detail scraper
│   ├── parsers.py           # HTML parsing logic
│   └── config.py            # URLs, selectors, constants
├── db/
│   ├── schema.sql           # SQLite schema (listings, damage_parts, features)
│   └── database.py          # Database helpers
├── analysis.ipynb            # Main analysis notebook (14 sections)
├── run_scraper.py            # CLI entry point
├── requirements.txt
└── README.md
```

## Quick Start

### 1. Setup

```bash
git clone https://github.com/orcunbaslak/porsche-taycan-analysis.git && cd porsche-taycan-analysis
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

### 2. Scrape

```bash
# Full scrape (list pages + detail pages)
python run_scraper.py

# Full scan without early stop; required for reliable inactive/delisting marking
python run_scraper.py --full

# List pages only (quick, ~2 min)
python run_scraper.py --list-only

# Resume detail scraping for listings that failed
python run_scraper.py --resume
```

> The scraper uses your local Chrome profile for session cookies to avoid detection. Make sure Chrome is **closed** before running.

### 3. Analyze

```bash
jupyter notebook analysis.ipynb
```

Run all cells top-to-bottom. The notebook has 14 sections:

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

## Tech Stack

- **[Playwright](https://playwright.dev/)** — Browser automation with real Chrome profile
- **[BeautifulSoup](https://www.crummy.com/software/BeautifulSoup/)** — HTML parsing
- **[pandas](https://pandas.pydata.org/)** — Data manipulation
- **[Plotly](https://plotly.com/python/)** — Interactive charts
- **[Jupyter](https://jupyter.org/)** — Notebook interface
- **[SQLite](https://sqlite.org/)** — Local database (zero config)

## Notes

- The database file (`taycan.db`) is included in the repo with sample data
- Designed for macOS — use `gtimeout` instead of `timeout` in shell commands
- The scraper respects sahibinden.com's rate limits with built-in delays
- Cross Turismo (station wagon) variants are excluded from analysis
- Use `python run_scraper.py --full` periodically if you want the inactive/no-longer-listed signal to be meaningful
- Historical trend charts are nominal TL asking-price trends; add FX or inflation adjustment separately if needed

---

<p align="center">
  <sub>Built for personal car shopping. Not affiliated with Porsche or sahibinden.com.</sub>
</p>
