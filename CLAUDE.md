# Taycan Analysis

Scrapes Porsche Taycan listings from sahibinden.com and analyzes them in a Jupyter notebook.

## Structure
- `scraper/` — Playwright-based scraper (browser.py, list_scraper.py, detail_scraper.py, parsers.py, config.py)
- `db/` — SQLite schema and helpers (schema.sql, database.py)
- `run_scraper.py` — CLI entry point
- `analysis.ipynb` — Jupyter notebook with price/value/damage/depreciation analysis

## Usage
```bash
source .venv/bin/activate
python run_scraper.py              # Full scrape
python run_scraper.py --list-only  # Search pages only
python run_scraper.py --resume     # Resume detail scraping
jupyter notebook analysis.ipynb    # Open analysis
```

## Notes
- Uses Playwright with Chrome user profile for anti-detection
- Database: taycan.db (SQLite, gitignored)
- macOS: use `gtimeout` instead of `timeout`
