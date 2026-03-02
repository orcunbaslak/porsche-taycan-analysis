#!/bin/bash
# Install dependencies and patch the rebrowser-playwright driver.
# Run this after cloning or after upgrading packages.

set -e

echo "=== Installing dependencies ==="
pip install -r requirements.txt

echo ""
echo "=== Patching rebrowser-playwright driver ==="
./patch_driver.sh

echo ""
echo "Done. You can now run the scraper with: python run_scraper.py"
