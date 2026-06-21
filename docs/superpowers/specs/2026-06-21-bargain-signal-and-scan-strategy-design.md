# Bargain Signal & Scan Strategy Redesign

**Date:** 2026-06-21
**Status:** Approved (pending spec review)

## Problem

The scraper sorts sahibinden results by `date_desc` and tries to early-stop once it
reaches "old / already-seen" listings, to keep the request footprint small and avoid
bot detection. In practice it keeps scanning deep into old dates and eventually gets
flagged.

### Root cause (verified against `taycan.db`)

The date sahibinden displays — and sorts `date_desc` by — is the **bump/refresh date
("güncelleme"), not the original listing date.**

- The same car's date marches forward over time. Example: `sahibinden_id 1262317796`
  showed `02 Şubat` (run 2, Feb 7) → `17 Şubat` → `14 Mart` → `29 Mart` → `28 Nisan`
  → `02 Haziran` → `17 Haziran` (run 40, Jun 17), as the seller kept re-bumping it.
- **474 of 713** listings seen in more than one run have a *changing* date. Re-bumping
  is ~66% of the catalog, not an edge case.

Because the sort key is a volatile bump date, the early-stop assumptions break:

- **Condition A** (`list_scraper.py:65`, stop when a whole page is already known) and
  **Condition B** (`list_scraper.py:71-77`, stop when every listing on the page is dated
  before the last *completed* run's start date) both assume the date is a stable creation
  date.
- With ~66% of listings re-bumped, a large slice of the catalog carries a recent date at
  any moment, so the date window is huge — the scan must walk past everything bumped since
  the last completed run. Gaps between completed runs (the run history has many
  `interrupted`/`failed` runs that never advance the boundary) widen this further.
- `--full` disables both stops entirely (`list_scraper.py:63`) and is wired to
  inactive-marking (`run_scraper.py:96-102`), so getting inactive detection means a full
  catalog traversal.

The deep traversal walks the whole result set via sequential `pagingOffset=0,50,100,…`
every run — a mechanical, high-volume signature that is easy to flag. The "new listings
in old dates" observation is the tail of never-bumped old listings that only a deep/full
scan reaches.

## Reframe

The bump pattern is **signal, not noise.** A car re-bumped many times over months — often
with price cuts — is a motivated seller with bargaining room. The list page already
captures `price`, `km`, `year` per row (`parsers.py:143-151`), so we can see *whether a
re-bump came with a price cut* without ever opening a detail page. This history already
sits in the `listings` table across runs; it just isn't computed into a signal.

Verified the premise: prices move hard across runs. E.g. `1242993562` went
13,950,000 → 10,750,000 TL (−23%) over 15 appearances. Many cars show 1.9M–3.2M TL drops.
Plenty of cars have deep history (many seen in 10–21 runs).

## Goals

1. Stop relying on the volatile date for early-stop. Embrace a **full list scan every
   run** (cheap, ~6 pages) and keep the expensive part — **detail scraping — limited to
   truly-new cars** (already the behavior via cross-run copy in `detail_scraper.py:39-40`).
2. Compute a persisted **bargain / motivation signal** per car from the cross-run
   price + bump history.
3. Surface the ranked bargaining report and the supporting metrics **in the notebook**.
4. Fold in **light detection-hardening** that fits naturally.

## Non-goals

- Deep anti-detection redesign (headers/fingerprint/profile audit) — separate future work.
- Re-scraping detail pages for already-known cars (price/km come from the list page).
- A standalone markdown/CSV report file — the notebook is the single place this is read.

---

## Design

Chosen approach: **dedicated `listing_signals` table, recomputed each run by one
`scraper/signals.py` module.** The module is the single source of truth for the formula;
the notebook reads the table. (Rejected: an on-the-fly SQLite VIEW — gnarly window SQL,
harder to tune; notebook-only computation — no persistence.)

### 1. Scan strategy

`scraper/list_scraper.py`
- `scrape_search_pages` always visits **all** result pages. Remove the early-stop block
  (`list_scraper.py:63-77`, conditions A and B) and the `full` parameter / `full_scan`
  return value.
- Keep `parse_listing_date` (reused by the signal module).
- `get_last_successful_run_date` and `get_all_known_ids` are no longer needed for stopping;
  `get_all_known_ids` / `new_count` may stay for the informational "(N new)" log line.

`run_scraper.py`
- Inactive-marking (`mark_inactive_listings`) runs on **every** scan (we always do a full
  sweep now). Remove the `full_scan` conditional.
- Retire the `--full` flag (full is the default). Keep `--list-only`, `--resume`,
  `--delay`, `--headless`, `--bot-check`.
- Add `--max-details N` (see §5).
- Call `compute_signals(conn)` (§2) near the end of every successful run and print a brief
  top-N console summary (no file). It runs in all modes — full scan, `--list-only`, and
  `--resume` — since it only reads the (already-persisted) cross-run list history and is
  idempotent. The full report lives in the notebook.

### 2. Signal module + table

New `scraper/signals.py` with `compute_signals(conn)`:
- For each `sahibinden_id`, gather all observations ordered by run id ascending:
  `(run_id, run_started_date, listing_date_str, price, km, is_active)` — joining
  `listings` to `scrape_runs.started_at`.
- Parse `listing_date_str` via `parse_listing_date`. Carry forward the last valid date for
  None values.
- Compute the metrics below. Recompute is a full rebuild each run
  (`DELETE FROM listing_signals;` then insert all cars) — cheap at this scale.

Metrics (per car):

| field | definition |
|---|---|
| `is_active` | car present in the most recent run |
| `runs_seen` | distinct runs the car appears in |
| `first_seen_date` / `last_seen_date` | earliest / latest run `started_at` date |
| `days_on_market` | `(last_seen_date − first_seen_date).days` (lower bound) |
| `bump_count` | count of consecutive observations where parsed `listing_date` strictly increased |
| `bump_cadence_days` | `days_on_market / bump_count` if `bump_count > 0` else NULL |
| `first_price` / `current_price` | first / last non-null price |
| `max_price` / `min_price` | over all observations |
| `total_price_drop` | `max_price − current_price` (clamp ≥ 0) |
| `price_drop_pct` | `(max_price − current_price) / max_price · 100` (clamp ≥ 0) |
| `num_price_cuts` | count of consecutive price decreases |
| `last_price_cut_date` | run date of the most recent price decrease |
| `motivation_score` | 0–100 composite (below) |
| `insufficient_history` | 1 if `runs_seen < 2` |
| `computed_at` | timestamp of this recompute |

Motivation score (weights + caps as tunable constants in `config.py`):

```
norm(x, cap) = clamp(x, 0, cap) / cap

score = 100 * ( 0.40 * norm(price_drop_pct, 25)    # concrete leverage
              + 0.20 * norm(num_price_cuts, 5)     # repeated cuts = eager
              + 0.20 * norm(days_on_market, 180)   # stale = motivated
              + 0.20 * norm(bump_count, 10) )       # bumping hard = stuck
```

Cars with `runs_seen < 2` → `motivation_score = 0`, `insufficient_history = 1`.

`db/schema.sql` — new table (created automatically by `init_db`, `CREATE IF NOT EXISTS`):

```sql
CREATE TABLE IF NOT EXISTS listing_signals (
    sahibinden_id        TEXT PRIMARY KEY,
    is_active            INTEGER,
    runs_seen            INTEGER,
    first_seen_date      TEXT,
    last_seen_date       TEXT,
    days_on_market       INTEGER,
    bump_count           INTEGER,
    bump_cadence_days    REAL,
    first_price          INTEGER,
    current_price        INTEGER,
    max_price            INTEGER,
    min_price            INTEGER,
    total_price_drop     INTEGER,
    price_drop_pct       REAL,
    num_price_cuts       INTEGER,
    last_price_cut_date  TEXT,
    motivation_score     REAL,
    insufficient_history INTEGER DEFAULT 0,
    computed_at          TEXT
);
```

### 3. Per-scan behavior (report)

`run_scraper.py` recomputes `listing_signals` at the end of each successful scan and prints
a short console summary (top ~5 by score). No file is written. The full ranked report is a
notebook cell (§4).

### 4. Notebook (`analysis.ipynb`)

New cells reading `listing_signals` (active cars) via `pandas.read_sql`, joined to the
latest listing row for title/model/year/km/current price/url:
- **Top bargains** — ranked table by `motivation_score` desc: model, year, km,
  current price, `price_drop_pct`, `num_price_cuts`, `bump_count`, `days_on_market`, url.
- **Charts** — price-drop histogram, days-on-market distribution, bumps-vs-price-drop
  scatter.

### 5. Light detection-hardening

- **Shuffle detail-scrape order** — `random.shuffle(to_scrape)` in
  `detail_scraper.py` so fetches aren't in catalog/id order. (Order is irrelevant to
  correctness.)
