"""Scrape sahibinden.com search result pages for Taycan listings."""

import time

from scraper.config import SEARCH_URL
from scraper.parsers import parse_listing_rows, has_next_page
from scraper.human_behavior import human_delay, maybe_long_break, simulate_list_page
from scraper.navigate import safe_goto, is_block_page, page_is_blocked, BlockedError
from db.database import upsert_listing_summary, get_all_known_ids


def _drop_decoy_rows(page, listings, known_real):
    """Drop phantom `searchResultsItem` rows that sahibinden injects to catch row-parsing
    bots. Two independent checks:

    1. Visibility — real listings always render; decoys are hidden (display:none → no
       offsetParent / zero height). This is the primary, rotation-proof signal.
    2. ID range — real listing IDs are 10 digits (~1.0–1.3B); the decoys use out-of-band
       9-digit IDs (~846M). A sub-10-digit *numeric* ID is treated as a decoy UNLESS we've
       already confirmed it real (detail-scraped before) — that preserves the one genuine
       old 9-digit car (985568902) and any future real one, and also catches decoys hidden
       by tricks offsetParent misses (visibility:hidden, opacity:0, off-screen).

    Fail-open on the visibility read (keep rows) so a dead/odd DOM never drops real cars.
    """
    try:
        visible = set(page.evaluate(
            "() => Array.from(document.querySelectorAll('tr.searchResultsItem[data-id]'))"
            ".filter(tr => tr.offsetParent !== null && tr.getBoundingClientRect().height > 0)"
            ".map(tr => tr.getAttribute('data-id'))"))
    except Exception:
        visible = None

    kept, dropped_hidden, dropped_id = [], 0, 0
    for l in listings:
        sid = str(l["sahibinden_id"])
        if visible is not None and sid not in visible:
            dropped_hidden += 1
            continue
        if sid.isdigit() and len(sid) < 10 and sid not in known_real:
            dropped_id += 1
            continue
        kept.append(l)
    if dropped_hidden or dropped_id:
        print(f"[LIST] dropped decoy rows: {dropped_hidden} hidden, {dropped_id} out-of-range ID")
    return kept


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
    # IDs we've ever successfully detail-scraped = confirmed-real, exempt from the
    # 9-digit decoy check (protects the one genuine old 9-digit car, 985568902).
    known_real = {str(r["sahibinden_id"]) for r in
                  conn.execute("SELECT DISTINCT sahibinden_id FROM listings WHERE detail_scraped=1")}
    offset = 0
    total_found = 0
    page_count = 0

    while True:
        url = SEARCH_URL if offset == 0 else f"{SEARCH_URL}&pagingOffset={offset}"
        print(f"[LIST] Loading: {url}")

        safe_goto(page, url)
        # A timeout here can be the rate-limit page (no results selector, arrived
        # via a delayed redirect) — surface it as BlockedError, not a generic crash.
        try:
            page.wait_for_selector("tr.searchResultsItem", timeout=30000)
        except Exception:
            if page_is_blocked(page):
                raise BlockedError(
                    f"Block page detected during list scan at offset {offset} "
                    "(results selector never appeared — delayed redirect to the "
                    "rate-limit page)."
                )
            raise
        time.sleep(1)  # small extra wait for DOM

        simulate_list_page(page)

        html = page.content()
        if is_block_page(page.url, html):
            raise BlockedError(f"Block page detected during list scan at offset {offset}.")
        listings = _drop_decoy_rows(page, parse_listing_rows(html), known_real)

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
