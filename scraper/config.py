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

# Human-like browsing behavior
HUMAN_DELAY_MIN = 6.0  # seconds
HUMAN_DELAY_MAX = 14.0

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

# Long break: periodic longer pause to mimic real browsing
LONG_BREAK_EVERY = 12  # pages
LONG_BREAK_MIN = 20.0  # seconds
LONG_BREAK_MAX = 45.0

# Playwright settings
VIEWPORT = {"width": 1440, "height": 900}
NAVIGATION_TIMEOUT = 60000  # ms

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
