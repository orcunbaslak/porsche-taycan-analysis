# Bargain Signal & Scan Strategy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the broken date-based early-stop with an always-full list scan, and compute a persisted per-car "bargain / motivation" signal from the cross-run price + bump history, surfaced in the notebook.

**Architecture:** A new pure-computation module `scraper/signals.py` derives metrics from the `listings` history already in SQLite and rebuilds a `listing_signals` table each run. The list scraper is simplified to walk all pages; the detail scraper keeps its truly-new-only behavior plus a shuffle and an optional per-run cap. `run_scraper.py` orchestrates scan → mark inactive → compute signals → print a short console summary. The notebook reads `listing_signals`.

**Tech Stack:** Python 3, SQLite (stdlib `sqlite3`), BeautifulSoup/lxml (existing parsers), pytest (new dev dependency), pandas/plotly (notebook).

**Spec:** `docs/superpowers/specs/2026-06-21-bargain-signal-and-scan-strategy-design.md`

**Conventions:**
- Run Python via the venv: `.venv/bin/python`.
- Run tests via: `.venv/bin/python -m pytest <path> -v`.
- All dates stored in the new table are ISO strings (`YYYY-MM-DD`) or NULL.

---

### Task 1: pytest scaffold + `listing_signals` schema

**Files:**
- Modify: `requirements.txt`
- Modify: `db/schema.sql`
- Test: `tests/test_schema.py`

- [ ] **Step 1: Install pytest into the venv**

Run:
```bash
.venv/bin/python -m pip install pytest && echo "pytest-installed"
```
Expected: ends with `pytest-installed`.

- [ ] **Step 2: Add pytest to requirements.txt**

Append one line to `requirements.txt` so the dependency is recorded:
```
pytest
```
(Final file is the existing 8 packages plus `pytest`.)

- [ ] **Step 3: Write the failing test**

Create `tests/test_schema.py`:
```python
import os
import tempfile

from db.database import init_db, get_connection


def _table_columns(conn, table):
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def test_init_db_creates_listing_signals_table():
    with tempfile.TemporaryDirectory() as d:
        db_path = os.path.join(d, "t.db")
        init_db(db_path)
        conn = get_connection(db_path)
        cols = _table_columns(conn, "listing_signals")
        conn.close()
    expected = {
        "sahibinden_id", "is_active", "runs_seen", "first_seen_date",
        "last_seen_date", "days_on_market", "bump_count", "bump_cadence_days",
        "first_price", "current_price", "max_price", "min_price",
        "total_price_drop", "price_drop_pct", "num_price_cuts",
        "last_price_cut_date", "motivation_score", "insufficient_history",
        "computed_at",
    }
    assert expected.issubset(cols)
```

- [ ] **Step 4: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_schema.py -v`
Expected: FAIL — `PRAGMA table_info(listing_signals)` returns no rows, so `cols` is empty and the subset assertion fails.

- [ ] **Step 5: Add the table to the schema**

Append to `db/schema.sql` (after the `features` table):
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

- [ ] **Step 6: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_schema.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add requirements.txt db/schema.sql tests/test_schema.py
git commit -m "feat: add listing_signals table + pytest scaffold"
```

---

### Task 2: Score config constants + pure scoring helpers

**Files:**
- Modify: `scraper/config.py`
- Create: `scraper/signals.py`
- Test: `tests/test_signals_score.py`

- [ ] **Step 1: Add score constants to config**

Append to `scraper/config.py`:
```python
# --- Bargain / motivation score ---
# Weights must sum to 1.0; each input is normalized against its cap (0..1).
SCORE_WEIGHT_PRICE_DROP = 0.40   # price_drop_pct
SCORE_WEIGHT_PRICE_CUTS = 0.20   # num_price_cuts
SCORE_WEIGHT_DAYS = 0.20         # days_on_market
SCORE_WEIGHT_BUMPS = 0.20        # bump_count

SCORE_CAP_PRICE_DROP_PCT = 25.0  # % drop that maxes out this component
SCORE_CAP_PRICE_CUTS = 5         # number of cuts that maxes out
SCORE_CAP_DAYS_ON_MARKET = 180   # days that maxes out
SCORE_CAP_BUMP_COUNT = 10        # bumps that maxes out

REPORT_TOP_N = 5                 # rows in the console summary after a scan
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_signals_score.py`:
```python
import pytest

from scraper.signals import _norm, motivation_score


def test_norm_basic():
    assert _norm(10, 20) == 0.5
    assert _norm(-5, 20) == 0.0   # clamped low
    assert _norm(30, 20) == 1.0   # clamped high
    assert _norm(5, 0) == 0.0     # zero cap is safe


def test_motivation_score_known_inputs():
    # price_drop_pct=14.2857, cuts=2, days=90, bumps=3
    # = 100 * (0.40*0.571428 + 0.20*0.4 + 0.20*0.5 + 0.20*0.3) = 46.857...
    score = motivation_score(
        price_drop_pct=14.285714, num_price_cuts=2, days_on_market=90, bump_count=3
    )
    assert score == pytest.approx(46.857, abs=0.01)


def test_motivation_score_zero_when_no_signal():
    assert motivation_score(0, 0, 0, 0) == 0.0
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_signals_score.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scraper.signals'` (or import error for `_norm`).

- [ ] **Step 4: Create the module with the scoring helpers**

