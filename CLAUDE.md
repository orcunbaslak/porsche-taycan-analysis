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
python run_scraper.py --resume         # PerimeterX-aware drain of the detail backlog (human click-through)
python run_scraper.py --max-details 6  # Cap detail/drain fetches this run; rest retried next run
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
- **Rate-limit pacing (retuned 2026-06-25 after a recurring block):** the block is reputation/volume-driven, not just speed-driven — on a degraded profile it tripped at ~9 total requests (was ~18), and a 4-day cooldown wasn't enough. Defaults are now gentler: `HUMAN_DELAY` 12–30s, long break every 4 requests (45–120s), `DEFAULT_MAX_DETAILS=3`. **For routine refreshes prefer `--list-only`** (~6 requests, no detail fetches) — the bargain signal is fully list-based. The real cure for a burned profile/IP is a fresh Chrome profile and/or residential proxy (still not done). `--bot-check` verifies stealth safely (hits browserscan, not sahibinden).
- **Block detection now covers delayed redirects:** `navigate.page_is_blocked(page)` re-checks the live URL+body after a content-selector wait times out. The rate-limit page can arrive via a client-side redirect, so `safe_goto`'s up-front URL check misses it and the wait just times out — previously this was swallowed as a generic error and the loop kept hammering (crashing the session, forcing a Ctrl-C → run logged `interrupted`, not `blocked`). Both list and detail scrapers now raise `BlockedError` on a timeout-that-is-really-a-block, so the run aborts cleanly. Tests in `tests/test_block_detection.py`.
- **`--resume` now drains the GLOBAL detail backlog (changed 2026-06-25):** previously it resumed only the *latest* run's rows, which breaks after a partial/interrupted sweep (e.g. a 51-row run) — the rest of the backlog was never revisited, so details never filled. Now `--resume` calls `scrape_detail_backlog`, which fetches every active listing that has never been detail-scraped in *any* run, deduped by `sahibinden_id` via `db.get_active_undetailed_listings` (latest row per id, `is_active=1`, compared against all `detail_scraped=1` rows). No list sweep → the whole request budget goes to the gap; capped by `--max-details`; aborts cleanly on a block. The per-listing fetch is shared (`detail_scraper._scrape_one_detail`) with the normal path. Tests in `tests/test_detail_backlog.py`. **Workflow:** alternate cheap `--list-only` (signal refresh) and `--resume` (detail drain) sessions, each under the block ceiling, with cooldowns between.
- **The block is PerimeterX, not reputation/rate (diagnosed + beaten 2026-06-25).** Live CDP probing showed sahibinden runs **PerimeterX/HUMAN** (sensor `sahibinden.com/QerrWGjI/init.js`, `_px3` risk cookie) + Cloudflare + reCAPTCHA + Sift. Our automation fingerprint is clean (no `webdriver`, no CDP leak); the tells were behavioral: `page.goto` to detail URLs sends `Sec-Fetch-Site: none` + no `Referer`, and the PX sensor scores robotic mouse/timing. **Fix (`--resume` → `detail_scraper.scrape_detail_backlog_via_clicks`):** warm up ONCE with the PX sensor *armed* + human Bézier mouse movement (`human_behavior.move_mouse_humanlike`/`wander_mouse`) to mint a healthy `_px3`; then **disarm** the sensor (`browser.disarm_px`/`arm_px` block `config.PX_SENSOR_PATTERNS` via `page.route`) so it can't re-score us, and navigate by **clicking the real listing anchor** (`navigate.click_listing` → trusted `isTrusted=true` click, `Sec-Fetch-Site: same-origin` + `Referer`). The good `_px3` is durable (cookie TTL ~250d, value stable while disarmed) — disarming *protects* it. Validated live: drained 8/8 with zero blocks (run 46). Burst pacing `DETAIL_BURST_MIN/MAX_GAP` (2–6s), NOT the 5-min `HUMAN_DELAY`. If `_px3`/the sensor path (`QerrWGjI`) rotates, re-probe the homepage and update `PX_SENSOR_PATTERNS`. Tests in `tests/test_px_navigation.py`.
