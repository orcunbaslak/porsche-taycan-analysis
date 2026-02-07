"""Scrape individual listing detail pages from sahibinden.com."""

import random
import time

from scraper.config import DEFAULT_DELAY
from scraper.parsers import parse_detail_page, _extract_model
from db.database import (
    get_unscraped_listings,
    get_previously_scraped_ids,
    copy_from_previous_run,
    update_listing_details,
    update_listing_model,
    insert_damage_parts,
    insert_features,
)


def scrape_detail_pages(page, conn, run_id, delay=DEFAULT_DELAY, progress_cb=None):
    """
    Scrape detail pages for all unscraped listings in the given run.
    Copies data from previous runs when available to avoid re-scraping.
    Returns number of successfully processed details (copied + scraped).
    """
    # Get previously scraped IDs for cross-run dedup
    prev_scraped = get_previously_scraped_ids(conn, run_id)

    unscraped = get_unscraped_listings(conn, run_id)
    total = len(unscraped)

    if total == 0:
        print("[DETAIL] All listings already scraped.")
        return 0

    # Split into "can copy" and "need to scrape"
    to_copy = [l for l in unscraped if l["sahibinden_id"] in prev_scraped]
    to_scrape = [l for l in unscraped if l["sahibinden_id"] not in prev_scraped]

    copied = 0
    scraped = 0

    # Phase 1: Copy from previous runs (no browser needed)
    if to_copy:
        print(f"[DETAIL] Copying {len(to_copy)} listings from previous runs...")
        for listing in to_copy:
            if copy_from_previous_run(conn, run_id, listing["sahibinden_id"]):
                copied += 1
        print(f"[DETAIL] Copied {copied}/{len(to_copy)} listings.")

    # Phase 2: Scrape new listings
    if not to_scrape:
        print("[DETAIL] No new listings to scrape.")
        return copied

    print(f"[DETAIL] {len(to_scrape)} new listings to scrape...")

    for i, listing in enumerate(to_scrape):
        listing_id = listing["id"]
        url = listing["url"]
        sah_id = listing["sahibinden_id"]

        print(f"[DETAIL] ({i+1}/{len(to_scrape)}) Scraping {sah_id}: {url}")

        try:
            page.goto(url, wait_until="domcontentloaded")
            # Wait for main content
            page.wait_for_selector("ul.classifiedInfoList", timeout=30000)
            time.sleep(1)

            html = page.content()
            data = parse_detail_page(html)

            # Extract nested data before updating
            damage_parts = data.pop("damage_parts", [])
            features = data.pop("features", [])

            # Resolve model from detail page if list page couldn't extract it
            model_detail = data.get("model_detail")
            if model_detail:
                model = _extract_model(model_detail)
                if model:
                    update_listing_model(conn, listing_id, model)

            # Update listing
            update_listing_details(conn, listing_id, data)

            # Insert damage parts
            if damage_parts:
                insert_damage_parts(conn, listing_id, damage_parts)

            # Insert features
            if features:
                insert_features(conn, listing_id, features)

            scraped += 1

        except Exception as e:
            print(f"[DETAIL] Error scraping {sah_id}: {e}")

        if progress_cb:
            progress_cb(i + 1, len(to_scrape), scraped)

        if i < len(to_scrape) - 1:
            _sleep(delay)

    print(f"[DETAIL] Done: {copied} copied + {scraped} scraped = {copied + scraped} total")
    return copied + scraped


def _sleep(delay):
    """Sleep with ±30% randomness."""
    actual = delay * (0.7 + random.random() * 0.6)
    time.sleep(actual)
