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
