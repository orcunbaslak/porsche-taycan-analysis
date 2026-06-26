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
    monkeypatch.setattr(ls.time, "sleep", lambda *a, **k: None)

    class FakePage:
        url = "https://www.sahibinden.com/porsche-taycan-elektrik"
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


def test_hidden_decoy_rows_are_dropped(monkeypatch):
    # One page with a hidden honeypot row (846840848, display:none) among two real rows.
    rows = [
        {"sahibinden_id": "1324000001", "listing_date": "Bugün"},
        {"sahibinden_id": "846840848", "listing_date": "Bugün"},   # phantom (hidden)
        {"sahibinden_id": "1324000002", "listing_date": "Bugün"},
    ]

    def fake_parse(html):
        return [dict(url=None, title=None, model=None, year=None, km=None, color=None,
                     price=None, currency="TL", location_city=None, location_district=None, **r)
                for r in rows]

    monkeypatch.setattr(ls, "parse_listing_rows", fake_parse)
    monkeypatch.setattr(ls, "has_next_page", lambda html: False)
    monkeypatch.setattr(ls, "safe_goto", lambda page, url: None)
    monkeypatch.setattr(ls, "simulate_list_page", lambda page: None)
    monkeypatch.setattr(ls, "human_delay", lambda *a, **k: None)
    monkeypatch.setattr(ls, "maybe_long_break", lambda *a, **k: None)
    monkeypatch.setattr(ls.time, "sleep", lambda *a, **k: None)

    class FakePage:
        url = "https://www.sahibinden.com/porsche-taycan-elektrik"
        def wait_for_selector(self, *a, **k):
            return None
        def content(self):
            return "<html></html>"
        def evaluate(self, script):
            # the DOM reports only the two real rows as visible; the phantom is display:none
            return ["1324000001", "1324000002"]

    with tempfile.TemporaryDirectory() as d:
        db_path = os.path.join(d, "t.db")
        init_db(db_path)
        conn = get_connection(db_path)
        run_id = create_scrape_run(conn)
        total = ls.scrape_search_pages(FakePage(), conn, run_id)
        ids = {r["sahibinden_id"] for r in
               conn.execute("SELECT DISTINCT sahibinden_id FROM listings").fetchall()}
        conn.close()

    assert ids == {"1324000001", "1324000002"}   # hidden phantom 846840848 dropped
    assert total == 2


def test_nine_digit_ids_always_dropped(monkeypatch):
    # Second check: any sub-10-digit numeric ID is a decoy, even if "visible" and even if it
    # was detail-scraped before. Real listing IDs are always 10 digits.
    rows = [
        {"sahibinden_id": "1324000003", "listing_date": "Bugün"},   # real 10-digit
        {"sahibinden_id": "846999999", "listing_date": "Bugün"},    # 9-digit decoy
        {"sahibinden_id": "985568902", "listing_date": "Bugün"},    # 9-digit, detailed before — still dropped
    ]

    def fake_parse(html):
        return [dict(url=None, title=None, model=None, year=None, km=None, color=None,
                     price=None, currency="TL", location_city=None, location_district=None, **r)
                for r in rows]

    monkeypatch.setattr(ls, "parse_listing_rows", fake_parse)
    monkeypatch.setattr(ls, "has_next_page", lambda html: False)
    monkeypatch.setattr(ls, "safe_goto", lambda page, url: None)
    monkeypatch.setattr(ls, "simulate_list_page", lambda page: None)
    monkeypatch.setattr(ls, "human_delay", lambda *a, **k: None)
    monkeypatch.setattr(ls, "maybe_long_break", lambda *a, **k: None)
    monkeypatch.setattr(ls.time, "sleep", lambda *a, **k: None)

    class FakePage:
        url = "https://www.sahibinden.com/porsche-taycan-elektrik"
        def wait_for_selector(self, *a, **k):
            return None
        def content(self):
            return "<html></html>"
        def evaluate(self, script):
            return ["1324000003", "846999999", "985568902"]   # all "visible" — isolate the ID check

    with tempfile.TemporaryDirectory() as d:
        db_path = os.path.join(d, "t.db")
        init_db(db_path)
        conn = get_connection(db_path)
        prev = create_scrape_run(conn)
        # Even a previously detail-scraped 9-digit ID is dropped now (no exception).
        conn.execute("INSERT INTO listings (scrape_run_id, sahibinden_id, url, detail_scraped) "
                     "VALUES (?, '985568902', 'http://x/985', 1)", (prev,))
        conn.commit()
        run_id = create_scrape_run(conn)
        total = ls.scrape_search_pages(FakePage(), conn, run_id)
        ids = {r["sahibinden_id"] for r in conn.execute(
            "SELECT DISTINCT sahibinden_id FROM listings WHERE scrape_run_id=?", (run_id,)).fetchall()}
        conn.close()

    assert ids == {"1324000003"}   # both 9-digit IDs dropped
    assert total == 1
