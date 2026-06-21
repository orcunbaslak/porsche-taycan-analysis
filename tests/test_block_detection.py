import os
import tempfile

import pytest

from scraper.navigate import is_block_page, safe_goto, BlockedError


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
