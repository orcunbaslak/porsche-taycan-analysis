import os
import tempfile

import pytest

from scraper.navigate import is_block_page, page_is_blocked, safe_goto, BlockedError


# --- pure detector ---

def test_is_block_page_detects_block_url():
    assert is_block_page("https://www.sahibinden.com/olagan-disi-kullanim") is True


def test_is_block_page_detects_block_body_markers():
    html = '<html><body class="error-page-container too-many-requests">' \
           '<h1>Olağan dışı erişim tespit ettik...</h1></body></html>'
    assert is_block_page("https://www.sahibinden.com/some-listing", html) is True


def test_is_block_page_passes_normal_page():
    assert is_block_page("https://www.sahibinden.com/ilan/.../detay",
                         "<html><ul class='classifiedInfoList'></ul></html>") is False


# --- page_is_blocked: live-page check used after a selector timeout ---

def test_page_is_blocked_true_on_block_body_even_with_normal_url():
    # The realistic case: a delayed redirect, so url still looks like a listing
    # but the body is already the rate-limit page.
    class P:
        url = "https://www.sahibinden.com/ilan/x-NEW1/detay"
        def content(self):
            return ('<html><body class="too-many-requests">'
                    '<h1>Olağan dışı erişim tespit ettik</h1></body></html>')
    assert page_is_blocked(P()) is True


def test_page_is_blocked_false_on_normal_page():
    class P:
        url = "https://www.sahibinden.com/ilan/x-NEW1/detay"
        def content(self):
            return "<html><ul class='classifiedInfoList'></ul></html>"
    assert page_is_blocked(P()) is False


def test_page_is_blocked_safe_when_session_dead():
    # A crashed session (the Page.createIsolatedWorld / "session closed" case)
    # makes content() throw — must not crash, and a normal url isn't a block.
    class P:
        url = "https://www.sahibinden.com/ilan/x-NEW1/detay"
        def content(self):
            raise Exception("Protocol error: session closed")
    assert page_is_blocked(P()) is False


# --- safe_goto raises on a block redirect ---

def test_safe_goto_raises_blocked_when_redirected_to_block_page():
    class FakePage:
        url = "https://www.sahibinden.com/olagan-disi-kullanim"
        def goto(self, url, wait_until=None):
            return None

    with pytest.raises(BlockedError):
        safe_goto(FakePage(), "https://www.sahibinden.com/ilan/x-846873854/detay")


# --- detail loop must NOT swallow a BlockedError ---

def test_detail_scraper_propagates_blocked_error(monkeypatch):
    import scraper.detail_scraper as ds
    from db.database import init_db, get_connection, create_scrape_run

    def boom(page, url):
        raise BlockedError("blocked")

    monkeypatch.setattr(ds, "safe_goto", boom)

    with tempfile.TemporaryDirectory() as d:
        db_path = os.path.join(d, "t.db")
        init_db(db_path)
        conn = get_connection(db_path)
        run_id = create_scrape_run(conn)
        conn.execute(
            "INSERT INTO listings (scrape_run_id, sahibinden_id, url, detail_scraped) "
            "VALUES (?, 'NEW1', 'http://x/NEW1', 0)",
            (run_id,),
        )
        conn.commit()

        with pytest.raises(BlockedError):
            ds.scrape_detail_pages(object(), conn, run_id)
        conn.close()


# --- detail loop: a selector timeout that is really the block page must abort ---

def _one_new_listing_db(d):
    from db.database import init_db, get_connection, create_scrape_run
    db_path = os.path.join(d, "t.db")
    init_db(db_path)
    conn = get_connection(db_path)
    run_id = create_scrape_run(conn)
    conn.execute(
        "INSERT INTO listings (scrape_run_id, sahibinden_id, url, detail_scraped) "
        "VALUES (?, 'NEW1', 'http://x/NEW1', 0)",
        (run_id,),
    )
    conn.commit()
    return conn, run_id


def test_detail_scraper_block_page_surfaces_as_timeout_aborts(monkeypatch):
    # Reproduces run 43: the rate-limit page arrives via a delayed redirect, so the
    # content selector never appears and wait_for_selector times out. The loop must
    # recognise the block and raise BlockedError instead of swallowing the timeout
    # and hammering on (which previously crashed the session and forced a Ctrl-C).
    import scraper.detail_scraper as ds

    monkeypatch.setattr(ds, "safe_goto", lambda page, url: None)
    monkeypatch.setattr(ds.time, "sleep", lambda *a, **k: None)

    class BlockedViaTimeoutPage:
        url = "https://www.sahibinden.com/ilan/x-NEW1/detay"  # url still looks normal
        def wait_for_selector(self, *a, **k):
            raise Exception("Timeout 30000ms exceeded.")
        def content(self):
            return ('<html><body class="too-many-requests">'
                    '<h1>Olağan dışı erişim tespit ettik</h1></body></html>')

    with tempfile.TemporaryDirectory() as d:
        conn, run_id = _one_new_listing_db(d)
        with pytest.raises(BlockedError):
            ds.scrape_detail_pages(BlockedViaTimeoutPage(), conn, run_id)
        conn.close()


def test_detail_scraper_genuine_timeout_is_not_a_false_block(monkeypatch):
    # A real slow/broken listing (no block markers) must NOT be misreported as a
    # block — the loop logs it and moves on, returning normally with 0 scraped.
    import scraper.detail_scraper as ds

    monkeypatch.setattr(ds, "safe_goto", lambda page, url: None)
    monkeypatch.setattr(ds.time, "sleep", lambda *a, **k: None)

    class SlowPage:
        url = "https://www.sahibinden.com/ilan/x-NEW1/detay"
        def wait_for_selector(self, *a, **k):
            raise Exception("Timeout 30000ms exceeded.")
        def content(self):
            return "<html><body>just a slow normal page</body></html>"

    with tempfile.TemporaryDirectory() as d:
        conn, run_id = _one_new_listing_db(d)
        result = ds.scrape_detail_pages(SlowPage(), conn, run_id)  # must not raise
        assert result == 0
        conn.close()
