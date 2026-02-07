import os

# Chrome user data directory and profile
BROWSER_USER_DATA_DIR = os.path.expanduser(
    "~/Library/Application Support/Google/Chrome"
)
CHROME_PROFILE = "Profile 1"  # SahibindenProfile

# Sahibinden URLs
BASE_URL = "https://www.sahibinden.com"
SEARCH_URL = f"{BASE_URL}/porsche-taycan"

# Delay between page loads (seconds) — randomized ±30%
DEFAULT_DELAY = 4.0

# Playwright settings
VIEWPORT = {"width": 1440, "height": 900}
NAVIGATION_TIMEOUT = 60000  # ms
