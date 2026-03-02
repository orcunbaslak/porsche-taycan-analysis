# Taycan Analysis

Scrapes Porsche Taycan listings from sahibinden.com and analyzes them in a Jupyter notebook.

## Structure
- `scraper/` — rebrowser-playwright scraper (browser.py, list_scraper.py, detail_scraper.py, parsers.py, config.py, navigate.py)
- `db/` — SQLite schema and helpers (schema.sql, database.py)
- `run_scraper.py` — CLI entry point
- `analysis.ipynb` — Jupyter notebook with price/value/damage/depreciation analysis

## Usage
```bash
source .venv/bin/activate
python run_scraper.py              # Full scrape
python run_scraper.py --list-only  # Search pages only
python run_scraper.py --resume     # Resume detail scraping
python run_scraper.py --bot-check  # Test anti-detection on bot check sites
jupyter notebook analysis.ipynb    # Open analysis
```

## Anti-Detection
- Uses rebrowser-playwright (CDP leak fix) + patched driver (renamed __pw/__playwright globals)
- After `pip install rebrowser-playwright`, run `./patch_driver.sh` to rename Playwright globals
- Stealth JS injected via CDP: webdriver flag hidden, Permissions.query patched
- Chrome launched with `--disable-blink-features=AutomationControlled`

## Notes
- Uses rebrowser-playwright with Chrome user profile for anti-detection
- Database: taycan.db (SQLite, gitignored)
- macOS: use `gtimeout` instead of `timeout`
