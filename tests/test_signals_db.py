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
