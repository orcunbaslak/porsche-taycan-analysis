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
)
from scraper.browser import BrowserManager
from scraper.list_scraper import scrape_search_pages
from scraper.detail_scraper import scrape_detail_pages


def progress_bar(current, total, scraped):
    pct = current / total * 100 if total else 0
    bar_len = 40
    filled = int(bar_len * current / total) if total else 0
    bar = "█" * filled + "░" * (bar_len - filled)
    print(f"\r  [{bar}] {current}/{total} ({pct:.0f}%) — {scraped} OK", end="", flush=True)
    if current == total:
        print()


def main():
    parser = argparse.ArgumentParser(description="Scrape Porsche Taycan listings from sahibinden.com")
    parser.add_argument("--list-only", action="store_true", help="Only scrape search result pages")
    parser.add_argument("--resume", action="store_true", help="Resume detail scraping for the latest run")
    parser.add_argument("--delay", type=float, default=4.0, help="Base delay between requests (seconds)")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    args = parser.parse_args()

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
                # Step 1: Scrape search result pages
                print("\n=== Phase 1: Scraping search results ===")
                total_listings = scrape_search_pages(page, conn, run_id, delay=args.delay)
                print(f"\nFound {total_listings} listings total.")

                if args.list_only:
                    status = "completed"
                    print("\n--list-only mode: skipping detail scraping.")
                    return

            if not args.list_only:
                # Step 2: Scrape detail pages (copies from previous runs when possible)
                print("\n=== Phase 2: Scraping listing details ===")
                processed = scrape_detail_pages(page, conn, run_id, delay=args.delay, progress_cb=progress_bar)
                stats = get_run_stats(conn, run_id)
                total_listings = stats["total"]
                print(f"\nDetail scraping complete: {stats['detail_scraped']}/{stats['total']}")

            status = "completed"

    except KeyboardInterrupt:
        print("\n\nInterrupted by user.")
        status = "interrupted"
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        status = "failed"
    finally:
        finish_scrape_run(conn, run_id, total_listings, status)
        conn.close()
        print(f"\nScrape run #{run_id} finished with status: {status}")


if __name__ == "__main__":
    main()
