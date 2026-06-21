# Taycan Analysis

Scrapes Porsche Taycan listings from sahibinden.com and analyzes them in a Jupyter notebook.

## Structure
- `scraper/` — rebrowser-playwright scraper (browser.py, list_scraper.py, detail_scraper.py, parsers.py, signals.py, config.py, navigate.py)
- `db/` — SQLite schema and helpers (schema.sql, database.py)
- `run_scraper.py` — CLI entry point
- `analysis.ipynb` — Jupyter notebook with price/value/damage/depreciation analysis
- `tests/` — pytest suite (signal logic, scan strategy)

## Usage
```bash
source .venv/bin/activate
python run_scraper.py                  # Full scan (always walks all list pages) + details for new cars
python run_scraper.py --list-only      # Search pages only (still refreshes the bargain signal)
python run_scraper.py --resume         # Resume detail scraping
python run_scraper.py --max-details 30 # Cap detail fetches this run; rest retried next run
python run_scraper.py --bot-check      # Test anti-detection on bot check sites
jupyter notebook analysis.ipynb        # Open analysis (incl. Top Bargain Candidates)
pytest -q                              # Run the test suite
```

## Anti-Detection
- Uses rebrowser-playwright (CDP leak fix) + patched driver (renamed __pw/__playwright globals)
- After `pip install rebrowser-playwright`, run `./patch_driver.sh` to rename Playwright globals
- Stealth JS injected via CDP: webdriver flag hidden, Permissions.query patched
- Chrome launched with `--disable-blink-features=AutomationControlled`

## Notes
- Uses rebrowser-playwright with Chrome user profile for anti-detection
- Database: taycan.db (SQLite, tracked in git)
- macOS: use `gtimeout` instead of `timeout`
- Sahibinden's listing date is a *bump* date, not a creation date (~66% of cars get re-bumped). The scan no longer early-stops on date; it always does a full list sweep and only detail-scrapes truly-new cars. `scraper/signals.py` rebuilds the `listing_signals` table (bump count, price drops, days-on-market, 0-100 motivation score) each run; the notebook's Section 15 shows the ranked report, signal charts, and per-car price history.