Create `scraper/signals.py`:
```python
"""Compute a per-car bargain / motivation signal from cross-run listing history."""

from scraper.config import (
    SCORE_WEIGHT_PRICE_DROP,
    SCORE_WEIGHT_PRICE_CUTS,
    SCORE_WEIGHT_DAYS,
    SCORE_WEIGHT_BUMPS,
    SCORE_CAP_PRICE_DROP_PCT,
    SCORE_CAP_PRICE_CUTS,
    SCORE_CAP_DAYS_ON_MARKET,
    SCORE_CAP_BUMP_COUNT,
)


def _norm(x, cap):
    """Normalize x into 0..1 against cap, clamping out-of-range values."""
    if cap <= 0:
        return 0.0
    return min(max(x, 0), cap) / cap


def motivation_score(price_drop_pct, num_price_cuts, days_on_market, bump_count):
    """Weighted 0..100 composite of the four bargain signals."""
    return 100 * (
        SCORE_WEIGHT_PRICE_DROP * _norm(price_drop_pct, SCORE_CAP_PRICE_DROP_PCT)
        + SCORE_WEIGHT_PRICE_CUTS * _norm(num_price_cuts, SCORE_CAP_PRICE_CUTS)
        + SCORE_WEIGHT_DAYS * _norm(days_on_market, SCORE_CAP_DAYS_ON_MARKET)
        + SCORE_WEIGHT_BUMPS * _norm(bump_count, SCORE_CAP_BUMP_COUNT)
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_signals_score.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add scraper/config.py scraper/signals.py tests/test_signals_score.py
git commit -m "feat: add motivation score config + scoring helpers"
```

---

### Task 3: `compute_car_metrics` pure function

**Files:**
- Modify: `scraper/signals.py`
- Test: `tests/test_signals_metrics.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_signals_metrics.py`:
```python
from datetime import date

import pytest

from scraper.signals import compute_car_metrics


def _obs(run_d, list_d, price):
    return {"run_date": run_d, "listing_date": list_d, "price": price}


def test_bargain_car_metrics():
    observations = [
        _obs(date(2026, 1, 1), date(2026, 1, 1), 14_000_000),
        _obs(date(2026, 2, 1), date(2026, 1, 20), 13_000_000),  # bump + cut
        _obs(date(2026, 3, 1), date(2026, 2, 15), 13_000_000),  # bump, no cut
        _obs(date(2026, 4, 1), date(2026, 3, 10), 12_000_000),  # bump + cut
    ]
    m = compute_car_metrics(observations)

    assert m["runs_seen"] == 4
    assert m["first_seen_date"] == date(2026, 1, 1)
    assert m["last_seen_date"] == date(2026, 4, 1)
    assert m["days_on_market"] == 90
    assert m["bump_count"] == 3
    assert m["bump_cadence_days"] == pytest.approx(30.0)
    assert m["first_price"] == 14_000_000
    assert m["current_price"] == 12_000_000
    assert m["max_price"] == 14_000_000
    assert m["min_price"] == 12_000_000
    assert m["total_price_drop"] == 2_000_000
    assert m["price_drop_pct"] == pytest.approx(14.2857, abs=0.01)
    assert m["num_price_cuts"] == 2
    assert m["last_price_cut_date"] == date(2026, 4, 1)
    assert m["insufficient_history"] == 0
    assert m["motivation_score"] == pytest.approx(46.857, abs=0.01)


def test_single_observation_is_insufficient_history():
    m = compute_car_metrics([_obs(date(2026, 4, 1), date(2026, 4, 1), 12_000_000)])
    assert m["runs_seen"] == 1
    assert m["insufficient_history"] == 1
    assert m["bump_count"] == 0
    assert m["num_price_cuts"] == 0
    assert m["days_on_market"] == 0
    assert m["motivation_score"] == 0.0
    assert m["bump_cadence_days"] is None


def test_none_dates_and_prices_are_carried_over():
    # Missing date in the middle must not count as a bump; missing price ignored.
    observations = [
        _obs(date(2026, 1, 1), date(2026, 1, 1), 10_000_000),
        _obs(date(2026, 2, 1), None, None),
        _obs(date(2026, 3, 1), date(2026, 1, 1), 9_000_000),  # date unchanged -> no bump
    ]
    m = compute_car_metrics(observations)
    assert m["bump_count"] == 0
    assert m["num_price_cuts"] == 1
    assert m["first_price"] == 10_000_000
    assert m["current_price"] == 9_000_000
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_signals_metrics.py -v`
Expected: FAIL — `ImportError: cannot import name 'compute_car_metrics'`.

- [ ] **Step 3: Implement `compute_car_metrics`**

Add to `scraper/signals.py` (after `motivation_score`):
```python
def compute_car_metrics(observations):
    """Derive bargain metrics from a car's observations, ordered oldest -> newest.

    Each observation is a dict: {"run_date": date, "listing_date": date|None, "price": int|None}.
    Returns a dict of metrics (dates as date objects or None).
    """
    runs_seen = len(observations)
    first_seen_date = observations[0]["run_date"]
    last_seen_date = observations[-1]["run_date"]
    days_on_market = (last_seen_date - first_seen_date).days

    # bump_count: forward changes in listing_date, carrying the last valid date over None.
    bump_count = 0
    last_date = None
    for o in observations:
        d = o["listing_date"]
        if d is None:
            continue
        if last_date is not None and d > last_date:
            bump_count += 1
        last_date = d
    bump_cadence_days = (days_on_market / bump_count) if bump_count > 0 else None

    prices = [o["price"] for o in observations if o["price"] is not None]
    if prices:
        first_price = prices[0]
        current_price = prices[-1]
        max_price = max(prices)
        min_price = min(prices)
        total_price_drop = max(0, max_price - current_price)
        price_drop_pct = (total_price_drop / max_price * 100) if max_price else 0.0
    else:
        first_price = current_price = max_price = min_price = None
        total_price_drop = 0
        price_drop_pct = 0.0

    # num_price_cuts: consecutive decreases; record the run_date of the latest cut.
    num_price_cuts = 0
    last_price_cut_date = None
    prev = None
    for o in observations:
        p = o["price"]
        if p is None:
            continue
        if prev is not None and p < prev:
            num_price_cuts += 1
            last_price_cut_date = o["run_date"]
        prev = p

    insufficient_history = 1 if runs_seen < 2 else 0
    score = 0.0 if insufficient_history else motivation_score(
        price_drop_pct, num_price_cuts, days_on_market, bump_count
    )

    return {
        "runs_seen": runs_seen,
        "first_seen_date": first_seen_date,
        "last_seen_date": last_seen_date,
        "days_on_market": days_on_market,
        "bump_count": bump_count,
        "bump_cadence_days": bump_cadence_days,
        "first_price": first_price,
        "current_price": current_price,
        "max_price": max_price,
        "min_price": min_price,
        "total_price_drop": total_price_drop,
        "price_drop_pct": price_drop_pct,
        "num_price_cuts": num_price_cuts,
        "last_price_cut_date": last_price_cut_date,
        "insufficient_history": insufficient_history,
        "motivation_score": score,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_signals_metrics.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add scraper/signals.py tests/test_signals_metrics.py
git commit -m "feat: compute per-car bargain metrics"
```

