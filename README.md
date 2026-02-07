<p align="center">
  <img src="2025-porsche-taycan.webp" alt="Porsche Taycan" width="600"/>
</p>

<h1 align="center">Porsche Taycan Market Analysis</h1>

<p align="center">
  <strong>Scrape, filter, score, and compare every Porsche Taycan listing on sahibinden.com</strong>
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

A complete pipeline for finding the best-value used Porsche Taycan in Turkey. It scrapes all active Taycan listings from [sahibinden.com](https://www.sahibinden.com), stores them in a local SQLite database, and runs a Jupyter notebook analysis that filters out junk, scores every car on multiple dimensions, and surfaces the top picks.

**The problem it solves:** The Turkish used car market is noisy. Gallery listings hide damage histories, cheap cars have unreported accidents, and ad titles are SEO spam. This tool gives you a data-driven view of the entire market in one place.

## How the scoring works

The notebook applies a **three-stage pipeline**:

### Stage 1 — Disqualification

Cars are hard-filtered out if they have:
- **Heavy damage record** (Agir Hasar Kaydi: Evet)
- **3+ changed body parts** (structural damage on a Porsche is a dealbreaker)
- **2023+ model with any changed parts** (too new to have legitimate bodywork)

### Stage 2 — Derived Metrics

For every surviving listing, the notebook computes:

| Metric | What it tells you |
|---|---|
| `km_per_year` | Usage intensity (15k/yr is average, 30k+ is a red flag) |
| `damage_severity` | Normalized 0-1 scale combining changed, painted, and local-painted parts |
| `is_clean` | True if zero bodywork of any kind (hatasiz) |
| `is_bayi` | True if listing mentions authorized dealer origin (Dogus, bayi) |
| Risk flags | High km/year, many painted panels, gallery with unknown damage record |

### Stage 3 — Value Score (0-100)

A weighted composite of five factors:

```
Price competitiveness (25%)  — z-score within model/year group
Mileage for age (20%)        — actual vs expected km
Damage severity (20%)        — fewer damaged panels = higher score
Feature count (10%)          — equipment level relative to market
Depreciation resistance (25%) — 2024+ facelift >> pre-facelift
```

Plus three bonuses:
- **Trim multiplier** — GTS (x1.10), Turbo S (x1.08), Turbo (x1.05), 4S (x1.00), base (x0.95)
- **Hatasiz bonus** — +5 points for zero bodywork
- **Bayi bonus** — +3 points for authorized dealer origin

## Final output

A unified **Top 15 Candidates** table where each car has auto-generated reasoning (e.g. "Flagship Turbo S at 18% below market median · Barely driven · Zero damage + dealer origin") and buyer-profile tags:

| Tag | Criteria | Who it's for |
|---|---|---|
| **SAFE** | Clean + 2023+ + <=15k km/yr | Buyers who want zero risk |
| **VALUE** | No high-km risk + <=1 changed part | Buyers who want the best deal |

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
├── analysis.ipynb            # Main analysis notebook (12 sections)
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

Run all cells top-to-bottom. The notebook has 12 sections:

| # | Section | What it does |
|---|---|---|
| 1 | Data Loading | Loads latest scrape run from SQLite |
| — | Date Range Filter | Interactive slider to exclude stale listings |
| 2 | Disqualification | Hard-filters heavy damage, 3+ changed parts |
| 3 | Derived Metrics | Computes km/year, damage severity, clean/bayi flags |
| 4 | Price Analysis | Histograms, scatter plots, price-per-km |
| 5 | Value Score | Composite scoring with decomposed breakdown table |
| 6 | Damage Analysis | Pie/box/bar charts of body condition |
| 7 | Feature Comparison | Equipment frequency and price correlation |
| 8 | Depreciation | OLS trendlines, depreciation curves, sweet spots |
| 9 | Facelift (2024+) | Dedicated analysis for facelift models |
| 10 | Top Candidates | Ranked list with auto-generated reasoning and tags |
| 11 | AI Recommendation | Copy-paste prompt for LLM second opinion |
| 12 | Interactive Browser | Sortable table + dropdown detail viewer |

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

---

<p align="center">
  <sub>Built for personal car shopping. Not affiliated with Porsche or sahibinden.com.</sub>
</p>
