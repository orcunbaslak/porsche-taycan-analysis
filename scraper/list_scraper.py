"""Scrape sahibinden.com search result pages for Taycan listings."""

import time

from scraper.config import SEARCH_URL
from scraper.parsers import parse_listing_rows, has_next_page
from scraper.human_behavior import human_delay, maybe_long_break, simulate_list_page
from scraper.navigate import safe_goto
from db.database import upsert_listing_summary, get_all_known_ids


def scrape_search_pages(page, conn, run_id, delay=None):
    """
    Walk every search result page (sorted date_desc) and upsert listing summaries.

    The scan is always full: sahibinden's displayed date is a volatile bump date,
    so date/known-based early-stopping was unreliable. The full list sweep is cheap
    (~6 pages) and feeds both the bargain signal and inactive detection; cost control
    lives in the detail phase, which only fetches truly-new cars.

    delay: If set, uses delay..delay*2 as the sleep range instead of the default
           human behavior range (5-10s).
    Returns total_found (int).
    """
    known_ids = get_all_known_ids(conn)
    offset = 0
    total_found = 0
    page_count = 0

    while True:
        url = SEARCH_URL if offset == 0 else f"{SEARCH_URL}&pagingOffset={offset}"
        print(f"[LIST] Loading: {url}")

        safe_goto(page, url)
        page.wait_for_selector("tr.searchResultsItem", timeout=30000)
        time.sleep(1)  # small extra wait for DOM

        simulate_list_page(page)

        html = page.content()
        listings = parse_listing_rows(html)

        if not listings:
            print(f"[LIST] No listings found at offset {offset}, stopping.")
            break

        new_count = sum(1 for l in listings if l["sahibinden_id"] not in known_ids)

        for listing in listings:
            upsert_listing_summary(conn, run_id, listing)
            known_ids.add(listing["sahibinden_id"])
            total_found += 1

        page_count += 1
        print(f"[LIST] Found {len(listings)} listings ({new_count} new, total: {total_found})")

        if not has_next_page(html):
            print("[LIST] No more pages.")
            break

        offset += 50

        if delay is not None:
            human_delay(delay, delay * 2)
        else:
            human_delay()
        maybe_long_break(page_count)

    return total_found