---

### Task 4: `compute_signals(conn)` — read history, rebuild `listing_signals`

**Files:**
- Modify: `scraper/signals.py`
- Test: `tests/test_signals_db.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_signals_db.py`:
```python
import os
import tempfile

import pytest

from db.database import init_db, get_connection
from scraper.signals import compute_signals


def _make_run(conn, run_id, started_at):
    conn.execute(
        "INSERT INTO scrape_runs (id, started_at, status) VALUES (?, ?, 'completed')",
        (run_id, started_at),
    )


def _add_listing(conn, run_id, sah_id, listing_date, price):
    conn.execute(
        """INSERT INTO listings (scrape_run_id, sahibinden_id, listing_date, price)
           VALUES (?, ?, ?, ?)""",
        (run_id, sah_id, listing_date, price),
    )


def test_compute_signals_rebuilds_table():
    with tempfile.TemporaryDirectory() as d:
        db_path = os.path.join(d, "t.db")
        init_db(db_path)
        conn = get_connection(db_path)

        _make_run(conn, 1, "2026-01-01T10:00:00")
        _make_run(conn, 2, "2026-04-01T10:00:00")
        # One car, bumped + price cut between runs.
        _add_listing(conn, 1, "AAA", "01 Ocak", 14_000_000)
        _add_listing(conn, 2, "AAA", "10 Mart", 12_000_000)
        # A car only in the old run -> inactive, insufficient history.
        _add_listing(conn, 1, "BBB", "01 Ocak", 9_000_000)
        conn.commit()

        compute_signals(conn)

        rows = {r["sahibinden_id"]: r for r in
                conn.execute("SELECT * FROM listing_signals").fetchall()}
        conn.close()

    assert set(rows) == {"AAA", "BBB"}

    aaa = rows["AAA"]
    assert aaa["is_active"] == 1            # present in latest run (2)
    assert aaa["runs_seen"] == 2
    assert aaa["bump_count"] == 1           # 01 Ocak -> 10 Mart
    assert aaa["num_price_cuts"] == 1
    assert aaa["current_price"] == 12_000_000
    assert aaa["max_price"] == 14_000_000
    assert aaa["price_drop_pct"] == pytest.approx(14.2857, abs=0.01)
    assert aaa["first_seen_date"] == "2026-01-01"
    assert aaa["motivation_score"] > 0
    assert aaa["computed_at"] is not None

    bbb = rows["BBB"]
    assert bbb["is_active"] == 0            # not in latest run
    assert bbb["insufficient_history"] == 1
    assert bbb["motivation_score"] == 0.0


def test_compute_signals_is_idempotent():
    with tempfile.TemporaryDirectory() as d:
        db_path = os.path.join(d, "t.db")
        init_db(db_path)
        conn = get_connection(db_path)
        _make_run(conn, 1, "2026-01-01T10:00:00")
        _add_listing(conn, 1, "AAA", "01 Ocak", 14_000_000)
        conn.commit()
        compute_signals(conn)
        compute_signals(conn)  # second run must not duplicate rows
        n = conn.execute("SELECT COUNT(*) AS c FROM listing_signals").fetchone()["c"]
        conn.close()
    assert n == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_signals_db.py -v`
Expected: FAIL — `ImportError: cannot import name 'compute_signals'`.

- [ ] **Step 3: Implement `compute_signals` and a date serializer**

Add to the top imports of `scraper/signals.py`:
```python
from collections import defaultdict
from datetime import datetime

from scraper.parsers import parse_listing_date
```

