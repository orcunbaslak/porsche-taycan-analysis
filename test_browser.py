#!/usr/bin/env python3
"""Test: launch Chrome with SahibindenProfile, open Gmail, check login."""

import os
import subprocess
import tempfile
import time
import urllib.request

CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PROFILE_DIR = os.path.expanduser("~/Library/Application Support/Google/Chrome")
CHROME_PROFILE = "Profile 1"  # SahibindenProfile
CDP_PORT = 9222

# Step 1: Create symlinked profile dir
print("Step 1: Creating symlinked profile...")
temp_dir = tempfile.mkdtemp(prefix="taycan_chrome_")
for item in os.listdir(PROFILE_DIR):
    src = os.path.join(PROFILE_DIR, item)
    dst = os.path.join(temp_dir, item)
    os.symlink(src, dst)
print(f"  Temp dir: {temp_dir}")

# Step 2: Launch Chrome with SahibindenProfile
print(f"Step 2: Launching Chrome with profile '{CHROME_PROFILE}'...")
proc = subprocess.Popen(
    [CHROME_PATH, f"--remote-debugging-port={CDP_PORT}",
     f"--user-data-dir={temp_dir}", f"--profile-directory={CHROME_PROFILE}",
     "--no-first-run"],
    stdout=subprocess.PIPE, stderr=subprocess.PIPE
)
time.sleep(5)

# Step 3: Check CDP
print("Step 3: Checking CDP port...")
try:
    resp = urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json/version", timeout=5)
    print(f"  CDP OK: {resp.read().decode()[:100]}")
except Exception as e:
    print(f"  CDP FAILED: {e}")
    stderr = proc.stderr.read().decode()
    print(f"  Chrome stderr: {stderr[:500]}")
    proc.terminate()
    import shutil; shutil.rmtree(temp_dir, ignore_errors=True)
    exit(1)

# Step 4: Connect Playwright and open Gmail
print("Step 4: Connecting Playwright and opening Gmail...")
from playwright.sync_api import sync_playwright
pw = sync_playwright().start()
browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{CDP_PORT}")
context = browser.contexts[0]
page = context.new_page()

page.goto("https://mail.google.com", wait_until="domcontentloaded")
time.sleep(5)

title = page.title()
url = page.url
print(f"  Page title: {title}")
print(f"  Page URL: {url}")

if "inbox" in url.lower() or "mail" in title.lower():
    print("\n  Gmail is logged in!")
else:
    print("\n  Check the Chrome window to see Gmail status")

input("\nPress Enter to close everything...")

browser.close()
pw.stop()
proc.terminate()
import shutil; shutil.rmtree(temp_dir, ignore_errors=True)
