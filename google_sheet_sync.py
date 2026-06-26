#!/usr/bin/env python3
"""Create or sync a buyer-facing Taycan sheet.

The main exporter produces `taycan_scores.csv`, which is machine-owned. This script
turns that into a sheet you can actually shop from: manual decision columns are
preserved by `sahibinden_id`, while scraped/scored columns are refreshed.

Local-only usage:
    python google_sheet_sync.py --local taycan_buyer_sheet.csv

Google Sheets usage:
    python google_sheet_sync.py --spreadsheet-id SHEET_ID --service-account service-account.json
"""
from __future__ import annotations

import argparse
import csv
import os
import string
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


DEFAULT_SCORES_CSV = "taycan_scores.csv"
DEFAULT_LOCAL_CSV = "taycan_buyer_sheet.csv"
DEFAULT_WORKSHEET = "Listings"

MANUAL_COLUMNS = [
    "my_status",
    "my_priority",
    "phone_price",
    "phone_date",
    "my_offer",
    "next_action",
    "seller_notes",
    "damage_story",
    "warranty_verified",
    "battery_health",
    "inspection_notes",
    "owner_notes",
]

DERIVED_COLUMNS = [
    "active_in_latest_export",
    "ask_price_m_tl",
    "phone_price_m_tl",
    "phone_discount_pct",
]

SOURCE_COLUMNS = [
    "rank",
    "value_score",
    "model",
    "year",
    "km",
    "price",
    "motivation_score",
    "price_drop_pct",
    "num_price_cuts",
    "bump_count",
    "days_on_market",
    "is_clean",
    "is_bayi",
    "damage_changed_count",
    "damage_painted_count",
    "damage_local_painted_count",
    "feature_count",
    "battery",
    "seller_type",
    "heavy_damage_record",
    "km_per_year",
    "price_score",
    "km_score",
    "damage_score",
    "feature_score",
    "depr_score",
    "trim_mult",
    "clean_bonus",
    "bayi_bonus",
    "new_changed_penalty",
    "price_history",
    "dq_reason",
    "sahibinden_id",
    "title",
    "url",
]

SHEET_COLUMNS = MANUAL_COLUMNS + DERIVED_COLUMNS + SOURCE_COLUMNS
KEY_COLUMN = "sahibinden_id"


@dataclass(frozen=True)
class MergeResult:
    header: list[str]
    rows: list[list[str]]
    active_count: int
    inactive_count: int


def read_csv_rows(path: str | os.PathLike[str]) -> tuple[list[str], list[dict[str, str]]]:
    file_path = Path(path)
    if not file_path.exists():
        return [], []
    with file_path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return list(reader.fieldnames or []), [dict(row) for row in reader]


def write_csv_rows(path: str | os.PathLike[str], header: list[str], rows: Iterable[list[str]]) -> None:
    with Path(path).open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


def _to_int(value: str | None) -> int | None:
    if value is None:
        return None
    cleaned = str(value).strip().replace(",", "")
    if not cleaned:
        return None
    try:
        return int(float(cleaned))
    except ValueError:
        return None


def _format_m_tl(value: str | None) -> str:
    amount = _to_int(value)
    if amount is None:
        return ""
    return f"{amount / 1_000_000:.3f}"


def _format_discount(phone_price: str | None, ask_price: str | None) -> str:
    phone = _to_int(phone_price)
    ask = _to_int(ask_price)
    if phone is None or ask in (None, 0):
        return ""
    return f"{(ask - phone) / ask:.2%}"


def _row_to_values(row: dict[str, str], header: list[str]) -> list[str]:
    return [str(row.get(col, "") or "") for col in header]


def merge_rows(source_rows: list[dict[str, str]], existing_rows: list[dict[str, str]]) -> MergeResult:
    """Merge source rows with an existing buyer sheet.

    Source columns always come from the current scrape export. Manual columns are
    copied from the existing row with the same `sahibinden_id`. Existing rows not
    present in the latest export are kept and marked inactive, so notes are not lost.
    """
    existing_by_id = {
        row.get(KEY_COLUMN, ""): row
        for row in existing_rows
        if row.get(KEY_COLUMN)
    }

    merged: list[dict[str, str]] = []
    active_ids: set[str] = set()

    for source in source_rows:
        sid = source.get(KEY_COLUMN, "")
        if not sid:
            continue
        active_ids.add(sid)
        previous = existing_by_id.get(sid, {})
        row = {col: "" for col in SHEET_COLUMNS}
        for col in MANUAL_COLUMNS:
            row[col] = previous.get(col, "")
        for col in SOURCE_COLUMNS:
            row[col] = source.get(col, "")
        row["active_in_latest_export"] = "Yes"
        row["ask_price_m_tl"] = _format_m_tl(row.get("price"))
        row["phone_price_m_tl"] = _format_m_tl(row.get("phone_price"))
        row["phone_discount_pct"] = _format_discount(row.get("phone_price"), row.get("price"))
        merged.append(row)

    for sid, previous in existing_by_id.items():
        if sid in active_ids:
            continue
        row = {col: previous.get(col, "") for col in SHEET_COLUMNS}
        row["active_in_latest_export"] = "No"
        row["ask_price_m_tl"] = _format_m_tl(row.get("price"))
        row["phone_price_m_tl"] = _format_m_tl(row.get("phone_price"))
        row["phone_discount_pct"] = _format_discount(row.get("phone_price"), row.get("price"))
        merged.append(row)

    active_rows = [row for row in merged if row.get("active_in_latest_export") == "Yes"]
    inactive_rows = [row for row in merged if row.get("active_in_latest_export") != "Yes"]
    active_rows.sort(key=_sort_key)
    inactive_rows.sort(key=lambda row: (row.get("model", ""), row.get("year", ""), row.get(KEY_COLUMN, "")))
    rows = active_rows + inactive_rows

    return MergeResult(
        header=SHEET_COLUMNS,
        rows=[_row_to_values(row, SHEET_COLUMNS) for row in rows],
        active_count=len(active_rows),
        inactive_count=len(inactive_rows),
    )