Add to `scraper/signals.py` (after `compute_car_metrics`):
```python
def _iso_or_none(d):
    return d.isoformat() if d is not None else None


def compute_signals(conn):
    """Recompute the listing_signals table from the full cross-run listings history."""
    latest_row = conn.execute("SELECT MAX(id) AS m FROM scrape_runs").fetchone()
    latest_run_id = latest_row["m"] if latest_row else None

    rows = conn.execute(
        """SELECT l.sahibinden_id, l.scrape_run_id, l.listing_date, l.price, r.started_at
           FROM listings l
           JOIN scrape_runs r ON r.id = l.scrape_run_id
           ORDER BY l.sahibinden_id, l.scrape_run_id"""
    ).fetchall()

    groups = defaultdict(list)
    for row in rows:
        groups[row["sahibinden_id"]].append(row)

    now = datetime.now().isoformat()
    conn.execute("DELETE FROM listing_signals")

    for sah_id, obs_rows in groups.items():
        observations = [
            {
                "run_date": datetime.fromisoformat(o["started_at"]).date(),
                "listing_date": parse_listing_date(o["listing_date"]),
                "price": o["price"],
            }
            for o in obs_rows
        ]
        is_active = 1 if any(o["scrape_run_id"] == latest_run_id for o in obs_rows) else 0
        m = compute_car_metrics(observations)
        conn.execute(
            """INSERT INTO listing_signals (
                sahibinden_id, is_active, runs_seen, first_seen_date, last_seen_date,
                days_on_market, bump_count, bump_cadence_days, first_price, current_price,
                max_price, min_price, total_price_drop, price_drop_pct, num_price_cuts,
                last_price_cut_date, motivation_score, insufficient_history, computed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                sah_id, is_active, m["runs_seen"],
                _iso_or_none(m["first_seen_date"]), _iso_or_none(m["last_seen_date"]),
                m["days_on_market"], m["bump_count"], m["bump_cadence_days"],
                m["first_price"], m["current_price"], m["max_price"], m["min_price"],
                m["total_price_drop"], m["price_drop_pct"], m["num_price_cuts"],
                _iso_or_none(m["last_price_cut_date"]), m["motivation_score"],
                m["insufficient_history"], now,
            ),
        )

    conn.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_signals_db.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add scraper/signals.py tests/test_signals_db.py
git commit -m "feat: compute_signals rebuilds listing_signals from history"
```

---

### Task 5: `top_bargains(conn, n)` query for the console summary

**Files:**
- Modify: `scraper/signals.py`
- Test: `tests/test_signals_top.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_signals_top.py`:
```python
import os
import tempfile

from db.database import init_db, get_connection
from scraper.signals import compute_signals, top_bargains


def test_top_bargains_orders_active_cars_by_score():
    with tempfile.TemporaryDirectory() as d:
        db_path = os.path.join(d, "t.db")
        init_db(db_path)
        conn = get_connection(db_path)
        conn.execute("INSERT INTO scrape_runs (id, started_at, status) VALUES (1, '2026-01-01T10:00:00', 'completed')")
        conn.execute("INSERT INTO scrape_runs (id, started_at, status) VALUES (2, '2026-06-01T10:00:00', 'completed')")

        # High-signal car: big drop across both runs.
        conn.execute("INSERT INTO listings (scrape_run_id, sahibinden_id, model, year, price, url, listing_date) VALUES (1,'HOT','Turbo',2022,16000000,'http://x/HOT','01 Ocak')")
        conn.execute("INSERT INTO listings (scrape_run_id, sahibinden_id, model, year, price, url, listing_date) VALUES (2,'HOT','Turbo',2022,12000000,'http://x/HOT','20 Mayıs')")
        # Low-signal car: stable price.
        conn.execute("INSERT INTO listings (scrape_run_id, sahibinden_id, model, year, price, url, listing_date) VALUES (1,'COLD','4S',2021,10000000,'http://x/COLD','01 Ocak')")
        conn.execute("INSERT INTO listings (scrape_run_id, sahibinden_id, model, year, price, url, listing_date) VALUES (2,'COLD','4S',2021,10000000,'http://x/COLD','01 Ocak')")
        conn.commit()
        compute_signals(conn)

        rows = top_bargains(conn, 5)
        conn.close()

    assert [r["sahibinden_id"] for r in rows][0] == "HOT"
    assert all("model" in dict(r) and "url" in dict(r) for r in rows)
    # COLD has zero drop/bumps -> score 0 but still active; HOT ranks first.
    assert rows[0]["motivation_score"] >= rows[-1]["motivation_score"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_signals_top.py -v`
Expected: FAIL — `ImportError: cannot import name 'top_bargains'`.

- [ ] **Step 3: Implement `top_bargains`**

Add to `scraper/signals.py`:
```python
def top_bargains(conn, n):
    """Return the top-n active cars by motivation_score, joined to their latest listing row."""
    return conn.execute(
        """SELECT s.sahibinden_id, s.motivation_score, s.price_drop_pct, s.bump_count,
                  s.days_on_market, s.num_price_cuts, s.current_price,
                  l.model, l.year, l.km, l.url
           FROM listing_signals s
           JOIN listings l
             ON l.sahibinden_id = s.sahibinden_id
            AND l.scrape_run_id = (SELECT MAX(id) FROM scrape_runs)
           WHERE s.is_active = 1 AND s.insufficient_history = 0
           ORDER BY s.motivation_score DESC
           LIMIT ?""",
        (n,),
    ).fetchall()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_signals_top.py -v`
Expected: PASS.

- [ ] **Step 5: Add a failing test for `price_history`**

Append to `tests/test_signals_top.py`:
```python
def test_price_history_is_ordered_oldest_to_newest():
    with tempfile.TemporaryDirectory() as d:
        db_path = os.path.join(d, "t.db")
        init_db(db_path)
        conn = get_connection(db_path)
        conn.execute("INSERT INTO scrape_runs (id, started_at, status) VALUES (2, '2026-06-01T10:00:00', 'completed')")
        conn.execute("INSERT INTO scrape_runs (id, started_at, status) VALUES (1, '2026-01-01T10:00:00', 'completed')")
        conn.execute("INSERT INTO listings (scrape_run_id, sahibinden_id, price, listing_date) VALUES (2,'HOT',12000000,'20 Mayıs')")
        conn.execute("INSERT INTO listings (scrape_run_id, sahibinden_id, price, listing_date) VALUES (1,'HOT',16000000,'01 Ocak')")
        conn.commit()

        from scraper.signals import price_history
        hist = price_history(conn, "HOT")
        conn.close()

    assert [h["price"] for h in hist] == [16000000, 12000000]   # ordered by run id
    assert hist[0]["run_date"] == "2026-01-01"
    assert hist[0]["listing_date"] == "01 Ocak"
    assert [h["run_id"] for h in hist] == [1, 2]
```

