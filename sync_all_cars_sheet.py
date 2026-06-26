#!/usr/bin/env python3
"""Export every Taycan ever seen and optionally sync it to Google Sheets.

This is the shopping cockpit export. It keeps one row per `sahibinden_id`,
including inactive/no-longer-listed cars, and preserves manual notes across
refreshes.

Local CSV:
    python sync_all_cars_sheet.py --local taycan_all_cars_sheet.csv

Google Sheets:
    python sync_all_cars_sheet.py --spreadsheet-id SHEET_ID --service-account service-account.json
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sqlite3
import string
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


DB_PATH = "taycan.db"
DEFAULT_LOCAL_CSV = "taycan_all_cars_sheet.csv"
DEFAULT_WORKSHEET = "All Cars"
KEY_COLUMN = "sahibinden_id"

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
    "ask_price_m_tl",
    "phone_price_m_tl",
    "phone_discount_pct",
    "is_clean",
    "is_bayi",
    "battery",
    "km_per_year",
    "first_seen_date",
    "last_seen_date",
    "runs_seen_total",
    "price_history",
]

SOURCE_COLUMNS = [
    "is_active",
    "detail_scraped",
    "sahibinden_id",
    "url",
    "title",
    "model",
    "year",
    "km",
    "color",
    "price",
    "currency",
    "listing_date",
    "location_city",
    "location_district",
    "fuel_type",
    "transmission",
    "vehicle_condition",
    "body_type",
    "engine_power",
    "traction",
    "warranty",
    "heavy_damage_record",
    "plate_nationality",
    "seller_type",
    "trade_in",
    "seller_name",
    "seller_agent",
    "seller_phone",
    "seller_years",
    "damage_original_count",
    "damage_painted_count",
    "damage_local_painted_count",
    "damage_changed_count",
    "scrape_run_id",
    "latest_seen_at",
    "description",
]

SHEET_COLUMNS = MANUAL_COLUMNS + DERIVED_COLUMNS + SOURCE_COLUMNS


@dataclass(frozen=True)
class SyncResult:
    active_count: int
    inactive_count: int
    total_count: int


def read_csv_rows(path: str | os.PathLike[str]) -> tuple[list[str], list[dict[str, str]]]:
    file_path = Path(path)
    if not file_path.exists():
        return [], []
    with file_path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return list(reader.fieldnames or []), [dict(row) for row in reader]


def write_csv_rows(path: str | os.PathLike[str], header: list[str], rows: Iterable[dict[str, str]]) -> None:
    with Path(path).open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows)


def connect_readonly(db_path: str) -> sqlite3.Connection:
    uri = f"file:{Path(db_path).resolve()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def load_all_cars(db_path: str) -> list[dict[str, str]]:
    conn = connect_readonly(db_path)
    try:
        latest_rows = conn.execute(
            """
            WITH ranked AS (
                SELECT
                    l.*,
                    r.started_at AS latest_seen_at,
                    ROW_NUMBER() OVER (
                        PARTITION BY l.sahibinden_id
                        ORDER BY l.scrape_run_id DESC, l.id DESC
                    ) AS rn
                FROM listings l
                JOIN scrape_runs r ON r.id = l.scrape_run_id
            )
            SELECT * FROM ranked WHERE rn = 1
            """
        ).fetchall()
        detail_by_id = {
            row["sahibinden_id"]: row
            for row in conn.execute(
                """
                WITH ranked AS (
                    SELECT
                        l.*,
                        r.started_at AS latest_seen_at,
                        ROW_NUMBER() OVER (
                            PARTITION BY l.sahibinden_id
                            ORDER BY l.scrape_run_id DESC, l.id DESC
                        ) AS rn
                    FROM listings l
                    JOIN scrape_runs r ON r.id = l.scrape_run_id
                    WHERE l.detail_scraped = 1
                )
                SELECT * FROM ranked WHERE rn = 1
                """
            ).fetchall()
        }
        seen_by_id = {
            row["sahibinden_id"]: row
            for row in conn.execute(
                """
                SELECT
                    l.sahibinden_id,
                    MIN(date(r.started_at)) AS first_seen_date,
                    MAX(date(r.started_at)) AS last_seen_date,
                    COUNT(DISTINCT l.scrape_run_id) AS runs_seen_total
                FROM listings l
                JOIN scrape_runs r ON r.id = l.scrape_run_id
                GROUP BY l.sahibinden_id
                """
            ).fetchall()
        }
        history_by_id = load_price_history(conn)
    finally:
        conn.close()

    rows: list[dict[str, str]] = []
    for latest in latest_rows:
        sid = latest["sahibinden_id"]
        detail = detail_by_id.get(sid)
        merged = merge_latest_and_detail(latest, detail)
        seen = seen_by_id.get(sid, {})

        row = {col: "" for col in SHEET_COLUMNS}
        for col in SOURCE_COLUMNS:
            row[col] = _clean(merged.get(col))
        row["is_active"] = "Yes" if str(merged.get("is_active", "")) == "1" else "No"
        row["detail_scraped"] = "Yes" if str(merged.get("detail_scraped", "")) == "1" else "No"
        row["is_clean"] = clean_status(row)
        row["is_bayi"] = "Yes" if detect_bayi(row) else "No"
        row["battery"] = detect_battery(row)
        row["km_per_year"] = km_per_year(row)
        row["first_seen_date"] = _clean(seen["first_seen_date"] if seen else "")
        row["last_seen_date"] = _clean(seen["last_seen_date"] if seen else "")
        row["runs_seen_total"] = _clean(seen["runs_seen_total"] if seen else "")
        row["price_history"] = history_by_id.get(sid, "")
        row["ask_price_m_tl"] = format_m_tl(row.get("price"))
        row["phone_price_m_tl"] = format_m_tl(row.get("phone_price"))
        row["phone_discount_pct"] = format_discount(row.get("phone_price"), row.get("price"))
        rows.append(row)

    rows.sort(key=sort_key)
    return rows


def load_price_history(conn: sqlite3.Connection) -> dict[str, str]:
    rows = conn.execute(
        """
        SELECT l.sahibinden_id, date(r.started_at) AS run_date, l.price
        FROM listings l
        JOIN scrape_runs r ON r.id = l.scrape_run_id
        WHERE l.price IS NOT NULL
        ORDER BY l.sahibinden_id, l.scrape_run_id, l.id
        """
    ).fetchall()
    out: dict[str, list[tuple[str, int]]] = {}
    for row in rows:
        sid = row["sahibinden_id"]
        price = row["price"]
        if price is None:
            continue
        out.setdefault(sid, [])
        if not out[sid] or out[sid][-1][1] != int(price):
            out[sid].append((row["run_date"], int(price)))
    return {
        sid: " -> ".join(f"{price:,} ({date})" for date, price in points)
        for sid, points in out.items()
    }


def merge_latest_and_detail(latest: sqlite3.Row, detail: sqlite3.Row | None) -> dict[str, object]:
    latest_dict = dict(latest)
    if detail is None:
        return latest_dict
    detail_dict = dict(detail)

    # List-page fields are fresher on the latest row; detail-page fields are richer
    # on the latest detailed row. Prefer detail only when latest has no value.
    merged = dict(detail_dict)
    for key in (
        "scrape_run_id",
        "sahibinden_id",
        "url",
        "title",
        "model",
        "year",
        "km",
        "color",
        "price",
        "currency",
        "listing_date",
        "location_city",
        "location_district",
        "is_active",
        "latest_seen_at",
    ):
        merged[key] = latest_dict.get(key)
    merged["detail_scraped"] = detail_dict.get("detail_scraped") or latest_dict.get("detail_scraped")
    return merged


def preserve_manual_columns(rows: list[dict[str, str]], existing_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    existing_by_id = {
        row.get(KEY_COLUMN, ""): row
        for row in existing_rows
        if row.get(KEY_COLUMN)
    }
    for row in rows:
        previous = existing_by_id.get(row[KEY_COLUMN], {})
        for col in MANUAL_COLUMNS:
            row[col] = previous.get(col, row.get(col, ""))
        row["phone_price_m_tl"] = format_m_tl(row.get("phone_price"))
        row["phone_discount_pct"] = format_discount(row.get("phone_price"), row.get("price"))
    return rows


def _clean(value: object) -> str:
    if value is None:
        return ""
    text = str(value)
    return " ".join(text.split()) if len(text) > 500 else text


def to_int(value: str | None) -> int | None:
    if value is None:
        return None
    cleaned = str(value).strip().replace(",", "")
    if not cleaned:
        return None
    try:
        return int(float(cleaned))
    except ValueError:
        return None


def to_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).strip().replace(",", ""))
    except ValueError:
        return None


def format_m_tl(value: str | None) -> str:
    amount = to_int(value)
    if amount is None:
        return ""
    return f"{amount / 1_000_000:.3f}"


def format_discount(phone_price: str | None, ask_price: str | None) -> str:
    phone = to_int(phone_price)
    ask = to_int(ask_price)
    if phone is None or ask in (None, 0):
        return ""
    return f"{(ask - phone) / ask:.2%}"


def discount_number(phone_price: str | None, ask_price: str | None) -> float | str:
    phone = to_int(phone_price)
    ask = to_int(ask_price)
    if phone is None or ask in (None, 0):
        return ""
    return round((ask - phone) / ask, 4)


def clean_status(row: dict[str, str]) -> str:
    damage_columns = ("damage_changed_count", "damage_painted_count", "damage_local_painted_count")
    if row.get("detail_scraped") != "Yes":
        return "Unknown"
    if all(row.get(col, "") == "" for col in damage_columns):
        return "Unknown"
    return "Yes" if all((to_int(row.get(col)) or 0) == 0 for col in damage_columns) else "No"


def detect_bayi(row: dict[str, str]) -> bool:
    text = f"{row.get('title', '')} {row.get('description', '')}".lower()
    return bool(re.search(r"\bbayi\b|\bbayii\b|\bdoğuş\b|\bdogus\b", text))


def parse_hp(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"(\d+)\s*-\s*(\d+)", value)
    if match:
        return round((int(match.group(1)) + int(match.group(2))) / 2)
    match = re.search(r"(\d+)", value)
    return int(match.group(1)) if match else None


def detect_battery(row: dict[str, str]) -> str:
    year = to_int(row.get("year"))
    model = row.get("model", "")
    hp = parse_hp(row.get("engine_power"))
    if not year or not model:
        return ""
    if model in ("GTS", "Turbo", "Turbo S"):
        return "PB Plus (105 kWh)" if year >= 2024 else "PB Plus (93.4 kWh)"
    if hp is None:
        return ""
    if year >= 2024:
        if model == "Taycan":
            return "PB Plus (105 kWh)" if hp >= 430 else "PB (89 kWh)"
        if model == "4S":
            return "PB Plus (105 kWh)" if hp >= 540 else "PB (89 kWh)"
    else:
        if model == "Taycan":
            return "PB Plus (93.4 kWh)" if hp >= 450 else "PB (79.2 kWh)"
        if model == "4S":
            return "PB Plus (93.4 kWh)" if hp >= 550 else "PB (79.2 kWh)"
    return ""


def km_per_year(row: dict[str, str]) -> str:
    year = to_int(row.get("year"))
    km = to_int(row.get("km"))
    if not year or km is None:
        return ""
    age = max(2026 - year, 1)
    return str(round(km / age))


def sort_key(row: dict[str, str]) -> tuple[int, int, int, int]:
    active_rank = 0 if row.get("is_active") == "Yes" else 1
    year = to_int(row.get("year")) or 0
    price = to_int(row.get("price")) or 99_999_999
    km = to_int(row.get("km")) or 99_999_999
    return active_rank, -year, price, km


def column_letter(index: int) -> str:
    if index < 1:
        raise ValueError("index must be 1-based")
    letters = []
    while index:
        index, remainder = divmod(index - 1, 26)
        letters.append(string.ascii_uppercase[remainder])
    return "".join(reversed(letters))


INTEGER_COLUMNS = {
    "phone_price",
    "my_offer",
    "year",
    "km",
    "price",
    "seller_years",
    "damage_original_count",
    "damage_painted_count",
    "damage_local_painted_count",
    "damage_changed_count",
    "scrape_run_id",
    "km_per_year",
    "runs_seen_total",
}

FLOAT_COLUMNS = {
    "ask_price_m_tl",
    "phone_price_m_tl",
}


def values_for_sheet(rows: list[dict[str, str]]) -> list[list[object]]:
    return [SHEET_COLUMNS] + [[sheet_value(row, col) for col in SHEET_COLUMNS] for row in rows]


def sheet_value(row: dict[str, str], col_name: str) -> object:
    value = row.get(col_name, "")
    if value == "":
        return ""
    if col_name in INTEGER_COLUMNS:
        number = to_int(value)
        return number if number is not None else value
    if col_name in FLOAT_COLUMNS:
        number = to_float(value)
        return number if number is not None else value
    if col_name == "phone_discount_pct":
        return discount_number(row.get("phone_price"), row.get("price"))
    return value


def sync_google_sheet(
    spreadsheet_id: str,
    worksheet: str,
    service_account: str,
    rows: list[dict[str, str]],
    apply_filter: bool,
) -> list[dict[str, str]]:
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

    existing_rows = read_google_rows(sheets, spreadsheet_id, worksheet)
    existing_filter = read_basic_filter(sheets, spreadsheet_id, sheet_id)
    if existing_rows:
        rows = preserve_manual_columns(rows, existing_rows)

    values = values_for_sheet(rows)
    end_col = column_letter(len(SHEET_COLUMNS))
    clear_range = f"'{worksheet}'!A:{end_col}"
    update_range = f"'{worksheet}'!A1:{end_col}{len(values)}"

    sheets.values().clear(spreadsheetId=spreadsheet_id, range=clear_range, body={}).execute()
    sheets.values().update(
        spreadsheetId=spreadsheet_id,
        range=update_range,
        valueInputOption="RAW",
        body={"values": values},
    ).execute()

    if apply_filter:
        apply_sheet_formatting(sheets, spreadsheet_id, sheet_id, len(values), existing_filter)
    return rows


def read_google_rows(sheets, spreadsheet_id: str, worksheet: str) -> list[dict[str, str]]:
    end_col = column_letter(len(SHEET_COLUMNS))
    response = sheets.values().get(
        spreadsheetId=spreadsheet_id,
        range=f"'{worksheet}'!A:{end_col}",
    ).execute()
    values = response.get("values", [])
    if len(values) < 2:
        return []
    header = [str(value) for value in values[0]]
    rows = []
    for values_row in values[1:]:
        row = {
            header[idx]: str(value)
            for idx, value in enumerate(values_row)
            if idx < len(header)
        }
        if row.get(KEY_COLUMN):
            rows.append(row)
    return rows


def read_basic_filter(sheets, spreadsheet_id: str, sheet_id: int) -> dict | None:
    metadata = sheets.get(spreadsheetId=spreadsheet_id).execute()
    for sheet in metadata.get("sheets", []):
        props = sheet.get("properties", {})
        if int(props.get("sheetId", -1)) == sheet_id:
            return sheet.get("basicFilter")
    return None


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


def apply_sheet_formatting(
    sheets,
    spreadsheet_id: str,
    sheet_id: int,
    row_count: int,
    existing_filter: dict | None,
) -> None:
    requests = [
        {
            "updateSheetProperties": {
                "properties": {
                    "sheetId": sheet_id,
                    "gridProperties": {"frozenRowCount": 1, "frozenColumnCount": len(MANUAL_COLUMNS)},
                },
                "fields": "gridProperties.frozenRowCount,gridProperties.frozenColumnCount",
            }
        },
        {
            "repeatCell": {
                "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1},
                "cell": {
                    "userEnteredFormat": {
                        "textFormat": {"bold": True, "foregroundColor": rgb(1, 1, 1)},
                        "backgroundColor": rgb(0.12, 0.16, 0.23),
                    }
                },
                "fields": "userEnteredFormat(textFormat,backgroundColor)",
            }
        },
        header_band(sheet_id, 0, len(MANUAL_COLUMNS), rgb(0.05, 0.32, 0.58)),
        header_band(sheet_id, len(MANUAL_COLUMNS), len(MANUAL_COLUMNS) + len(DERIVED_COLUMNS), rgb(0.31, 0.18, 0.56)),
        header_band(sheet_id, len(MANUAL_COLUMNS) + len(DERIVED_COLUMNS), len(SHEET_COLUMNS), rgb(0.12, 0.16, 0.23)),
        set_basic_filter_request(sheet_id, row_count, existing_filter),
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
        {
            "repeatCell": {
                "range": {"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": row_count},
                "cell": {"userEnteredFormat": {"wrapStrategy": "CLIP"}},
                "fields": "userEnteredFormat.wrapStrategy",
            }
        },
        {
            "deleteConditionalFormatRule": {
                "sheetId": sheet_id,
                "index": 0,
            }
        },
    ]

    sheets.batchUpdate(spreadsheetId=spreadsheet_id, body={"requests": requests[:-1]}).execute()
    clear_conditional_rules(sheets, spreadsheet_id, sheet_id)

    format_requests = [
        conditional_formula(sheet_id, row_count, "$A2=\"Pass\"", rgb(0.89, 0.89, 0.89), rgb(0.43, 0.43, 0.43)),
        conditional_formula(sheet_id, row_count, "$A2=\"Shortlist\"", rgb(0.82, 0.93, 0.82)),
        conditional_formula(sheet_id, row_count, "$A2=\"Inspect\"", rgb(0.84, 0.78, 0.94)),
        conditional_formula(sheet_id, row_count, "$A2=\"Call\"", rgb(1.00, 0.95, 0.75)),
        conditional_formula(sheet_id, row_count, f"${col('is_active')}2=\"No\"", rgb(0.93, 0.93, 0.93), rgb(0.45, 0.45, 0.45)),
        conditional_formula(sheet_id, row_count, f"${col('heavy_damage_record')}2=\"Evet\"", rgb(0.96, 0.78, 0.76)),
        conditional_formula(sheet_id, row_count, f"IFERROR(VALUE(${col('damage_changed_count')}2),0)>0", rgb(1.00, 0.88, 0.70)),
        conditional_formula(sheet_id, row_count, f"${col('is_clean')}2=\"Yes\"", rgb(0.83, 0.93, 0.84)),
        conditional_formula(sheet_id, row_count, f"${col('warranty')}2=\"Evet\"", rgb(0.80, 0.91, 1.00)),
        number_format(sheet_id, "phone_price", "NUMBER", "#,##0"),
        number_format(sheet_id, "my_offer", "NUMBER", "#,##0"),
        number_format(sheet_id, "price", "NUMBER", "#,##0"),
        number_format(sheet_id, "km", "NUMBER", "#,##0"),
        number_format(sheet_id, "ask_price_m_tl", "NUMBER", "0.000"),
        number_format(sheet_id, "phone_price_m_tl", "NUMBER", "0.000"),
        number_format(sheet_id, "phone_discount_pct", "PERCENT", "0.00%"),
    ]
    sheets.batchUpdate(spreadsheetId=spreadsheet_id, body={"requests": format_requests}).execute()


def clear_conditional_rules(sheets, spreadsheet_id: str, sheet_id: int) -> None:
    metadata = sheets.get(spreadsheetId=spreadsheet_id).execute()
    rule_count = 0
    for sheet in metadata.get("sheets", []):
        props = sheet.get("properties", {})
        if int(props.get("sheetId", -1)) == sheet_id:
            rule_count = len(sheet.get("conditionalFormats", []))
            break
    if not rule_count:
        return
    requests = [
        {"deleteConditionalFormatRule": {"sheetId": sheet_id, "index": 0}}
        for _ in range(rule_count)
    ]
    sheets.batchUpdate(spreadsheetId=spreadsheet_id, body={"requests": requests}).execute()


def header_band(sheet_id: int, start: int, end: int, color: dict[str, float]) -> dict:
    return {
        "repeatCell": {
            "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1, "startColumnIndex": start, "endColumnIndex": end},
            "cell": {
                "userEnteredFormat": {
                    "backgroundColor": color,
                    "textFormat": {"bold": True, "foregroundColor": rgb(1, 1, 1)},
                }
            },
            "fields": "userEnteredFormat(backgroundColor,textFormat)",
        }
    }


def set_basic_filter_request(sheet_id: int, row_count: int, existing_filter: dict | None) -> dict:
    sheet_filter = {
        "range": {
            "sheetId": sheet_id,
            "startRowIndex": 0,
            "endRowIndex": row_count,
            "startColumnIndex": 0,
            "endColumnIndex": len(SHEET_COLUMNS),
        }
    }
    if existing_filter:
        if existing_filter.get("criteria"):
            sheet_filter["criteria"] = existing_filter["criteria"]
        if existing_filter.get("sortSpecs"):
            sheet_filter["sortSpecs"] = existing_filter["sortSpecs"]
    return {"setBasicFilter": {"filter": sheet_filter}}


def conditional_formula(
    sheet_id: int,
    row_count: int,
    formula: str,
    background: dict[str, float],
    foreground: dict[str, float] | None = None,
) -> dict:
    cell_format = {"backgroundColor": background}
    if foreground:
        cell_format["textFormat"] = {"foregroundColor": foreground}
    return {
        "addConditionalFormatRule": {
            "rule": {
                "ranges": [
                    {
                        "sheetId": sheet_id,
                        "startRowIndex": 1,
                        "endRowIndex": row_count,
                        "startColumnIndex": 0,
                        "endColumnIndex": len(SHEET_COLUMNS),
                    }
                ],
                "booleanRule": {
                    "condition": {
                        "type": "CUSTOM_FORMULA",
                        "values": [{"userEnteredValue": f"={formula}"}],
                    },
                    "format": cell_format,
                },
            },
            "index": 0,
        }
    }


def number_format(sheet_id: int, column_name: str, fmt_type: str, pattern: str) -> dict:
    index = SHEET_COLUMNS.index(column_name)
    return {
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 1,
                "startColumnIndex": index,
                "endColumnIndex": index + 1,
            },
            "cell": {
                "userEnteredFormat": {
                    "numberFormat": {"type": fmt_type, "pattern": pattern}
                }
            },
            "fields": "userEnteredFormat.numberFormat",
        }
    }


def col(name: str) -> str:
    return column_letter(SHEET_COLUMNS.index(name) + 1)


def rgb(red: float, green: float, blue: float) -> dict[str, float]:
    return {"red": red, "green": green, "blue": blue}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DB_PATH, help=f"SQLite DB path (default: {DB_PATH})")
    parser.add_argument("--local", default=DEFAULT_LOCAL_CSV, help=f"Local CSV output (default: {DEFAULT_LOCAL_CSV})")
    parser.add_argument("--spreadsheet-id", help="Google Sheet spreadsheet ID")
    parser.add_argument("--worksheet", default=DEFAULT_WORKSHEET, help=f"Worksheet/tab name (default: {DEFAULT_WORKSHEET})")
    parser.add_argument("--service-account", help="Google service account JSON credentials")
    parser.add_argument("--no-filter", action="store_true", help="Do not apply freeze/filter/color formatting")
    args = parser.parse_args()

    _, existing_rows = read_csv_rows(args.local)
    rows = preserve_manual_columns(load_all_cars(args.db), existing_rows)
    write_csv_rows(args.local, SHEET_COLUMNS, rows)

    active_count = sum(1 for row in rows if row.get("is_active") == "Yes")
    inactive_count = len(rows) - active_count

    if args.spreadsheet_id:
        if not args.service_account:
            raise SystemExit("--service-account is required when --spreadsheet-id is set")
        rows = sync_google_sheet(
            spreadsheet_id=args.spreadsheet_id,
            worksheet=args.worksheet,
            service_account=args.service_account,
            rows=rows,
            apply_filter=not args.no_filter,
        )
        write_csv_rows(args.local, SHEET_COLUMNS, rows)
        active_count = sum(1 for row in rows if row.get("is_active") == "Yes")
        inactive_count = len(rows) - active_count
        print(
            f"Synced {len(rows)} total cars to '{args.worksheet}' "
            f"({active_count} active, {inactive_count} inactive)."
        )
    else:
        print(
            f"Wrote {args.local} with {len(rows)} total cars "
            f"({active_count} active, {inactive_count} inactive)."
        )


if __name__ == "__main__":
    main()
