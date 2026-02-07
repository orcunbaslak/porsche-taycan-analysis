#!/usr/bin/env python3
"""Test: check if cookies survive the symlinked profile launch."""

import os
import subprocess
import tempfile
import time
import urllib.request

CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PROFILE_DIR = os.path.expanduser("~/Library/Application Support/Google/Chrome")
CHROME_PROFILE = "Profile 1"  # SahibindenProfile
CDP_PORT = 9222

# Create symlinked profile dir
temp_dir = tempfile.mkdtemp(prefix="taycan_chrome_")
for item in os.listdir(PROFILE_DIR):
    os.symlink(os.path.join(PROFILE_DIR, item), os.path.join(temp_dir, item))

# Launch Chrome
proc = subprocess.Popen(
    [CHROME_PATH, f"--remote-debugging-port={CDP_PORT}",
     f"--user-data-dir={temp_dir}", f"--profile-directory={CHROME_PROFILE}",
     "--no-first-run"],
    stdout=subprocess.PIPE, stderr=subprocess.PIPE
)
time.sleep(5)

from playwright.sync_api import sync_playwright
pw = sync_playwright().start()
browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{CDP_PORT}")
context = browser.contexts[0]

# Check cookies
cookies = context.cookies()
print(f"Total cookies in profile: {len(cookies)}")

# Show domains with cookies
domains = set(c["domain"] for c in cookies)
print(f"\nDomains with cookies ({len(domains)}):")
for d in sorted(domains):
    count = sum(1 for c in cookies if c["domain"] == d)
    print(f"  {d}: {count} cookies")

# Check sahibinden specifically
sah_cookies = [c for c in cookies if "sahibinden" in c.get("domain", "")]
print(f"\nSahibinden cookies: {len(sah_cookies)}")
for c in sah_cookies:
    print(f"  {c['name']}: {c['value'][:30]}...")

input("\nPress Enter to close...")
browser.close()
pw.stop()
proc.terminate()
import shutil; shutil.rmtree(temp_dir, ignore_errors=True)