- [ ] **Step 6: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_signals_top.py::test_price_history_is_ordered_oldest_to_newest -v`
Expected: FAIL — `ImportError: cannot import name 'price_history'`.

- [ ] **Step 7: Implement `price_history`**

Add to `scraper/signals.py`:
```python
def price_history(conn, sahibinden_id):
    """Return a car's per-run observations, oldest -> newest.

    Each item: {"run_id", "run_date" (YYYY-MM-DD), "listing_date" (raw bump text), "price"}.
    Reads the raw listings history; the full price+bump timeline lives there.
    """
    rows = conn.execute(
        """SELECT l.scrape_run_id AS run_id, r.started_at, l.listing_date, l.price
           FROM listings l
           JOIN scrape_runs r ON r.id = l.scrape_run_id
           WHERE l.sahibinden_id = ?
           ORDER BY l.scrape_run_id""",
        (sahibinden_id,),
    ).fetchall()
    return [
        {
            "run_id": row["run_id"],
            "run_date": (row["started_at"] or "")[:10],
            "listing_date": row["listing_date"],
            "price": row["price"],
        }
        for row in rows
    ]
```

- [ ] **Step 8: Run both tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_signals_top.py -v`
Expected: PASS (2 tests).

- [ ] **Step 9: Commit**

```bash
git add scraper/signals.py tests/test_signals_top.py
git commit -m "feat: top_bargains + price_history queries"
```

---

### Task 6: Simplify the list scraper to an unconditional full scan

**Files:**
- Modify: `scraper/list_scraper.py`
- Test: `tests/test_list_scraper.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_list_scraper.py`. It monkeypatches the I/O boundaries and proves the scan does NOT early-stop on an all-known page (the old behavior) and visits every page until `has_next_page` is false:
```python
import os
import tempfile

import scraper.list_scraper as ls
from db.database import init_db, get_connection, create_scrape_run


def test_scan_visits_all_pages_without_early_stop(monkeypatch):
    # Three pages. Page 2 is entirely already-known (would have tripped the old
    # condition A early-stop); page 3 has new listings that must still be reached.
    pages = [
        [{"sahibinden_id": "N1", "listing_date": "Bugün"},
         {"sahibinden_id": "N2", "listing_date": "Bugün"}],
        [{"sahibinden_id": "N1", "listing_date": "Bugün"},
         {"sahibinden_id": "N2", "listing_date": "Bugün"}],   # all known
        [{"sahibinden_id": "N3", "listing_date": "01 Ocak"}],  # new, old-dated
    ]
    calls = {"i": 0}

    def fake_parse(html):
        page = pages[calls["i"]]
        calls["i"] += 1
        # fill required keys used by upsert_listing_summary
        return [dict(url=None, title=None, model=None, year=None, km=None,
                     color=None, price=None, currency="TL",
                     location_city=None, location_district=None, **row)
                for row in page]

    def fake_has_next(html):
        return calls["i"] < len(pages)  # more pages remain

    # Neutralize browser + timing side effects.
    monkeypatch.setattr(ls, "parse_listing_rows", fake_parse)
    monkeypatch.setattr(ls, "has_next_page", fake_has_next)
    monkeypatch.setattr(ls, "safe_goto", lambda page, url: None)
    monkeypatch.setattr(ls, "simulate_list_page", lambda page: None)
    monkeypatch.setattr(ls, "human_delay", lambda *a, **k: None)
    monkeypatch.setattr(ls, "maybe_long_break", lambda *a, **k: None)

    class FakePage:
        def wait_for_selector(self, *a, **k):
            return None
        def content(self):
            return "<html></html>"

    with tempfile.TemporaryDirectory() as d:
        db_path = os.path.join(d, "t.db")
        init_db(db_path)
        conn = get_connection(db_path)
        run_id = create_scrape_run(conn)
        total = ls.scrape_search_pages(FakePage(), conn, run_id)
        ids = {r["sahibinden_id"] for r in
               conn.execute("SELECT DISTINCT sahibinden_id FROM listings").fetchall()}
        conn.close()

    assert total == 5                       # 2 + 2 + 1, no early stop
    assert ids == {"N1", "N2", "N3"}        # reached the old-dated page 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_list_scraper.py -v`
