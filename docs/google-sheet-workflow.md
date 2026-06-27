# Google Sheet workflow

Use the repo as the data source and Google Sheets as the buying cockpit. One
script does everything: `sync_all_cars_sheet.py`.

## What it does

`sync_all_cars_sheet.py` reads `taycan.db`, scores/ranks the active cars with the
notebook's Value Score (+ bargain signals), and writes one row per
`sahibinden_id` — including inactive/no-longer-listed cars — to a stable
`All Cars` tab keyed by `sahibinden_id`:

- scraped fields and the ranking/score columns are refreshed every run
- your `my_priority` note column is preserved across refreshes
- disappeared listings stay in the sheet with `is_active = No`
- Google filters / filter views survive because the tab is updated in place

Do not re-import a CSV into the sheet by hand — that scrambles your working
notes. Always sync through this script.

### Column groups (left to right)

1. **Manual** (you fill this in): `my_priority`
2. **Score / ranking** (the notebook's ranking — sort on these): `rank`,
   `value_score`, `motivation_score`, `price_drop_pct`, `num_price_cuts`,
   `bump_count`, `days_on_market`, `dq_reason`
3. **Derived**: `ask_price_m_tl`, `is_clean`, `is_bayi`, `battery`,
   `km_per_year`, `first_seen_date`, `last_seen_date`, `runs_seen_total`,
   `price_history`
4. **Source**: the raw scraped fields straight from `taycan.db` (`is_active`,
   `detail_scraped`, `sahibinden_id`, `url`, `title`, `model`, `year`, `km`,
   `color`, `price`, `listing_date`, location, damage counts, `description`, …)

`rank`/`value_score` are only populated for the scored universe (active,
detail-scraped, non-wagon cars); inactive or undetailed cars leave them blank.

## Setup (once)

Install the optional Google dependencies:

```bash
python -m pip install -r requirements-google.txt
```

Credentials and the spreadsheet id are baked into the script. The service
account is `orcun-sheetswriter@sacred-alpha-382721.iam.gserviceaccount.com`, its
key lives in Bitwarden, and the target sheet is already shared with it.

## Run it

Unlock Bitwarden once per shell, then run:

```bash
export BW_SESSION="$(bw unlock --raw)"
python sync_all_cars_sheet.py
```

That's it — the script fetches the service-account key from Bitwarden (to a
`0600` file under `~/.config/gcloud/keys/`), writes the local
`taycan_all_cars_sheet.csv`, and syncs the `All Cars` tab.

### Credential resolution order

The script looks for the service-account JSON in this order, using the first it
finds:

1. `--service-account /path/to/key.json`
2. `$GOOGLE_APPLICATION_CREDENTIALS` (if the file exists)
3. Bitwarden (requires `BW_SESSION`)

### Other options

```bash
python sync_all_cars_sheet.py --local-only        # write the CSV, skip Google
python sync_all_cars_sheet.py --worksheet "Other" # sync a different tab
python sync_all_cars_sheet.py --no-filter         # skip freeze/filter/colour formatting
python sync_all_cars_sheet.py --spreadsheet-id ID # override the baked-in sheet
```

## Recommended filters

Good default filters for shopping:

- `is_active` = `Yes`
- `dq_reason` is empty
- `is_clean` = `Yes`, or allow one cosmetic paint only
- `year` in your target range
- `price` within budget

Sort by `rank` (ascending) or `value_score` (descending) to see the best-value
cars first; sort by `motivation_score` to surface the most motivated sellers.

`is_clean` means the scraped damage summary has zero changed, painted, and
local-painted panels. It does not mean no Tramer, no mechanical repair, no
underbody/cooling-system impact, or no battery/warranty risk. Undetailed rows
are marked `Unknown`.
