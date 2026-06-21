#!/usr/bin/env python3
"""CLI entry point for the Taycan scraper."""

import argparse
import sys

from db.database import (
    init_db,
    get_connection,
    create_scrape_run,
    finish_scrape_run,
    get_latest_run_id,
    get_run_stats,
    mark_inactive_listings,
)
from scraper.browser import BrowserManager
from scraper.list_scraper import scrape_search_pages
from scraper.detail_scraper import scrape_detail_pages
from scraper.navigate import safe_goto, BlockedError
from scraper.signals import compute_signals, top_bargains
from scraper.config import REPORT_TOP_N, DEFAULT_MAX_DETAILS


BOT_CHECK_URLS = [
    "https://www.browserscan.net/bot-detection",
    "https://deviceandbrowserinfo.com/are_you_a_bot",
]


def _run_bot_check():
    """Open bot detection test pages and wait for user to inspect."""
    print("=== Bot Detection Check ===")
    with BrowserManager() as browser:
        for url in BOT_CHECK_URLS:
            print(f"Opening: {url}")
            tab = browser.new_page()
            safe_goto(tab, url)
            tab.bring_to_front()
            print("  Check the Chrome window. Press Enter to continue...")
            input()
    print("Done.")


def progress_bar(current, total, scraped):
    pct = current / total * 100 if total else 0
    bar_len = 40
    filled = int(bar_len * current / total) if total else 0
    bar = "█" * filled + "░" * (bar_len - filled)
    print(f"\r  [{bar}] {current}/{total} ({pct:.0f}%) — {scraped} OK", end="", flush=True)
    if current == total:
        print()


def _report_signal(conn):
    """Recompute the bargain signal and print the top candidates (full report in the notebook)."""
    print("\n=== Computing bargain signal ===")
    compute_signals(conn)
    bargains = top_bargains(conn, REPORT_TOP_N)
    if bargains:
        print("Top bargain candidates (full report in analysis.ipynb):")
        for r in bargains:
            price = f"{r['current_price']:,}" if r["current_price"] is not None else "?"
            print(f"  score {r['motivation_score']:.0f} | {r['model']} {r['year']} "
                  f"| {price} TL | -{r['price_drop_pct']:.0f}% | "
                  f"{r['bump_count']} bumps | {r['days_on_market']}d | {r['url']}")


def main():
    parser = argparse.ArgumentParser(description="Scrape Porsche Taycan listings from sahibinden.com")
    parser.add_argument("--list-only", action="store_true", help="Only scrape search result pages")
    parser.add_argument("--resume", action="store_true", help="Resume detail scraping for the latest run")
    parser.add_argument("--delay", type=float, default=None,
                        help="Override base delay between requests (seconds). Uses delay..delay*2 range. Default: 5-10s human delay.")
    parser.add_argument("--max-details", type=int, default=DEFAULT_MAX_DETAILS,
                        help=f"Cap detail-page fetches this run; remainder retried next run "
                             f"(default {DEFAULT_MAX_DETAILS}; pass a large number to disable).")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    parser.add_argument("--bot-check", action="store_true", help="Open bot detection test pages and wait")
    args = parser.parse_args()

    if args.bot_check:
        _run_bot_check()
        return

    # Initialize database
    init_db()
    conn = get_connection()

    if args.resume:
        run_id = get_latest_run_id(conn)
        if not run_id:
            print("No previous scrape run found. Run without --resume first.")
            sys.exit(1)
        stats = get_run_stats(conn, run_id)
        print(f"Resuming run #{run_id}: {stats['detail_scraped']}/{stats['total']} details scraped")
    else:
        run_id = create_scrape_run(conn)
        print(f"Started scrape run #{run_id}")

    status = "failed"
    total_listings = 0

    try:
        with BrowserManager(headless=args.headless) as browser:
            page = browser.new_page()

            if not args.resume:
                # Step 1: Scrape search result pages (always a full sweep)
                print("\n=== Phase 1: Scraping search results ===")
                total_listings = scrape_search_pages(page, conn, run_id, delay=args.delay)
                print(f"\nFound {total_listings} listings total.")

                # Full sweep every run -> always safe to mark inactive.
                deactivated = mark_inactive_listings(conn, run_id)
                if deactivated:
                    print(f"Marked {deactivated} listings as inactive (no longer on sahibinden).")

                if args.list_only:
                    _report_signal(conn)
                    status = "completed"
                    print("\n--list-only mode: skipping detail scraping.")
                    return

            if not args.list_only:
                # Step 2: Scrape detail pages (copies from previous runs when possible)
                print("\n=== Phase 2: Scraping listing details ===")
                processed = scrape_detail_pages(page, conn, run_id, delay=args.delay,
                                                progress_cb=progress_bar, max_details=args.max_details)
                stats = get_run_stats(conn, run_id)
                total_listings = stats["total"]
                print(f"\nDetail scraping complete: {stats['detail_scraped']}/{stats['total']}")

            _report_signal(conn)
            status = "completed"

    except KeyboardInterrupt:
        print("\n\nInterrupted by user.")
        status = "interrupted"
    except BlockedError as e:
        print(f"\n[BLOCKED] sahibinden rate-limited us: {e}")
        print("Stopped early to avoid making it worse. Let the profile/IP cool down "
              "before the next run, and keep --max-details small.")
        status = "blocked"
        try:
            # The list sweep that already ran still feeds the bargain signal.
            _report_signal(conn)
        except Exception:
            pass
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        status = "failed"
    finally:
        finish_scrape_run(conn, run_id, total_listings, status)
        print(f"\nScrape run #{run_id} finished with status: {status}")

        if status in ("failed", "interrupted"):
            try:
                answer = input(
                    "\nMark this run as successful for date tracking in the next scan? (y/N): "
                ).strip().lower()
                if answer == "y":
                    conn.execute(
                        "UPDATE scrape_runs SET status='completed' WHERE id=?",
                        (run_id,),
                    )
                    conn.commit()
                    print(f"Run #{run_id} marked as completed for date tracking.")
            except (EOFError, KeyboardInterrupt):
                pass

        conn.close()


if __name__ == "__main__":
    main()
