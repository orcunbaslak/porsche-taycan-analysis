"""Navigation helper with retry for transient DNS errors."""

import time


def safe_goto(page, url, retries=3, wait_between=10):
    """Navigate to a URL, retrying on DNS resolution errors."""
    for attempt in range(retries):
        try:
            page.goto(url, wait_until="domcontentloaded")
            return
        except Exception as e:
            if "ERR_NAME_NOT_RESOLVED" in str(e) and attempt < retries - 1:
                print(f"[NAV] DNS not resolved, retrying in {wait_between}s... ({attempt + 1}/{retries})")
                time.sleep(wait_between)
            else:
                raise
