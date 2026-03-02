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
HUMAN_DELAY_MIN = 5.0  # seconds
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

# Long break: periodic longer pause to mimic real browsing
LONG_BREAK_EVERY = 15  # pages
LONG_BREAK_MIN = 15.0  # seconds
LONG_BREAK_MAX = 30.0

# Playwright settings
VIEWPORT = {"width": 1440, "height": 900}
NAVIGATION_TIMEOUT = 60000  # ms
