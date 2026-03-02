#!/bin/bash
# Rename all __playwright* and __pw* globals in the rebrowser-playwright driver
# to avoid isPlaywright detection. Run after pip install/upgrade.

DRIVER_BASE="$(python3 -c 'import rebrowser_playwright; import os; print(os.path.join(os.path.dirname(rebrowser_playwright.__file__), "driver", "package", "lib"))')"

if [ ! -d "$DRIVER_BASE" ]; then
    echo "Error: rebrowser_playwright driver not found at $DRIVER_BASE"
    exit 1
fi

echo "Patching driver at: $DRIVER_BASE"

find "$DRIVER_BASE" -name "*.js" -not -path "*/vite/*" -exec sed -i '' \
    -e 's/__playwright/__cr/g' \
    -e 's/__pw/__cr/g' \
    {} \;

# Verify
REMAINING=$(find "$DRIVER_BASE" -name "*.js" -not -path "*/vite/*" -exec grep -l '__pw\|__playwright' {} \; 2>/dev/null | wc -l | tr -d ' ')
echo "Done. Remaining files with __pw/__playwright: $REMAINING"
