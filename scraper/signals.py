"""Compute a per-car bargain / motivation signal from cross-run listing history."""

from collections import defaultdict
from datetime import datetime

from scraper.parsers import parse_listing_date
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
