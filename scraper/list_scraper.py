"""Scrape sahibinden.com search result pages for Taycan listings."""

import time

from scraper.config import SEARCH_URL
from scraper.parsers import parse_listing_rows, parse_listing_date, has_next_page
from scraper.human_behavior import human_delay, maybe_long_break, simulate_list_page
from scraper.navigate import safe_goto
from db.database import upsert_listing_summary, get_all_known_ids, get_last_successful_run_date


def scrape_search_pages(page, conn, run_id, delay=None, full=False):
    """
    Navigate through all search result pages and collect listing summaries.
    Results are sorted by date descending. Stops early when all listings
    on a page are already in the database (unless full=True).
    Returns (total_found, full_scan) where full_scan is True if all pages
    were visited (no early stop).

    delay: If set, uses delay..delay*2 as the sleep range instead of the
           default human behavior range (5-10s).
    full:  If True, scan all pages without early stop (needed for inactive detection).
    """
    known_ids = get_all_known_ids(conn)
    last_success = get_last_successful_run_date(conn)
    if last_success:
        print(f"[LIST] Last successful scan: {last_success.strftime('%d.%m.%Y')}")
    offset = 0
    total_found = 0
    page_count = 0
    full_scan = True

    while True:
        url = SEARCH_URL if offset == 0 else f"{SEARCH_URL}&pagingOffset={offset}"
        print(f"[LIST] Loading: {url}")

        safe_goto(page, url)
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

        # Check how many are already known
        new_count = sum(1 for l in listings if l["sahibinden_id"] not in known_ids)

        for listing in listings:
            upsert_listing_summary(conn, run_id, listing)
            known_ids.add(listing["sahibinden_id"])
            total_found += 1

        page_count += 1
        print(f"[LIST] Found {len(listings)} listings ({new_count} new, total: {total_found})")

        if not full:
            # Stop if all IDs on this page are already known
            if new_count == 0:
                print("[LIST] All listings on this page already in DB, stopping early.")
                full_scan = False
                break

            # Stop if all listing dates are before the last successful scan
            if last_success:
                page_dates = [parse_listing_date(l["listing_date"]) for l in listings]
                valid_dates = [d for d in page_dates if d is not None]
                if valid_dates and all(d < last_success for d in valid_dates):
                    print(f"[LIST] All listings on this page dated before last scan ({last_success.strftime('%d.%m.%Y')}), stopping early.")
                    full_scan = False
                    break

        if not has_next_page(html):
            print("[LIST] No more pages.")
            break

        offset += 50

        # Delay between pages
        if delay is not None:
            human_delay(delay, delay * 2)
        else:
            human_delay()
        maybe_long_break(page_count)

    return total_found, full_scan
