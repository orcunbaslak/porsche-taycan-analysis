"""Navigation helper with retry for transient DNS errors and bot-block detection."""

import time


class BlockedError(Exception):
    """Raised when sahibinden serves its 'olağan dışı erişim' (too-many-requests) page."""


# Sahibinden's rate-limit / anti-bot page: redirects to this path and/or serves a
# body with these markers (verified against a live block, support code G0TFUT2T-*).
_BLOCK_URL_MARKER = "olagan-disi-kullanim"
_BLOCK_BODY_MARKERS = ("too-many-requests", "Olağan dışı erişim", "tooManyRequestHelp")


def is_block_page(url, html=None):
    """Return True if the current URL or page body is sahibinden's block page."""
    if url and _BLOCK_URL_MARKER in url:
        return True
    if html and any(marker in html for marker in _BLOCK_BODY_MARKERS):
        return True
    return False


def safe_goto(page, url, retries=3, wait_between=10):
    """Navigate to a URL, retrying on DNS errors. Raises BlockedError if rate-limited."""
    for attempt in range(retries):
        try:
            page.goto(url, wait_until="domcontentloaded")
            if is_block_page(page.url):
                raise BlockedError(
                    f"sahibinden served its rate-limit page (redirected to {page.url}). "
                    "Stopping to avoid digging the hole deeper — cool the profile/IP down."
                )
            return
        except BlockedError:
            raise
        except Exception as e:
            if "ERR_NAME_NOT_RESOLVED" in str(e) and attempt < retries - 1:
                print(f"[NAV] DNS not resolved, retrying in {wait_between}s... ({attempt + 1}/{retries})")
                time.sleep(wait_between)
            else:
                raise
