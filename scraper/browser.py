import time
import urllib.request
from patchright.sync_api import sync_playwright
from scraper.config import VIEWPORT, NAVIGATION_TIMEOUT

CDP_PORT = 9222


class BrowserManager:
    """
    Connects Playwright to an already-running Chrome via CDP.

    Start Chrome first with:
        ./start_chrome.sh
    """

    def __init__(self, headless=False):
        self._playwright = None
        self._browser = None

    def _is_cdp_ready(self):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json/version", timeout=2)
            return True
        except Exception:
            return False

    def start(self):
        if not self._is_cdp_ready():
            print("Chrome is not running with remote debugging.")
            print("Start it first with:  ./start_chrome.sh")
            print("Then log into sahibinden.com and run the scraper again.")
            raise RuntimeError("No Chrome with CDP found on port 9222")

        print("Connecting to Chrome via CDP...")
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.connect_over_cdp(
            f"http://127.0.0.1:{CDP_PORT}"
        )

        default_context = self._browser.contexts[0]
        default_context.add_init_script("""
            // Hide webdriver flag
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});

            // Patch Permissions.query so notification permission looks normal
            const originalQuery = window.Permissions.prototype.query;
            window.Permissions.prototype.query = (parameters) => (
                parameters.name === 'notifications'
                    ? Promise.resolve({state: Notification.permission})
                    : originalQuery(parameters)
            );

            // Remove Playwright-injected properties from window
            delete window.__playwright;
            delete window.__pw_manual;
        """)

        print("Connected.")
        return self._browser

    def new_page(self):
        if not self._browser:
            self.start()
        context = self._browser.contexts[0]
        page = context.new_page()
        page.set_viewport_size(VIEWPORT)
        page.set_default_navigation_timeout(NAVIGATION_TIMEOUT)
        page.set_default_timeout(NAVIGATION_TIMEOUT)
        return page

    def close(self):
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()
        # Never kill Chrome — user manages it

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.close()
