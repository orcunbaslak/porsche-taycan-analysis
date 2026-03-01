"""Scrape sahibinden.com search result pages for Taycan listings."""

import time

from scraper.config import SEARCH_URL
from scraper.parsers import parse_listing_rows, has_next_page
from scraper.human_behavior import human_delay, maybe_long_break, simulate_list_page
from db.database import upsert_listing_summary


def scrape_search_pages(page, conn, run_id, delay=None):
    """
    Navigate through all search result pages and collect listing summaries.
    Returns total number of listings found.

    delay: If set, uses delay..delay*2 as the sleep range instead of the
           default human behavior range (5-10s).
    """
    offset = 0
    total_found = 0
    page_count = 0

    while True:
        url = SEARCH_URL if offset == 0 else f"{SEARCH_URL}?pagingOffset={offset}"
        print(f"[LIST] Loading: {url}")

        page.goto(url, wait_until="domcontentloaded")
        # Wait for results to render
        page.wait_for_selector("tr.searchResultsItem", timeout=30000)
        time.sleep(1)  # small extra wait for DOM

        # Human-like browsing before extracting content
        simulate_list_page(page)

        html = page.content()
        listings = parse_listing_rows(html)

        if not listings:
            print(f"[LIST] No listings found at offset {offset}, stopping.")
            break

        for listing in listings:
            upsert_listing_summary(conn, run_id, listing)
            total_found += 1

        page_count += 1
        print(f"[LIST] Found {len(listings)} listings (total: {total_found})")

        if not has_next_page(html):
            print("[LIST] No more pages.")
            break

        offset += 20

        # Delay between pages
        if delay is not None:
            human_delay(delay, delay * 2)
        else:
            human_delay()
        maybe_long_break(page_count)

    return total_found
