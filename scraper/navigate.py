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


def page_is_blocked(page):
    """Best-effort block check on a *live* page.

    Used after a content-selector wait times out: the rate-limit page can arrive
    via a delayed / client-side redirect (so the URL looked fine when safe_goto
    first checked it), and it has none of the normal listing selectors — so the
    wait just times out instead of raising BlockedError. We re-check both the
    (possibly now-changed) URL and the body here.

    Defensive: a crashed/closed session makes page.url or page.content() throw;
    in that case we simply report "not a known block page" rather than blowing up.
    """
    try:
        url = page.url
    except Exception:
        url = None
    try:
        html = page.content()
    except Exception:
        html = None
    return is_block_page(url, html)


def click_listing(page, sahibinden_id, timeout=30000):
    """Navigate to a listing by clicking its REAL anchor on the current search-results
    page — a trusted (isTrusted=true) same-origin click that sends Referer +
    Sec-Fetch-Site: same-origin, the way a human opens a listing. A bare page.goto()
    instead sends Sec-Fetch-Site: none with no Referer, which the bot heuristic flags.

    Listing hrefs in the grid are relative and end with `-<id>/detay`, so we match by id.
    Raises LookupError if the anchor isn't on the current page (caller must load the
    search page that contains it first). Raises BlockedError on the rate-limit page.
    """
    el = page.query_selector(f'a[href*="{sahibinden_id}"]')
    if el is None:
        raise LookupError(f"listing anchor for {sahibinden_id} not on current page")

    el.click(timeout=timeout)
    try:
        page.wait_for_selector("ul.classifiedInfoList", timeout=timeout)
    except Exception:
        if page_is_blocked(page):
            raise BlockedError(
                f"Block page after clicking listing {sahibinden_id} "
                "(content selector never appeared)."
            )
        raise
    if is_block_page(page.url):
        raise BlockedError(f"Block page after clicking listing {sahibinden_id}.")
    return True


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
