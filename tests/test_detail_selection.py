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
