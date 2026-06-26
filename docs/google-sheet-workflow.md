# Google Sheet workflow

Use the repo as the data source and Google Sheets as the buying cockpit.

## Why this shape

Do not re-import `taycan_scores.csv` into a sheet by hand each time. That deletes or scrambles your working notes. Instead, keep a stable `Listings` tab keyed by `sahibinden_id`:

- scraped/scored columns are refreshed from `taycan_scores.csv`
- manual columns are preserved across refreshes
- disappeared listings stay in the sheet with `active_in_latest_export = No`
- Google filters/filter views remain because the tab is updated in place

Manual columns currently preserved:

- `my_status`
- `my_priority`
- `phone_price`
- `phone_date`
- `my_offer`
- `next_action`
- `seller_notes`
- `damage_story`
- `warranty_verified`
- `battery_health`
- `inspection_notes`
- `owner_notes`

## Local CSV first

```bash
python export_scores.py
python google_sheet_sync.py --local taycan_buyer_sheet.csv
```

You can import `taycan_buyer_sheet.csv` into Google Sheets manually. This is the simplest start.

## Direct Google Sheets sync

Install the optional Google dependencies:

```bash
python -m pip install -r requirements-google.txt
```

Create a Google Cloud service account with Sheets API access, download its JSON credentials, then share your Google Sheet with the service account email.

Run:

```bash
python export_scores.py
python google_sheet_sync.py \
  --spreadsheet-id YOUR_SPREADSHEET_ID \
  --service-account /path/to/service-account.json
```

The script writes to a `Listings` tab by default. Use `--worksheet SomeName` if you want another tab.

## Recommended filters

Good default filters for shopping:

- `active_in_latest_export` = `Yes`
- `dq_reason` is empty
- `heavy_damage_record` is not `Evet`
- `is_clean` = `Yes`, or allow one cosmetic paint only
- `year` in your target range
- `price` or `phone_price` within budget
- `my_status` not `Pass`

Use `phone_price` for real negotiation numbers. `phone_discount_pct` is recomputed whenever the sync script runs.

`is_clean` means the scraped damage summary has zero changed, painted, and local-painted panels. It does not mean no Tramer, no mechanical repair, no underbody/cooling-system impact, or no battery/warranty risk. In the all-cars export, undetailed rows are marked `Unknown`.