def _sort_key(row: dict[str, str]) -> tuple[int, float, str]:
    rank = _to_int(row.get("rank"))
    if rank is None:
        rank = 999_999
    score_raw = row.get("value_score") or "-1"
    try:
        score = float(score_raw)
    except ValueError:
        score = -1
    return rank, -score, row.get(KEY_COLUMN, "")


def column_letter(index: int) -> str:
    """1-based column index to Google Sheets column letters."""
    if index < 1:
        raise ValueError("index must be 1-based")
    letters = []
    while index:
        index, remainder = divmod(index - 1, 26)
        letters.append(string.ascii_uppercase[remainder])
    return "".join(reversed(letters))


def sync_google_sheet(
    spreadsheet_id: str,
    worksheet: str,
    service_account: str,
    values: list[list[str]],
    apply_filter: bool,
) -> None:
    try:
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise SystemExit(
            "Google sync needs optional dependencies. Run: "
            "python -m pip install -r requirements-google.txt"
        ) from exc

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    credentials = Credentials.from_service_account_file(service_account, scopes=scopes)
    service = build("sheets", "v4", credentials=credentials)
    sheets = service.spreadsheets()

    sheet_id = ensure_worksheet(sheets, spreadsheet_id, worksheet)
    end_col = column_letter(len(SHEET_COLUMNS))
    clear_range = f"{worksheet}!A:{end_col}"
    update_range = f"{worksheet}!A1:{end_col}{len(values)}"

    sheets.values().clear(spreadsheetId=spreadsheet_id, range=clear_range, body={}).execute()
    sheets.values().update(
        spreadsheetId=spreadsheet_id,
        range=update_range,
        valueInputOption="RAW",
        body={"values": values},
    ).execute()

    if apply_filter:
        sheets.batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={
                "requests": [
                    {
                        "updateSheetProperties": {
                            "properties": {
                                "sheetId": sheet_id,
                                "gridProperties": {"frozenRowCount": 1},
                            },
                            "fields": "gridProperties.frozenRowCount",
                        }
                    },
                    {
                        "setBasicFilter": {
                            "filter": {
                                "range": {
                                    "sheetId": sheet_id,
                                    "startRowIndex": 0,
                                    "startColumnIndex": 0,
                                    "endColumnIndex": len(SHEET_COLUMNS),
                                }
                            }
                        }
                    },
                    {
                        "autoResizeDimensions": {
                            "dimensions": {
                                "sheetId": sheet_id,
                                "dimension": "COLUMNS",
                                "startIndex": 0,
                                "endIndex": len(SHEET_COLUMNS),
                            }
                        }
                    },
                ]
            },
        ).execute()


def ensure_worksheet(sheets, spreadsheet_id: str, worksheet: str) -> int:
    metadata = sheets.get(spreadsheetId=spreadsheet_id).execute()
    for sheet in metadata.get("sheets", []):
        props = sheet.get("properties", {})
        if props.get("title") == worksheet:
            return int(props["sheetId"])

    response = sheets.batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": [{"addSheet": {"properties": {"title": worksheet}}}]},
    ).execute()
    return int(response["replies"][0]["addSheet"]["properties"]["sheetId"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", default=DEFAULT_SCORES_CSV, help=f"Input score CSV (default: {DEFAULT_SCORES_CSV})")
    parser.add_argument("--local", default=DEFAULT_LOCAL_CSV, help=f"Local buyer CSV output (default: {DEFAULT_LOCAL_CSV})")
    parser.add_argument("--spreadsheet-id", help="Google Sheet spreadsheet ID to sync")
    parser.add_argument("--worksheet", default=DEFAULT_WORKSHEET, help=f"Worksheet/tab name (default: {DEFAULT_WORKSHEET})")
    parser.add_argument("--service-account", help="Google service account JSON credentials")
    parser.add_argument("--no-filter", action="store_true", help="Do not apply freeze/filter/autosize formatting")
    args = parser.parse_args()

    _, source_rows = read_csv_rows(args.csv)
    if not source_rows:
        raise SystemExit(f"No rows found in {args.csv}. Run export_scores.py first.")

    _, existing_rows = read_csv_rows(args.local)
    result = merge_rows(source_rows, existing_rows)
    values = [result.header] + result.rows
    write_csv_rows(args.local, result.header, result.rows)

    if args.spreadsheet_id:
        if not args.service_account:
            raise SystemExit("--service-account is required when --spreadsheet-id is set")
        sync_google_sheet(
            spreadsheet_id=args.spreadsheet_id,
            worksheet=args.worksheet,
            service_account=args.service_account,
            values=values,
            apply_filter=not args.no_filter,
        )
        print(
            f"Synced {result.active_count} active and {result.inactive_count} inactive rows "
            f"to Google Sheet tab '{args.worksheet}'."
        )
    else:
        print(
            f"Wrote {args.local} with {result.active_count} active and "
            f"{result.inactive_count} inactive rows."
        )


if __name__ == "__main__":
    main()
