import os

# Chrome user data directory and profile
BROWSER_USER_DATA_DIR = os.path.expanduser(
    "~/Library/Application Support/Google/Chrome"
)
CHROME_PROFILE = "Profile 1"  # SahibindenProfile

# Sahibinden URLs
BASE_URL = "https://www.sahibinden.com"
SEARCH_URL = f"{BASE_URL}/porsche-taycan-elektrik?pagingSize=50&sorting=date_desc"

# Delay between page loads (seconds) — randomized ±30%
DEFAULT_DELAY = 4.0

# Human-like browsing behavior — normal browsing pace between list pages.
# (Reverted from the 5-min experiment: the block is PerimeterX *behavioral* scoring,
# not a request-rate limit, so slow pacing didn't help and only made runs crawl. The
# real defense is the arm/disarm + human-mouse + real-link-click strategy; a human
# browses search pages a few seconds apart.)
HUMAN_DELAY_MIN = 4.0   # seconds
HUMAN_DELAY_MAX = 10.0

# Scroll simulation
SCROLL_STEP_MIN = 200  # pixels
SCROLL_STEP_MAX = 500
SCROLL_PAUSE_MIN = 0.5  # seconds between scroll steps
SCROLL_PAUSE_MAX = 2.0
SCROLL_STEPS_MIN = 3
SCROLL_STEPS_MAX = 6

# Photo click probabilities
PHOTO_CLICK_PROB_LIST = 0.35  # chance to click a thumbnail on list page
PHOTO_CLICK_PROB_DETAIL = 0.25  # chance to click gallery photos on detail page

# Long break: occasional longer pause to mimic real browsing (modest — not a rate lever).
LONG_BREAK_EVERY = 10  # pages
LONG_BREAK_MIN = 15.0  # seconds
LONG_BREAK_MAX = 40.0

# Playwright settings
VIEWPORT = {"width": 1440, "height": 900}
NAVIGATION_TIMEOUT = 60000  # ms

# --- PerimeterX (HUMAN Security) sensor blocking ---
# sahibinden runs PerimeterX: a first-party sensor (init.js on a randomized path) feeds
# behavioral telemetry to PX, which issues the short-lived `_px3` risk token. We can't
# pass its behavioral ML when scraping, so the strategy is: ARM the sensor on list/home
# pages (with human mouse movement) to mint a good `_px3`, then DISARM it (block these
# requests) for the quick detail-fetch burst so it can't re-score us, then re-arm.
# NOTE: the first-party path (QerrWGjI) is set by sahibinden's PX integration and CAN
# rotate; if drains start blocking, re-probe the homepage and update this list.
PX_SENSOR_PATTERNS = [
    "**/QerrWGjI/**",            # first-party PX sensor + telemetry (observed 2026-06-25)
    "**://*.perimeterx.net/**",
    "**://*.px-cloud.net/**",
    "**://*.pxi.pub/**",
    "**://*.px-cdn.net/**",
    "**://*.pxchk.net/**",
]

# `_px3` token lifetime is short (~60s–5.5min): re-arm every list page, keep detail
# bursts small, and pace clicks a few seconds apart (NOT the 5-min list/detail delay).
DETAIL_BURST_MIN_GAP = 2.0  # seconds between detail clicks within a disarmed burst
DETAIL_BURST_MAX_GAP = 6.0

# --- Bargain / motivation score ---
# Weights must sum to 1.0; each input is normalized against its cap (0..1).
SCORE_WEIGHT_PRICE_DROP = 0.40   # price_drop_pct
SCORE_WEIGHT_PRICE_CUTS = 0.20   # num_price_cuts
SCORE_WEIGHT_DAYS = 0.20         # days_on_market
SCORE_WEIGHT_BUMPS = 0.20        # bump_count

SCORE_CAP_PRICE_DROP_PCT = 25.0  # % drop that maxes out this component
SCORE_CAP_PRICE_CUTS = 5         # number of cuts that maxes out
SCORE_CAP_DAYS_ON_MARKET = 180   # days that maxes out
SCORE_CAP_BUMP_COUNT = 10        # bumps that maxes out

REPORT_TOP_N = 5                 # rows in the console summary after a scan

# Detail-fetch cap per run (applies to the PerimeterX-aware click-through drain used by
# both normal runs and --resume). With the arm/disarm strategy working, a run can clear
# the whole never-detailed gap in one go, so this is set high enough to cover a typical
# backlog while still bounding a runaway session. Lower it for cautious sessions, or
# raise it to drain a large initial backlog. The drain aborts cleanly on a block and the
# remainder is picked up next run, so this is a safety bound, not a correctness limit.
DEFAULT_MAX_DETAILS = 25
