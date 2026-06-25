"""Scrape individual listing detail pages from sahibinden.com."""

import random
import time

from scraper.parsers import parse_detail_page, _extract_model
from scraper.human_behavior import (
    human_delay, maybe_long_break, simulate_detail_page, simulate_list_page,
)
from scraper.navigate import (
    safe_goto, click_listing, is_block_page, page_is_blocked, BlockedError,
)
from scraper.config import (
    SEARCH_URL, NAVIGATION_TIMEOUT, DETAIL_BURST_MIN_GAP, DETAIL_BURST_MAX_GAP,
)
from db.database import (
    get_unscraped_listings,
    get_active_undetailed_listings,
    get_previously_scraped_ids,
    copy_from_previous_run,
    update_listing_details,
    update_listing_model,
    insert_damage_parts,
    insert_features,
)


def split_unscraped(unscraped, prev_scraped, max_details=None, shuffle=True, rng=random):
    """Split unscraped listings into (to_copy, to_scrape).

    to_copy:   already detail-scraped in a previous run -> copy, no network.
    to_scrape: truly new -> fetch detail page. Optionally shuffled (de-patterns the
               request order) and capped at max_details (remainder is retried next run
               because it keeps detail_scraped=0).
    """
    to_copy = [l for l in unscraped if l["sahibinden_id"] in prev_scraped]
    to_scrape = [l for l in unscraped if l["sahibinden_id"] not in prev_scraped]
    if shuffle:
        rng.shuffle(to_scrape)
    if max_details is not None:
        to_scrape = to_scrape[:max_details]
    return to_copy, to_scrape


def _scrape_one_detail(page, conn, listing):
    """Fetch and persist one detail page. Returns True on success.

    Raises BlockedError if the rate-limit page is detected (caller must abort).
    Any other failure propagates to the caller, which logs it and moves on.
    """
    listing_id = listing["id"]
    url = listing["url"]
    sah_id = listing["sahibinden_id"]

    safe_goto(page, url)
    # Wait for main content. A timeout here is often the rate-limit page: it arrives
    # via a delayed/client-side redirect (so safe_goto's URL check passed) and carries
    # none of the listing selectors. Treat a timeout-on-a-block-page as BlockedError so
    # we abort instead of eating 30s and hammering the next listing into a session crash.
    try:
        page.wait_for_selector("ul.classifiedInfoList", timeout=30000)
    except Exception:
        if page_is_blocked(page):
            raise BlockedError(
                f"Block page detected while scraping {sah_id} — the content selector "
                "never appeared (delayed redirect to the rate-limit page). Stopping "
                "so we don't keep hammering it."
            )
        raise
    time.sleep(1)

    # Human-like browsing before extracting content
    simulate_detail_page(page)

    html = page.content()
    if is_block_page(page.url, html):
        raise BlockedError(f"Block page detected while scraping {sah_id}.")
    _persist_detail(conn, listing_id, html)
    return True


def _persist_detail(conn, listing_id, html):
    """Parse a detail page's HTML and write its fields, damage parts and features.
    Shared by the goto path (_scrape_one_detail) and the click-through drain."""
    data = parse_detail_page(html)

    damage_parts = data.pop("damage_parts", [])
    features = data.pop("features", [])

    # Resolve model from detail page if list page couldn't extract it
    model_detail = data.get("model_detail")
    if model_detail:
        model = _extract_model(model_detail)
        if model:
            update_listing_model(conn, listing_id, model)

    update_listing_details(conn, listing_id, data)
    if damage_parts:
        insert_damage_parts(conn, listing_id, damage_parts)
    if features:
        insert_features(conn, listing_id, features)


def _scrape_listings_loop(page, conn, listings, delay, progress_cb, tag):
    """Scrape a list of listing rows one by one with human pacing.

    Re-raises BlockedError (abort the run); logs and continues on any other error.
    Returns the count successfully scraped.
    """
    scraped = 0
    n = len(listings)
    for i, listing in enumerate(listings):
        sah_id = listing["sahibinden_id"]
        print(f"[{tag}] ({i + 1}/{n}) Scraping {sah_id}: {listing['url']}")
        try:
            if _scrape_one_detail(page, conn, listing):
                scraped += 1
        except BlockedError:
            raise  # don't swallow — abort so we stop hammering the block page
        except Exception as e:
            print(f"[{tag}] Error scraping {sah_id}: {e}")

        if progress_cb:
            progress_cb(i + 1, n, scraped)

        if i < n - 1:
            if delay is not None:
                human_delay(delay, delay * 2)
            else:
                human_delay()
            maybe_long_break(i + 1)
    return scraped


def scrape_detail_backlog(page, conn, delay=None, progress_cb=None, max_details=None,
                          shuffle=True, rng=random):
    """Drain the GLOBAL active detail backlog.

    Unlike scrape_detail_pages (which is bound to one run's rows), this fetches every
    active listing that has never been detail-scraped in ANY run — deduped by
    sahibinden_id via get_active_undetailed_listings — so it is robust to partial/
    interrupted runs. No list sweep: the whole request budget goes to the gap.
    Capped at max_details (remainder drains over later runs); aborts cleanly on a block.
    Returns the count scraped this run.
    """
    backlog = get_active_undetailed_listings(conn)
    total = len(backlog)
    if total == 0:
        print("[DRAIN] Backlog empty — every active listing already has details.")
        return 0

    if shuffle:
        rng.shuffle(backlog)
    batch = backlog[:max_details] if max_details is not None else backlog

    print(f"[DRAIN] {total} active listing(s) need details; fetching up to {len(batch)} this run...")
    scraped = _scrape_listings_loop(page, conn, batch, delay, progress_cb, tag="DRAIN")
    print(f"[DRAIN] Done: {scraped}/{len(batch)} scraped this run; backlog now ~{total - scraped}.")
    return scraped


