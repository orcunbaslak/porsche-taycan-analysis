"""Simulate human-like browsing behavior to avoid bot detection."""

import random
import time

from scraper.config import (
    HUMAN_DELAY_MIN,
    HUMAN_DELAY_MAX,
    SCROLL_STEP_MIN,
    SCROLL_STEP_MAX,
    SCROLL_PAUSE_MIN,
    SCROLL_PAUSE_MAX,
    SCROLL_STEPS_MIN,
    SCROLL_STEPS_MAX,
    PHOTO_CLICK_PROB_LIST,
    PHOTO_CLICK_PROB_DETAIL,
    LONG_BREAK_EVERY,
    LONG_BREAK_MIN,
    LONG_BREAK_MAX,
    VIEWPORT,
)


def human_delay(min_s=HUMAN_DELAY_MIN, max_s=HUMAN_DELAY_MAX):
    """Sleep for a random duration between bounds."""
    time.sleep(random.uniform(min_s, max_s))


def maybe_long_break(page_count):
    """Take a longer break periodically (~every LONG_BREAK_EVERY pages)."""
    if page_count > 0 and page_count % LONG_BREAK_EVERY == 0:
        pause = random.uniform(LONG_BREAK_MIN, LONG_BREAK_MAX)
        print(f"[HUMAN] Taking a {pause:.0f}s break after {page_count} pages...")
        time.sleep(pause)


def _bezier_points(sx, sy, ex, ey, steps):
    """Quadratic Bézier path from (sx,sy) to (ex,ey) with a randomized control point
    and ease-in-out timing — produces a curved, variable-speed cursor path rather than
    a straight line. PerimeterX's dominant signal is mouse-movement ML, so armed
    re-warm loads need believable motion to mint a high-trust _px3 token.
    """
    cx = (sx + ex) / 2 + random.uniform(-160, 160)
    cy = (sy + ey) / 2 + random.uniform(-120, 120)
    pts = []
    for i in range(1, steps + 1):
        t = i / steps
        te = t * t * (3 - 2 * t)  # smoothstep ease-in-out
        x = (1 - te) ** 2 * sx + 2 * (1 - te) * te * cx + te ** 2 * ex
        y = (1 - te) ** 2 * sy + 2 * (1 - te) * te * cy + te ** 2 * ey
        pts.append((x, y))
    return pts


def move_mouse_humanlike(page, to_x, to_y, start=None, steps=None):
    """Move the cursor to (to_x, to_y) along a human-like curved path."""
    try:
        sx, sy = start if start else (random.uniform(0, VIEWPORT["width"]),
                                      random.uniform(0, VIEWPORT["height"]))
        steps = steps or random.randint(18, 34)
        for x, y in _bezier_points(sx, sy, to_x, to_y, steps):
            page.mouse.move(x, y)
            time.sleep(random.uniform(0.008, 0.03))
    except Exception:
        pass


def wander_mouse(page, moves=None):
    """Drift the cursor across a few random points in the viewport, the way a person
    idly moves the mouse while reading search results (feeds PX good behavioral data)."""
    try:
        moves = moves or random.randint(2, 4)
        last = (random.uniform(0, VIEWPORT["width"]), random.uniform(0, VIEWPORT["height"]))
        for _ in range(moves):
            target = (random.uniform(40, VIEWPORT["width"] - 40),
                      random.uniform(40, VIEWPORT["height"] - 40))
            move_mouse_humanlike(page, target[0], target[1], start=last)
            last = target
            time.sleep(random.uniform(0.1, 0.5))
    except Exception:
        pass


def scroll_page(page):
    """Scroll the page incrementally like a human reading content."""
    try:
        steps = random.randint(SCROLL_STEPS_MIN, SCROLL_STEPS_MAX)
        for i in range(steps):
            amount = random.randint(SCROLL_STEP_MIN, SCROLL_STEP_MAX)
            page.mouse.wheel(0, amount)
            time.sleep(random.uniform(SCROLL_PAUSE_MIN, SCROLL_PAUSE_MAX))

        # Occasionally scroll back up a bit
        if random.random() < 0.3:
            page.mouse.wheel(0, -random.randint(100, 300))
            time.sleep(random.uniform(0.3, 1.0))
    except Exception:
        pass


def click_random_photo_list_page(page):
    """With some probability, click a listing thumbnail to mimic curiosity."""
    try:
        if random.random() > PHOTO_CLICK_PROB_LIST:
            return

        thumbnails = page.query_selector_all("img.classifiedImg")
        if not thumbnails:
            return

        thumb = random.choice(thumbnails)
        thumb.click()
        print("[HUMAN] Clicked a listing photo")
        time.sleep(random.uniform(1.0, 3.0))

        # Press Escape to close any overlay
        page.keyboard.press("Escape")
        time.sleep(random.uniform(0.3, 0.8))
    except Exception:
        pass


def click_gallery_detail_page(page):
    """With some probability, click through gallery photos on a detail page."""
    try:
        if random.random() > PHOTO_CLICK_PROB_DETAIL:
            return

        gallery_imgs = page.query_selector_all("div.classifiedDetailMainPhoto img")
        if not gallery_imgs:
            return

        clicks = random.randint(1, 3)
        for _ in range(min(clicks, len(gallery_imgs))):
            img = random.choice(gallery_imgs)
            img.click()
            print("[HUMAN] Clicked a gallery photo")
            time.sleep(random.uniform(1.0, 2.5))
    except Exception:
        pass


def simulate_list_page(page):
    """Run human-like actions on a search results page.

    This is also the PerimeterX 're-warm': the sensor is armed here, so believable
    mouse movement + scrolling is what mints a high-trust `_px3` token for the
    subsequent (sensor-disarmed) detail burst.
    """
    wander_mouse(page)
    scroll_page(page)
    wander_mouse(page)
    click_random_photo_list_page(page)


def simulate_detail_page(page):
    """Run human-like actions on a listing detail page."""
    scroll_page(page)
    click_gallery_detail_page(page)