- **Longer, higher-variance delays** — raise and widen `HUMAN_DELAY_MIN/MAX` and
  randomize `LONG_BREAK_EVERY` / break durations in `config.py` (exact values tunable).
- **`--max-details N` cap** — limit detail fetches per run; the remainder keep
  `detail_scraped=0` and are naturally retried next run (a never-detail-scraped car
  reappears in `to_scrape` because it's absent from `prev_scraped`). Spreads a large
  new-listing batch across several runs instead of one burst.

---

## Components & boundaries

- `scraper/signals.py` — pure computation + persistence of the signal. Input: a DB
  connection. Output: a rebuilt `listing_signals` table. One public function
  `compute_signals(conn)`; testable in isolation against a fixture DB.
- `scraper/list_scraper.py` — simplified to an unconditional full sweep.
- `scraper/detail_scraper.py` — adds shuffle + optional cap; truly-new-only logic unchanged.
- `run_scraper.py` — orchestration: scan → mark inactive → compute signals → console summary.
- `analysis.ipynb` — read-only consumer of `listing_signals`.

## Testing

- `compute_signals` against a small fixture DB with hand-built multi-run history:
  verify `bump_count`, `num_price_cuts`, `price_drop_pct`, `days_on_market`, and
  `motivation_score` for known inputs, plus the `insufficient_history` path.
- Spot-check against the real `taycan.db` (e.g. `1242993562` should show a large
  `price_drop_pct` and high score; `1262317796` a high `bump_count`).
- Verify the simplified `scrape_search_pages` visits all pages and `mark_inactive_listings`
  still runs.

## Risks / notes

- `days_on_market` is a lower bound for cars that predate our first scan.
- `bump_count` / `num_price_cuts` are bounded by scan frequency — relative signals, not
  absolute counts.
- Always-full list scan is ~6 pages — comparable to today's `--full` list phase, not a
  volume increase; the detail phase (the real cost) stays minimal.