def _wait_results(page):
    """Wait for the search-results grid; raise BlockedError if it's really the block page."""
    try:
        page.wait_for_selector("tr.searchResultsItem", timeout=30000)
    except Exception:
        if page_is_blocked(page):
            raise BlockedError("Block page while loading search results during drain.")
        raise


def scrape_detail_backlog_via_clicks(browser, page, conn, max_details=None, progress_cb=None):
    """Drain the global detail backlog the human way, to survive PerimeterX.

    Strategy (validated 2026-06-25): warm up ONCE with the PX sensor armed (load the
    search page with human mouse movement) to ensure a healthy `_px3` token, then keep
    the sensor DISARMED for the whole drain so it can't re-score us, navigating to each
    backlog listing by CLICKING its real anchor (trusted click + Referer + Sec-Fetch-Site:
    same-origin). Walks the search pages and opens the backlog cars found on each, going
    back like a human between them. Aborts cleanly (BlockedError) if the token ever fails.
    Returns count scraped.
    """
    backlog = {r["sahibinden_id"]: r["id"] for r in get_active_undetailed_listings(conn)}
    if not backlog:
        print("[DRAIN] Backlog empty — every active listing already has details.")
        return 0
    target = len(backlog) if max_details is None else min(max_details, len(backlog))
    print(f"[DRAIN] {len(backlog)} active listing(s) need details; "
          f"fetching up to {target} via human click-through...")

    scraped = 0
    offset = 0
    pages_walked = 0
    while scraped < target and backlog and pages_walked <= 7:
        url = SEARCH_URL if offset == 0 else f"{SEARCH_URL}&pagingOffset={offset}"
        # ARM for every list-page load: re-warm `_px3` and let the sensor clear any JS
        # challenge (a disarmed search-page load can hang waiting for the grid), with
        # human mouse movement for a high-trust token.
        browser.arm_px(page)
        safe_goto(page, url)
        _wait_results(page)
        simulate_list_page(page)
        # DISARM for the detail-click burst on this page (rides the fresh token).
        browser.disarm_px(page)

        ids_here = page.evaluate(
            "() => Array.from(document.querySelectorAll('tr.searchResultsItem[data-id]'))"
            ".map(t => t.getAttribute('data-id'))"
        )
        if not ids_here:
            break

        for sid in [s for s in ids_here if s in backlog]:
            if scraped >= target:
                break
            try:
                click_listing(page, sid)
                _persist_detail(conn, backlog[sid], page.content())
                scraped += 1
                backlog.pop(sid, None)
                print(f"[DRAIN] ({scraped}/{target}) {sid} OK")
                if progress_cb:
                    progress_cb(scraped, target, scraped)
            except BlockedError:
                raise  # token failed mid-drain — abort so we don't hammer the block
            except LookupError:
                continue  # anchor not on this page (lazy render); skip
            except Exception as e:
                print(f"[DRAIN] error {sid}: {e}")
            # Back to the (bfcached) results page — disarmed is fine, no new sensor load.
            # If go_back fails, re-arm to reload the list robustly, then disarm again.
            try:
                page.go_back(wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT)
                _wait_results(page)
            except Exception:
                browser.arm_px(page)
                safe_goto(page, url)
                _wait_results(page)
                browser.disarm_px(page)
            time.sleep(random.uniform(DETAIL_BURST_MIN_GAP, DETAIL_BURST_MAX_GAP))

        offset += 50
        pages_walked += 1

    print(f"[DRAIN] Done: {scraped} scraped via human click-through.")
    return scraped


def copy_known_details(conn, run_id):
    """Copy detail data from prior runs into THIS run's rows for cars already detailed
    before (no network), so the freshly-swept list rows are complete. Never-detailed
    cars are left untouched — they get fetched by the click-through drain. Returns the
    count copied.
    """
    prev_scraped = get_previously_scraped_ids(conn, run_id)
    copied = 0
    for listing in get_unscraped_listings(conn, run_id):
        if listing["sahibinden_id"] in prev_scraped:
            if copy_from_previous_run(conn, run_id, listing["sahibinden_id"]):
                copied += 1
    return copied


def scrape_detail_pages(page, conn, run_id, delay=None, progress_cb=None, max_details=None):
    """
    Scrape detail pages for all unscraped listings in the given run.
    Copies data from previous runs when available to avoid re-scraping.
    Returns number of successfully processed details (copied + scraped).

    delay: If set, uses delay..delay*2 as the sleep range instead of the
           default human behavior range (5-10s).
    """
    # Get previously scraped IDs for cross-run dedup
    prev_scraped = get_previously_scraped_ids(conn, run_id)

    unscraped = get_unscraped_listings(conn, run_id)
    total = len(unscraped)

    if total == 0:
        print("[DETAIL] All listings already scraped.")
        return 0

    # Split into "can copy" and "need to scrape" (shuffled + optionally capped)
    to_copy, to_scrape = split_unscraped(unscraped, prev_scraped, max_details=max_details)

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
    scraped = _scrape_listings_loop(page, conn, to_scrape, delay, progress_cb, tag="DETAIL")

    print(f"[DETAIL] Done: {copied} copied + {scraped} scraped = {copied + scraped} total")
    return copied + scraped
