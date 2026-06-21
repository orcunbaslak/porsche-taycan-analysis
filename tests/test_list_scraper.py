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
