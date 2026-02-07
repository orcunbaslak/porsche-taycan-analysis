#!/bin/bash
# Launch Chrome with remote debugging for the scraper.
# Close Chrome first (Cmd+Q), then run this script.
#
# First time: log into sahibinden.com in the Chrome window.
# After that, your session will persist across launches.

CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# Permanent non-default user-data-dir (cookies persist here)
DATA_DIR="$HOME/.taycan-chrome"
mkdir -p "$DATA_DIR"

echo "Starting Chrome with remote debugging on port 9222..."
echo "Data dir: $DATA_DIR"
echo ""
echo "Once Chrome is open and you're logged into sahibinden.com, run:"
echo "  python run_scraper.py"
echo ""

"$CHROME" \
    --remote-debugging-port=9222 \
    --user-data-dir="$DATA_DIR" \
    --no-first-run
