import os
import tempfile

import pytest

from db.database import (
    init_db, get_connection, create_scrape_run, get_active_undetailed_listings,
)
from scraper.navigate import BlockedError
import scraper.detail_scraper as ds


def test_copy_known_details_copies_known_leaves_never_detailed():
    with tempfile.TemporaryDirectory() as d:
        db_path = os.path.join(d, "t.db")
        init_db(db_path)
        conn = get_connection(db_path)
        r1 = create_scrape_run(conn)
        r2 = create_scrape_run(conn)
        # A: detailed in r1, re-listed undetailed in r2 -> should be copied into r2
        conn.execute("INSERT INTO listings (scrape_run_id,sahibinden_id,url,detail_scraped,is_active,fuel_type)"
                     " VALUES (?,?,?,?,?,?)", (r1, "A", "http://x/A", 1, 1, "Elektrikli"))
        conn.execute("INSERT INTO listings (scrape_run_id,sahibinden_id,url,detail_scraped,is_active)"
                     " VALUES (?,?,?,?,?)", (r2, "A", "http://x/A", 0, 1))
        # B: brand new, never detailed -> must be left for the click-through drain
        conn.execute("INSERT INTO listings (scrape_run_id,sahibinden_id,url,detail_scraped,is_active)"
                     " VALUES (?,?,?,?,?)", (r2, "B", "http://x/B", 0, 1))
        conn.commit()

        assert ds.copy_known_details(conn, r2) == 1
        a = conn.execute("SELECT detail_scraped FROM listings WHERE scrape_run_id=? AND sahibinden_id='A'", (r2,)).fetchone()[0]
        b = conn.execute("SELECT detail_scraped FROM listings WHERE scrape_run_id=? AND sahibinden_id='B'", (r2,)).fetchone()[0]
        assert a == 1 and b == 0
        conn.close()


# --- the dedup'd global backlog query ---

def test_get_active_undetailed_listings_dedups_and_filters():
    with tempfile.TemporaryDirectory() as d:
        db_path = os.path.join(d, "t.db")
        init_db(db_path)
        conn = get_connection(db_path)
        r1 = create_scrape_run(conn)  # 1
        r2 = create_scrape_run(conn)  # 2

        def ins(run, sid, url, detailed, active):
            conn.execute(
                "INSERT INTO listings (scrape_run_id, sahibinden_id, url, detail_scraped, is_active) "
                "VALUES (?,?,?,?,?)", (run, sid, url, detailed, active))

        # A: detailed in run 1, re-listed undetailed in run 2 -> NOT backlog (we have its details)
        ins(r1, "A", "http://x/A", 1, 1)
        ins(r2, "A", "http://x/A", 0, 1)
        # B: never detailed, active -> IN backlog, via its LATEST row (run 2)
        ins(r1, "B", "http://x/B1", 0, 1)
        ins(r2, "B", "http://x/B2", 0, 1)
        # C: never detailed but inactive -> NOT backlog
        ins(r2, "C", "http://x/C", 0, 0)
        # D: never detailed, active, but no url -> excluded
        ins(r2, "D", "", 0, 1)
        conn.commit()

        backlog = get_active_undetailed_listings(conn)
        ids = {r["sahibinden_id"] for r in backlog}
        assert ids == {"B"}
        # must use the latest row's url (run 2), not the older one
        assert backlog[0]["url"] == "http://x/B2"
        conn.close()


# --- the drain loop ---

def _backlog(n):
    return [{"id": i, "sahibinden_id": f"S{i}", "url": f"http://x/{i}"} for i in range(n)]


def _neutralize(monkeypatch, ds):
    monkeypatch.setattr(ds, "human_delay", lambda *a, **k: None)
    monkeypatch.setattr(ds, "maybe_long_break", lambda *a, **k: None)


def test_backlog_empty_returns_zero(monkeypatch):
    import scraper.detail_scraper as ds
    monkeypatch.setattr(ds, "get_active_undetailed_listings", lambda conn: [])
    assert ds.scrape_detail_backlog(page=object(), conn=object()) == 0


def test_backlog_respects_max_details_cap(monkeypatch):
    import scraper.detail_scraper as ds
    _neutralize(monkeypatch, ds)
    monkeypatch.setattr(ds, "get_active_undetailed_listings", lambda conn: _backlog(10))
    calls = []
    monkeypatch.setattr(ds, "_scrape_one_detail",
                        lambda page, conn, l: (calls.append(l["sahibinden_id"]), True)[1])
    n = ds.scrape_detail_backlog(page=object(), conn=object(), max_details=3, shuffle=False)
    assert n == 3 and len(calls) == 3


def test_backlog_aborts_on_block(monkeypatch):
    import scraper.detail_scraper as ds
    _neutralize(monkeypatch, ds)
    monkeypatch.setattr(ds, "get_active_undetailed_listings", lambda conn: _backlog(5))

    def fake_one(page, conn, l):
        if l["sahibinden_id"] == "S2":
            raise BlockedError("blocked")
        return True
    monkeypatch.setattr(ds, "_scrape_one_detail", fake_one)
    with pytest.raises(BlockedError):
        ds.scrape_detail_backlog(page=object(), conn=object(), max_details=10, shuffle=False)


def test_backlog_continues_past_generic_error(monkeypatch):
    import scraper.detail_scraper as ds
    _neutralize(monkeypatch, ds)
    monkeypatch.setattr(ds, "get_active_undetailed_listings", lambda conn: _backlog(4))

    def fake_one(page, conn, l):
        if l["sahibinden_id"] == "S1":
            raise Exception("timeout")  # a poison listing must not abort the drain
        return True
    monkeypatch.setattr(ds, "_scrape_one_detail", fake_one)
    n = ds.scrape_detail_backlog(page=object(), conn=object(), max_details=10, shuffle=False)
    assert n == 3  # 4 attempted, 1 failed, drain kept going