Expected: FAIL — current `scrape_search_pages` early-stops on page 2 (`new_count == 0`), so `total` is 4 and `N3` is missing. (It may also fail on the signature if `time.sleep(1)` blocks — see Step 3, which removes the per-page sleep dependency on real time by leaving `time.sleep` but the test's small count keeps it fast; if it is too slow, monkeypatch `ls.time.sleep`.)

- [ ] **Step 3: Rewrite `scrape_search_pages` as an unconditional full scan**

Replace the entire body of `scraper/list_scraper.py` with:
```python
"""Scrape sahibinden.com search result pages for Taycan listings."""

import time

from scraper.config import SEARCH_URL
from scraper.parsers import parse_listing_rows, has_next_page
from scraper.human_behavior import human_delay, maybe_long_break, simulate_list_page
from scraper.navigate import safe_goto
from db.database import upsert_listing_summary, get_all_known_ids


def scrape_search_pages(page, conn, run_id, delay=None):
    """
    Walk every search result page (sorted date_desc) and upsert listing summaries.

    The scan is always full: sahibinden's displayed date is a volatile bump date,
    so date/known-based early-stopping was unreliable. The full list sweep is cheap
    (~6 pages) and feeds both the bargain signal and inactive detection; cost control
    lives in the detail phase, which only fetches truly-new cars.

    delay: If set, uses delay..delay*2 as the sleep range instead of the default
           human behavior range (5-10s).
    Returns total_found (int).
    """
    known_ids = get_all_known_ids(conn)
    offset = 0
    total_found = 0
    page_count = 0

    while True:
        url = SEARCH_URL if offset == 0 else f"{SEARCH_URL}&pagingOffset={offset}"
        print(f"[LIST] Loading: {url}")

        safe_goto(page, url)
        page.wait_for_selector("tr.searchResultsItem", timeout=30000)
        time.sleep(1)  # small extra wait for DOM

        simulate_list_page(page)

        html = page.content()
        listings = parse_listing_rows(html)

        if not listings:
            print(f"[LIST] No listings found at offset {offset}, stopping.")
            break

        new_count = sum(1 for l in listings if l["sahibinden_id"] not in known_ids)

        for listing in listings:
            upsert_listing_summary(conn, run_id, listing)
            known_ids.add(listing["sahibinden_id"])
            total_found += 1

        page_count += 1
        print(f"[LIST] Found {len(listings)} listings ({new_count} new, total: {total_found})")

        if not has_next_page(html):
            print("[LIST] No more pages.")
            break

        offset += 50

        if delay is not None:
            human_delay(delay, delay * 2)
        else:
            human_delay()
        maybe_long_break(page_count)

    return total_found
```

Note: this drops the `full` parameter, the `full_scan` return value, the early-stop block, and the now-unused imports `parse_listing_date`, `get_last_successful_run_date`. (`parse_listing_date` is still used by `scraper/signals.py`; we just no longer import it here.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_list_scraper.py -v`
Expected: PASS. If the test is slow due to `time.sleep(1)` per page, add `monkeypatch.setattr(ls.time, "sleep", lambda *_a, **_k: None)` in the test and re-run.

- [ ] **Step 5: Commit**

```bash
git add scraper/list_scraper.py tests/test_list_scraper.py
git commit -m "refactor: list scan always walks all pages (drop date early-stop)"
```

---

### Task 7: Detail scraper — testable selection with shuffle + per-run cap

**Files:**
- Modify: `scraper/detail_scraper.py`
- Test: `tests/test_detail_selection.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_detail_selection.py`:
```python
import random

from scraper.detail_scraper import split_unscraped


def _l(i):
    return {"id": i, "sahibinden_id": str(i), "url": f"http://x/{i}"}


def test_split_separates_copy_from_scrape():
    unscraped = [_l(1), _l(2), _l(3)]
    prev_scraped = {"1", "2"}
    to_copy, to_scrape = split_unscraped(unscraped, prev_scraped, shuffle=False)
    assert {l["sahibinden_id"] for l in to_copy} == {"1", "2"}
    assert {l["sahibinden_id"] for l in to_scrape} == {"3"}


def test_split_caps_scrape_count():
    unscraped = [_l(i) for i in range(10)]
    prev_scraped = set()  # all are new
    to_copy, to_scrape = split_unscraped(
        unscraped, prev_scraped, max_details=4, rng=random.Random(0)
    )
    assert to_copy == []
    assert len(to_scrape) == 4
    # All selected items are genuinely from the input set.
    assert all(l in unscraped for l in to_scrape)


def test_split_no_cap_returns_all_new():
    unscraped = [_l(i) for i in range(5)]
    to_copy, to_scrape = split_unscraped(unscraped, set(), shuffle=False)
    assert len(to_scrape) == 5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_detail_selection.py -v`
Expected: FAIL — `ImportError: cannot import name 'split_unscraped'`.

- [ ] **Step 3: Add `split_unscraped` and wire it into `scrape_detail_pages`**

Add near the top of `scraper/detail_scraper.py` (after the imports), then add `import random` to the import block:
```python
import random


def split_unscraped(unscraped, prev_scraped, max_details=None, shuffle=True, rng=random):
    """Split unscraped listings into (to_copy, to_scrape).

    to_copy:   already detail-scraped in a previous run -> copy, no network.
    to_scrape: truly new -> fetch detail page. Optionally shuffled (de-patterns the
               request order) and capped at max_details (remainder is retried next run
               because it keeps detail_scraped=0).
    """
    to_copy = [l for l in unscraped if l["sahibinden_id"] in prev_scraped]
    to_scrape = [l for l in unscraped if l["sahibinden_id"] not in prev_scraped]
    if shuffle:
        rng.shuffle(to_scrape)
    if max_details is not None:
        to_scrape = to_scrape[:max_details]
    return to_copy, to_scrape
```

Then change the signature of `scrape_detail_pages` from:
```python
def scrape_detail_pages(page, conn, run_id, delay=None, progress_cb=None):
```
to:
```python
def scrape_detail_pages(page, conn, run_id, delay=None, progress_cb=None, max_details=None):
```

And replace the existing split lines (currently `to_copy = [...]` / `to_scrape = [...]`) with:
```python
    to_copy, to_scrape = split_unscraped(unscraped, prev_scraped, max_details=max_details)
```

(The rest of the function — copy loop, scrape loop, progress — is unchanged.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_detail_selection.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add scraper/detail_scraper.py tests/test_detail_selection.py
git commit -m "feat: shuffle + optional per-run cap on detail scraping"
```

---

### Task 8: Wire it together in `run_scraper.py` (retire --full, add --max-details, compute + print signals)

**Files:**
- Modify: `run_scraper.py`
- Modify: `scraper/config.py` (delay tuning — see Step 5)

- [ ] **Step 1: Update imports and CLI flags**

In `run_scraper.py`, update the db import block to add the signal functions:
```python
from db.database import (
    init_db,
    get_connection,
    create_scrape_run,
    finish_scrape_run,
    get_latest_run_id,
    get_run_stats,
    mark_inactive_listings,
)
from scraper.signals import compute_signals, top_bargains
from scraper.config import REPORT_TOP_N
```
Replace the `--full` argument definition:
```python
    parser.add_argument("--full", action="store_true",
                        help="Full scan: visit all list pages (no early stop) and mark inactive listings")
```
with:
```python
    parser.add_argument("--max-details", type=int, default=None,
                        help="Cap detail-page fetches this run; remainder retried next run.")
```

- [ ] **Step 2: Simplify the scan call + always mark inactive**

Replace this block (the `if not args.resume:` body, `run_scraper.py:90-102`):
```python
            if not args.resume:
                # Step 1: Scrape search result pages
                print("\n=== Phase 1: Scraping search results ===")
                total_listings, full_scan = scrape_search_pages(page, conn, run_id, delay=args.delay, full=args.full)
                print(f"\nFound {total_listings} listings total.")

                # Only mark inactive when we did a full scan (visited all pages)
                if full_scan:
                    deactivated = mark_inactive_listings(conn, run_id)
                    if deactivated:
                        print(f"Marked {deactivated} listings as inactive (no longer on sahibinden).")
                else:
                    print("Partial scan (stopped early) — skipping inactive marking.")
```
with:
```python
            if not args.resume:
                # Step 1: Scrape search result pages (always a full sweep)
                print("\n=== Phase 1: Scraping search results ===")
                total_listings = scrape_search_pages(page, conn, run_id, delay=args.delay)
                print(f"\nFound {total_listings} listings total.")

                # Full sweep every run -> always safe to mark inactive.
                deactivated = mark_inactive_listings(conn, run_id)
                if deactivated:
                    print(f"Marked {deactivated} listings as inactive (no longer on sahibinden).")
```

- [ ] **Step 3: Pass the cap into the detail scraper**

Replace the detail call (`run_scraper.py:112`):
```python
                processed = scrape_detail_pages(page, conn, run_id, delay=args.delay, progress_cb=progress_bar)
```
with:
```python
                processed = scrape_detail_pages(page, conn, run_id, delay=args.delay,
                                                progress_cb=progress_bar, max_details=args.max_details)
```

- [ ] **Step 4: Compute signals + print the bargain summary on success**

In `run_scraper.py`, immediately before `status = "completed"` at the end of the `try` block (the one after Phase 2), insert:
```python
            # Recompute the bargain signal and show the top candidates.
            print("\n=== Computing bargain signal ===")
            compute_signals(conn)
            _bargains = top_bargains(conn, REPORT_TOP_N)
            if _bargains:
                print("Top bargain candidates (full report in analysis.ipynb):")
                for r in _bargains:
                    price = f"{r['current_price']:,}" if r["current_price"] is not None else "?"
                    print(f"  score {r['motivation_score']:.0f} | {r['model']} {r['year']} "
                          f"| {price} TL | -{r['price_drop_pct']:.0f}% | "
                          f"{r['bump_count']} bumps | {r['days_on_market']}d | {r['url']}")
```
Note: there are two `status = "completed"` assignments — put this before the **final** one (after Phase 2 / the non-`--list-only` path). For the `--list-only` early `return` path (`run_scraper.py:104-107`), add the same compute call right before its `status = "completed"` so `--list-only` runs also refresh the signal. Factor the block into a local helper `def _report_signal(conn): ...` at the top of `main()` to avoid duplicating the code, and call `_report_signal(conn)` in both spots.

- [ ] **Step 5: Tune delays for the always-full sweep (light hardening)**

In `scraper/config.py`, widen and lengthen the human delays and randomize the long-break cadence:
```python
# Human-like browsing behavior
HUMAN_DELAY_MIN = 6.0   # was 5.0
HUMAN_DELAY_MAX = 14.0  # was 10.0
```
and
```python
# Long break: periodic longer pause to mimic real browsing
LONG_BREAK_EVERY = 12   # was 15 — break a little more often
LONG_BREAK_MIN = 20.0   # was 15.0
LONG_BREAK_MAX = 45.0   # was 30.0
```

- [ ] **Step 6: Smoke-check imports and the full test suite**

Run:
```bash
.venv/bin/python -c "import run_scraper; print('imports-ok')"
.venv/bin/python -m pytest tests/ -v
```
Expected: `imports-ok`, then all tests PASS.

- [ ] **Step 7: Commit**

```bash
git add run_scraper.py scraper/config.py
git commit -m "feat: always-full scan + signal report + per-run detail cap"
```

---

### Task 9: Notebook — top-bargains cell + charts

**Files:**
- Modify: `analysis.ipynb`

- [ ] **Step 1: Add a "Top Bargain Candidates" cell**

Add a new cell to `analysis.ipynb` (use the NotebookEdit tool). It reads `listing_signals` joined to the latest listing row and shows the ranked table:
```python
import sqlite3
import pandas as pd

conn = sqlite3.connect("taycan.db")
bargains = pd.read_sql_query(
    """
    SELECT s.motivation_score AS score, l.model, l.year, l.km,
           s.current_price, s.price_drop_pct, s.num_price_cuts,
           s.bump_count, s.days_on_market, l.url
    FROM listing_signals s
    JOIN listings l
      ON l.sahibinden_id = s.sahibinden_id
     AND l.scrape_run_id = (SELECT MAX(id) FROM scrape_runs)
    WHERE s.is_active = 1 AND s.insufficient_history = 0
    ORDER BY s.motivation_score DESC
    LIMIT 25
    """,
    conn,
)
conn.close()
bargains.style.format({
    "score": "{:.0f}", "current_price": "{:,.0f}", "price_drop_pct": "{:.1f}%",
}).background_gradient(subset=["score"], cmap="Reds")
```

- [ ] **Step 2: Add a charts cell**

Add another cell with the three charts (price-drop histogram, days-on-market distribution, bumps-vs-drop scatter):
```python
import sqlite3
import pandas as pd
import plotly.express as px

conn = sqlite3.connect("taycan.db")
sig = pd.read_sql_query(
    "SELECT * FROM listing_signals WHERE is_active=1 AND insufficient_history=0", conn
)
conn.close()

px.histogram(sig, x="price_drop_pct", nbins=30,
             title="Price drop % across active listings").show()
px.histogram(sig, x="days_on_market", nbins=30,
             title="Days on market (observed lower bound)").show()
px.scatter(sig, x="bump_count", y="price_drop_pct", size="days_on_market",
           hover_data=["sahibinden_id", "current_price"],
           title="Bumps vs. price drop — top-right = motivated sellers").show()
```

- [ ] **Step 3: Add a per-car price-history lookup cell**

Add a cell that takes a `sahibinden_id` and plots its full price + bump timeline (line chart) plus the raw observation table, via the `price_history` helper:
```python
import sqlite3
import pandas as pd
import plotly.express as px
from scraper.signals import price_history

CAR_ID = "1242993562"  # paste a sahibinden_id (the trailing number in a listing url)

conn = sqlite3.connect("taycan.db")
conn.row_factory = sqlite3.Row
hist = pd.DataFrame(price_history(conn, CAR_ID))
conn.close()

display(hist)
if not hist.empty:
    px.line(hist, x="run_date", y="price", markers=True,
            hover_data=["listing_date"],
            title=f"Price history — {CAR_ID}").show()
else:
    print(f"No history for {CAR_ID}")
```

- [ ] **Step 4: Add a top-bargains price-trajectory small-multiples cell**

Add a cell that draws each top-bargain car's price trajectory in a faceted grid:
```python
import sqlite3
import pandas as pd
import plotly.express as px
from scraper.signals import top_bargains, price_history

conn = sqlite3.connect("taycan.db")
conn.row_factory = sqlite3.Row
ids = [r["sahibinden_id"] for r in top_bargains(conn, 9)]
frames = []
for sid in ids:
    h = pd.DataFrame(price_history(conn, sid))
    if not h.empty:
        h["car"] = sid
        frames.append(h)
conn.close()

allh = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
if not allh.empty:
    fig = px.line(allh, x="run_date", y="price", color="car",
                  facet_col="car", facet_col_wrap=3, markers=True, height=650,
                  title="Top bargain price trajectories")
    fig.update_yaxes(matches=None)
    fig.for_each_annotation(lambda a: a.update(text=a.text.split("=")[-1]))
    fig.show()
else:
    print("No bargain history yet.")
```

- [ ] **Step 5: Run the new cells to verify they execute**

Open the notebook and run the four new cells against the live `taycan.db` (it has data). Expected: the ranked table renders sorted by score descending; the three signal charts render; the per-car cell renders a price-over-time line + table; the small-multiples cell renders a faceted grid of trajectories. If `listing_signals` is empty (fresh DB), first run `.venv/bin/python -c "from db.database import init_db, get_connection; from scraper.signals import compute_signals; init_db(); c=get_connection(); compute_signals(c); c.close(); print('signals-built')"`.

- [ ] **Step 6: Commit**

```bash
git add analysis.ipynb
git commit -m "feat: notebook bargain report, signal charts + price history"
```

---

### Task 10: Update project docs

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update usage + notes in CLAUDE.md**

In `CLAUDE.md`, under `## Usage`, remove the implication that `--full` exists and reflect the new flags. Replace the usage code block with:
```bash
source .venv/bin/activate
python run_scraper.py                  # Full scan (always walks all list pages) + details for new cars
python run_scraper.py --list-only      # Search pages only (still refreshes the bargain signal)
python run_scraper.py --resume         # Resume detail scraping
python run_scraper.py --max-details 30 # Cap detail fetches this run; rest retried next run
python run_scraper.py --bot-check      # Test anti-detection on bot check sites
jupyter notebook analysis.ipynb        # Open analysis (incl. Top Bargain Candidates)
```
Add a bullet under `## Notes`:
```markdown
- Sahibinden's listing date is a *bump* date, not a creation date (~66% of cars get re-bumped). The scan no longer early-stops on date; it always does a full list sweep and only detail-scrapes truly-new cars. `scraper/signals.py` rebuilds the `listing_signals` table (bump count, price drops, days-on-market, 0-100 motivation score) each run.
```

- [ ] **Step 2: Run the full suite one last time**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: all tests PASS.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: document always-full scan + bargain signal"
```

---

## Self-Review

**1. Spec coverage:**
- Scan strategy (always full, no early-stop, inactive every run, `--full` retired) → Task 6, Task 8. ✓
- Detail-scrape only truly-new + shuffle + `--max-details` → Task 7, Task 8. ✓
- `listing_signals` table → Task 1. ✓
- Signal module + all metrics + score formula → Tasks 2, 3, 4. ✓
- Per-scan console summary, no file → Task 5 (`top_bargains`), Task 8 Step 4. ✓
- Notebook report cell + charts → Task 9. ✓
- Light hardening (shuffle, delays, cap) → Task 7, Task 8 Step 5. ✓
- Config-tunable weights/caps → Task 2 Step 1. ✓
- `compute_signals` runs in all modes incl. `--list-only`/`--resume` → Task 8 Step 4 (helper called in both paths; resume path already reaches the final `status="completed"`). ✓
- Testing: `compute_signals` + helpers against fixtures, real-DB spot check noted → Tasks 3–5; real-DB spot check is exercised in Task 9 Step 3. ✓

**2. Placeholder scan:** No "TBD/TODO"; every code step shows full code. ✓

**3. Type consistency:** `compute_car_metrics` returns the exact keys consumed by `compute_signals`' INSERT; `listing_signals` columns match the INSERT column list and the `top_bargains`/notebook `SELECT`s; `split_unscraped`/`scrape_detail_pages`/`max_details` names consistent across Tasks 7–8; `scrape_search_pages` now returns a single int and the Task 8 call site unpacks a single value. ✓
