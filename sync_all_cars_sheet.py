#!/usr/bin/env python3
"""Export every Taycan ever seen, score/rank it, and sync it to Google Sheets.

This is the shopping cockpit export. It keeps one row per `sahibinden_id`,
including inactive/no-longer-listed cars, preserves manual notes across
refreshes, and carries the notebook's value-score ranking + bargain signals
(rank, value_score, motivation_score, ...) so you can sort by them in the sheet.

The spreadsheet id and the service-account credentials are wired in: with the
Bitwarden vault unlocked (`export BW_SESSION="$(bw unlock --raw)"`), a bare
`python sync_all_cars_sheet.py` writes the local CSV and syncs the Google Sheet.

Local CSV only:
    python sync_all_cars_sheet.py --local-only

Google Sheets (defaults baked in):
    python sync_all_cars_sheet.py
    python sync_all_cars_sheet.py --spreadsheet-id SHEET_ID --service-account creds.json
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import socket
import sqlite3
import string
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

import pandas as pd

from scraper.parsers import parse_listing_date
from scraper.signals import compute_car_metrics
from valuation import VALUATION_EXPORT_COLUMNS, valuation_by_id


DB_PATH = "taycan.db"
DEFAULT_LOCAL_CSV = "taycan_all_cars_sheet.csv"
DEFAULT_WORKSHEET = "All Cars"
DEFAULT_SPREADSHEET_ID = "1CBdGStPruim7T9bjvuKX_JTD_MRBWCnlE5o9iwHgARE"
KEY_COLUMN = "sahibinden_id"

# Service-account credentials are resolved from --service-account, then
# $GOOGLE_APPLICATION_CREDENTIALS, then fetched from Bitwarden (vault must be
# unlocked first: `export BW_SESSION="$(bw unlock --raw)"`).
BW_SERVICE_ACCOUNT_ITEM = "fce62dcd-d2fb-4d14-af88-ab8154ac6551"
SERVICE_ACCOUNT_PATH = os.path.expanduser("~/.config/gcloud/keys/sheetswriter.json")

# --- Scoring/ranking config (moved from the retired export_scores.py; kept in
# sync with analysis.ipynb Section 2/3/5). ---
CURRENT_YEAR = 2026
DISQUALIFY_HEAVY_DAMAGE = True
DISQUALIFY_CHANGED_THRESHOLD = 3
NEW_CAR_YEAR_THRESHOLD = 2023
DISQUALIFY_NEW_CAR_CHANGED = False

MANUAL_COLUMNS = [
    "my_priority",
]

DERIVED_COLUMNS = [
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
    "sahibinden_id",
    "url",
    "title",
    "model",
    "year",
    "km",
    "color",
    "body_type",
    "price",
    "listing_date",
    "location_city",
    "location_district",
    "damage_original_count",
    "damage_painted_count",
    "damage_local_painted_count",
    "damage_changed_count",
    "scrape_run_id",
    "latest_seen_at",
    "description",
]

SCORE_COLUMNS = [
    "rank",
    "value_score",
    "motivation_score",
    "price_drop_pct",
    "num_price_cuts",
    "bump_count",
    "days_on_market",
    "dq_reason",
]

# Hedonic fair-value model outputs (valuation.py, kept in sync with
# analysis.ipynb Section 16). Blank for cars outside the buyable universe
# (inactive / heavy-damage-record).
VALUATION_COLUMNS = list(VALUATION_EXPORT_COLUMNS)

# On-screen column order. VISIBLE_COLUMNS are shown in this exact order; every
# other defined column is appended after them and hidden in the tab. The four
# group lists above still drive the logic (manual preservation, source fill,
# scoring) and header colours — this only fixes order + visibility, so any name
# here must belong to one of those groups.
VISIBLE_COLUMNS = [
    "my_priority",
    "rank",
    "value_score",
    "motivation_score",
    "price_drop_pct",
    "num_price_cuts",
    "bump_count",
    "days_on_market",
    "dq_reason",
    "price",
    "fair_ask_tl",
    "bargain_pct",
    "offer_open_tl",
    "offer_settle_tl",
    "tramer_tl",
    "verify_first",
    "is_clean",
    "is_bayi",
    "battery",
    "model",
    "body_type",
    "year",
    "km",
    "color",
    "km_per_year",
    "first_seen_date",
    "last_seen_date",
    "runs_seen_total",
    "price_history",
    "is_active",
    "sahibinden_id",
    "url",
    "title",
    "listing_date",
    "location_city",
]

_ALL_DEFINED = MANUAL_COLUMNS + SCORE_COLUMNS + VALUATION_COLUMNS + DERIVED_COLUMNS + SOURCE_COLUMNS
HIDDEN_COLUMNS = [c for c in _ALL_DEFINED if c not in VISIBLE_COLUMNS]
SHEET_COLUMNS = VISIBLE_COLUMNS + HIDDEN_COLUMNS

assert set(VISIBLE_COLUMNS) <= set(_ALL_DEFINED), \
    f"VISIBLE_COLUMNS names not defined in any group: {set(VISIBLE_COLUMNS) - set(_ALL_DEFINED)}"
assert len(SHEET_COLUMNS) == len(set(SHEET_COLUMNS)), "duplicate column in SHEET_COLUMNS"

# Header colour per column group, applied to contiguous runs so any column order
# still bands correctly. Stored as tuples; rgb() is called at format time.
GROUP_COLORS = {
    "manual": (0.05, 0.32, 0.58),
    "score": (0.13, 0.46, 0.36),
    "valuation": (0.72, 0.38, 0.08),
    "derived": (0.31, 0.18, 0.56),
    "source": (0.12, 0.16, 0.23),
}

# Score columns that should be written to the sheet as integers (the rest of
# SCORE_COLUMNS are floats or free text).
INT_SCORE_COLUMNS = {"rank", "num_price_cuts", "bump_count", "days_on_market"}


@dataclass(frozen=True)
class SyncResult:
    active_count: int
    inactive_count: int
    total_count: int


# ----------------------------------------------------------------------------
# Scoring / ranking (the notebook's Value Score + bargain signals).
# Moved verbatim from the retired export_scores.py; mirrors analysis.ipynb
# Section 2 (disqualification), Section 3 (derived metrics), Section 5 (value
# score). Operates on a pandas view of the active, detailed car universe and is
# the single source of truth for the rank/value_score/signal columns.
# ----------------------------------------------------------------------------

SCORE_EXPORT_COLUMNS = [
    "rank", "value_score", "motivation_score", "price_drop_pct",
    "num_price_cuts", "bump_count", "days_on_market", "dq_reason",
]


def load_active_scorable(conn):
    """All currently-active cars, deduped by sahibinden_id, on their most recent DETAILED
    row, with current price/km, excluding Cross Turismo. Returns (df, df_features)."""
    all_rows = pd.read_sql("SELECT * FROM listings", conn)
    latest = all_rows.loc[all_rows.groupby("sahibinden_id")["scrape_run_id"].idxmax()].set_index("sahibinden_id")
    active_ids = set(latest.index[latest["is_active"] == 1])
    det = all_rows[all_rows["detail_scraped"] == 1]
    detrows = det.loc[det.groupby("sahibinden_id")["scrape_run_id"].idxmax()].set_index("sahibinden_id")
    ids = sorted(active_ids & set(detrows.index))

    df = detrows.loc[ids].copy()
    df["price"] = latest.loc[ids, "price"]   # refresh volatile current-market fields
    df["km"] = latest.loc[ids, "km"]
    df = df.reset_index()
    df = df[df["body_type"].fillna("") != "Station Wagon"].copy()

    picked = tuple(int(x) for x in df["id"]) or (-1,)
    ph = ",".join("?" * len(picked))
    df_features = pd.read_sql(f"SELECT * FROM features WHERE listing_id IN ({ph})", conn, params=picked)
    return df, df_features


def add_disqualification(df):
    changed = df["damage_changed_count"].fillna(0)
    mask_heavy = df["heavy_damage_record"] == "Evet"
    mask_changed = changed >= DISQUALIFY_CHANGED_THRESHOLD
    mask_new_changed = (df["year"] >= NEW_CAR_YEAR_THRESHOLD) & (changed >= 1)
    reasons = []
    for idx in df.index:
        r = []
        if DISQUALIFY_HEAVY_DAMAGE and mask_heavy[idx]:
            r.append("Heavy damage record")
        if mask_changed[idx]:
            r.append(f"{int(changed[idx])} changed parts")
        if DISQUALIFY_NEW_CAR_CHANGED and mask_new_changed[idx] and not mask_changed[idx]:
            r.append("newer car w/ changed part")
        reasons.append("; ".join(r) if r else None)
    df["dq_reason"] = reasons
    return df


def _parse_hp(val):
    if not val or pd.isna(val):
        return None
    m = re.search(r"(\d+)\s*-\s*(\d+)", str(val))
    if m:
        return (int(m.group(1)) + int(m.group(2))) / 2
    m = re.search(r"(\d+)", str(val))
    return int(m.group(1)) if m else None


def _detect_battery(row):
    year, model, hp = row.get("year"), row.get("model"), _parse_hp(row.get("engine_power"))
    if not year or not model:
        return None
    if model in ("GTS", "Turbo", "Turbo S") or "Cross Turismo" in str(model):
        return "PB Plus (105 kWh)" if year >= 2024 else "PB Plus (93.4 kWh)"
    if not hp:
        return None
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
    return None


def add_derived_metrics(df):
    df["car_age"] = CURRENT_YEAR - df["year"]
    df["km_per_year"] = df.apply(
        lambda r: round(r["km"] / max(r["car_age"], 1)) if pd.notna(r["km"]) else None, axis=1)
    df["is_clean"] = ((df["damage_changed_count"].fillna(0) == 0) &
                      (df["damage_painted_count"].fillna(0) == 0) &
                      (df["damage_local_painted_count"].fillna(0) == 0))

    def detect_bayi(row):
        text = f"{row.get('title', '') or ''} {row.get('description', '') or ''}".lower()
        return bool(re.search(r"\bbayi\b|\bbayii\b|\bdoğuş\b|\bdogus\b", text))
    df["is_bayi"] = df.apply(detect_bayi, axis=1)
    df["battery"] = df.apply(_detect_battery, axis=1)
    df["risk_new_changed"] = (df["year"] >= NEW_CAR_YEAR_THRESHOLD) & (df["damage_changed_count"].fillna(0) >= 1)
    return df


def calculate_value_score(df, df_features):
    """Section 5 composite (verbatim from analysis.ipynb)."""
    scores = pd.DataFrame(index=df.index)
    df["price_zscore"] = df.groupby(["model", "year"])["price"].transform(
        lambda x: (x - x.mean()) / x.std() if x.std() > 0 else 0)
    scores["price_score"] = -df["price_zscore"]
    df["expected_km"] = df["car_age"] * 15000
    df["km_ratio"] = df.apply(
        lambda r: r["km"] / r["expected_km"] if r["expected_km"] > 0 and r["km"] is not None else 1, axis=1)
    scores["km_score"] = 1 - df["km_ratio"].clip(0, 2) / 2
    df["damage_penalty"] = (df["damage_changed_count"].fillna(0) * 3 +
                            df["damage_painted_count"].fillna(0) * 1.5 +
                            df["damage_local_painted_count"].fillna(0) * 1)
    max_penalty = df["damage_penalty"].max() if df["damage_penalty"].max() > 0 else 1
    scores["damage_score"] = 1 - (df["damage_penalty"] / max_penalty)
    feature_counts = df_features[df_features["is_present"] == 1].groupby("listing_id").size()
    df["feature_count"] = df["id"].map(feature_counts).fillna(0).astype(int)
    max_features = df["feature_count"].max() if df["feature_count"].max() > 0 else 1
    scores["feature_score"] = df["feature_count"] / max_features

    def depr_score(row):
        y = row["year"]
        if y >= 2024:
            return 1.0
        elif y == 2023:
            return 0.6
        elif y == 2022:
            return 0.4
        elif y == 2021:
            return 0.25
        return 0.1
    scores["depr_score"] = df.apply(depr_score, axis=1)

    df["value_score_raw"] = (scores["price_score"] * 0.25 + scores["km_score"] * 0.20 +
                             scores["damage_score"] * 0.20 + scores["feature_score"] * 0.10 +
                             scores["depr_score"] * 0.25)
    vmin, vmax = df["value_score_raw"].min(), df["value_score_raw"].max()
    df["value_score_raw"] = ((df["value_score_raw"] - vmin) / (vmax - vmin) * 100).round(1) if vmax > vmin else 50.0

    df["trim_mult"] = df["model"].map({"GTS": 1.10, "Turbo S": 1.08, "Turbo": 1.05, "4S": 1.0, "Taycan": 0.95}).fillna(1.0)
    df["clean_bonus"] = df["is_clean"].astype(float) * 5.0
    df["bayi_bonus"] = df["is_bayi"].astype(float) * 3.0
    df["new_changed_penalty"] = df.get("risk_new_changed", False).astype(float) * 7.0
    df["value_score"] = (df["value_score_raw"] * df["trim_mult"] + df["clean_bonus"] +
                         df["bayi_bonus"] - df["new_changed_penalty"]).round(1)
    vmin2, vmax2 = df["value_score"].min(), df["value_score"].max()
    df["value_score"] = ((df["value_score"] - vmin2) / (vmax2 - vmin2) * 100).round(1) if vmax2 > vmin2 else 50.0
    return df


def bargain_and_history(conn):
    """Per car: bargain-signal metrics keyed by sahibinden_id."""
    hist = pd.read_sql(
        """SELECT l.sahibinden_id, l.scrape_run_id, l.listing_date, l.price, r.started_at
           FROM listings l JOIN scrape_runs r ON r.id = l.scrape_run_id
           ORDER BY l.sahibinden_id, l.scrape_run_id""", conn)
    out = {}
    for sid, g in hist.groupby("sahibinden_id"):
        g = g.sort_values("scrape_run_id")
        obs = [{"run_date": datetime.fromisoformat(s).date(),
                "listing_date": parse_listing_date(ld),
                "price": (int(p) if pd.notna(p) else None)}
               for s, ld, p in zip(g["started_at"], g["listing_date"], g["price"])]
        m = compute_car_metrics(obs)
        out[sid] = {
            "motivation_score": round(m["motivation_score"], 1),
            "price_drop_pct": round(m["price_drop_pct"], 1),
            "num_price_cuts": m["num_price_cuts"],
            "bump_count": m["bump_count"],
            "days_on_market": m["days_on_market"],
        }
    return out


def score_active_cars(db_path: str) -> "pd.DataFrame":
    """Return the scored, ranked active-car universe (one row per sahibinden_id).

    Eligible cars get a value_score and are ranked 1..N by it; disqualified cars
    are kept (with dq_reason set, value_score blank) and ranked after."""
    conn = sqlite3.connect(db_path)
    try:
        df, df_features = load_active_scorable(conn)
        df = add_derived_metrics(df)
        df = add_disqualification(df)
        eligible = calculate_value_score(df[df["dq_reason"].isna()].copy(), df_features)
        out = pd.concat([eligible, df[df["dq_reason"].notna()].copy()], ignore_index=True, sort=False)
        bargains = bargain_and_history(conn)
    finally:
        conn.close()

    for col in ["motivation_score", "price_drop_pct", "num_price_cuts", "bump_count", "days_on_market"]:
        out[col] = out["sahibinden_id"].map(lambda s, c=col: bargains.get(s, {}).get(c))

    out = out.sort_values("value_score", ascending=False, na_position="last").reset_index(drop=True)
    out.insert(0, "rank", range(1, len(out) + 1))
    return out


def scores_by_id(db_path: str) -> dict[str, dict[str, str]]:
    """Map sahibinden_id -> {SCORE_EXPORT_COLUMNS as display strings}. NaN/None -> ''."""
    out = score_active_cars(db_path)
    result: dict[str, dict[str, str]] = {}
    for _, row in out.iterrows():
        sid = str(row["sahibinden_id"])
        entry: dict[str, str] = {}
        for col in SCORE_EXPORT_COLUMNS:
            value = row.get(col)
            if isinstance(value, str):
                entry[col] = value
            elif pd.isna(value):
                entry[col] = ""
            elif col in INT_SCORE_COLUMNS:
                entry[col] = str(int(value))
            else:
                entry[col] = str(value)
        result[sid] = entry
    return result


def read_csv_rows(path: str | os.PathLike[str]) -> tuple[list[str], list[dict[str, str]]]:
    file_path = Path(path)
    if not file_path.exists():
        return [], []
    with file_path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return list(reader.fieldnames or []), [dict(row) for row in reader]


def write_csv_rows(path: str | os.PathLike[str], header: list[str], rows: Iterable[dict[str, str]]) -> None:
    with Path(path).open("w", newline="", encoding="utf-8-sig") as f:
        # extrasaction="ignore": rows may carry internal working keys (e.g. the
        # detail_scraped flag used by clean_status) that are not sheet columns.
        writer = csv.DictWriter(f, fieldnames=header, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def connect_readonly(db_path: str) -> sqlite3.Connection:
    uri = f"file:{Path(db_path).resolve()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def load_all_cars(db_path: str) -> list[dict[str, str]]:
    scores = scores_by_id(db_path)
    try:
        valuations = valuation_by_id(db_path)
    except Exception as exc:  # model failure must not block the sheet sync
        print(f"WARNING: valuation model failed ({exc}); valuation columns left blank.")
        valuations = {}
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
        # engine_power is no longer a displayed column, so read it from the full DB row.
        row["battery"] = detect_battery(merged)
        row["km_per_year"] = km_per_year(row)
        row["first_seen_date"] = _clean(seen["first_seen_date"] if seen else "")
        row["last_seen_date"] = _clean(seen["last_seen_date"] if seen else "")
        row["runs_seen_total"] = _clean(seen["runs_seen_total"] if seen else "")
        row["price_history"] = history_by_id.get(sid, "")
        car_scores = scores.get(str(sid), {})
        for score_col in SCORE_COLUMNS:
            row[score_col] = car_scores.get(score_col, "")
        car_vals = valuations.get(str(sid), {})
        for val_col in VALUATION_COLUMNS:
            row[val_col] = car_vals.get(val_col, "")
        rows.append(row)

    # Sheet carries only the shoppable universe: active cars, sedan bodies.
    rows = [
        r for r in rows
        if r.get("is_active") == "Yes"
        and r.get("body_type") not in ("Station Wagon", "Hatchback 5 kapı")
        and "Cross Turismo" not in (r.get("model") or "")
    ]
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
    "year",
    "km",
    "price",
    "damage_original_count",
    "damage_painted_count",
    "damage_local_painted_count",
    "damage_changed_count",
    "scrape_run_id",
    "km_per_year",
    "runs_seen_total",
    "rank",
    "num_price_cuts",
    "bump_count",
    "days_on_market",
    "fair_ask_tl",
    "offer_open_tl",
    "offer_settle_tl",
    "drop_paint_tl",
    "drop_changed_tl",
    "drop_10k_km_tl",
    "drop_1yr_tl",
    "tramer_tl",
}

FLOAT_COLUMNS = {
    "value_score",
    "motivation_score",
    "price_drop_pct",
    "bargain_pct",
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

    # httplib2 has no default socket timeout, so a half-open connection can hang
    # the sync forever. Cap it; the API calls here complete in well under a minute.
    socket.setdefaulttimeout(120)

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
    update_range = f"'{worksheet}'!A1:{end_col}{len(values)}"

    # Clear the ENTIRE sheet, not a fixed A:<end_col> window. A narrower clear
    # leaves stale trailing columns from any previous/wider layout behind, which
    # then read back as duplicate columns.
    sheets.values().clear(spreadsheetId=spreadsheet_id, range=f"'{worksheet}'", body={}).execute()
    sheets.values().update(
        spreadsheetId=spreadsheet_id,
        range=update_range,
        valueInputOption="RAW",
        body={"values": values},
    ).execute()
    trim_surplus_columns(sheets, spreadsheet_id, sheet_id, len(SHEET_COLUMNS))

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


def trim_surplus_columns(sheets, spreadsheet_id: str, sheet_id: int, keep_cols: int) -> None:
    """Delete any grid columns past keep_cols so the sheet is exactly SHEET_COLUMNS wide."""
    metadata = sheets.get(spreadsheetId=spreadsheet_id).execute()
    col_count = 0
    for sheet in metadata.get("sheets", []):
        props = sheet.get("properties", {})
        if int(props.get("sheetId", -1)) == sheet_id:
            col_count = int(props.get("gridProperties", {}).get("columnCount", 0))
            break
    if col_count > keep_cols:
        sheets.batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{
                "deleteDimension": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "COLUMNS",
                        "startIndex": keep_cols,
                        "endIndex": col_count,
                    }
                }
            }]},
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
                    "gridProperties": {"frozenRowCount": 1, "frozenColumnCount": 0},
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
        *header_band_requests(sheet_id),
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
        conditional_formula(sheet_id, row_count, f"${col('is_active')}2=\"No\"", rgb(0.93, 0.93, 0.93), rgb(0.45, 0.45, 0.45)),
        conditional_formula(sheet_id, row_count, f"N(${col('damage_changed_count')}2)>0", rgb(1.00, 0.88, 0.70)),
        conditional_formula(sheet_id, row_count, f"${col('is_clean')}2=\"Yes\"", rgb(0.83, 0.93, 0.84)),
        number_format(sheet_id, "price", "NUMBER", '#,##0" TL"'),
        number_format(sheet_id, "km", "NUMBER", "#,##0"),
        number_format(sheet_id, "fair_ask_tl", "NUMBER", '#,##0" TL"'),
        number_format(sheet_id, "bargain_pct", "NUMBER", '0.0"%"'),
        number_format(sheet_id, "offer_open_tl", "NUMBER", '#,##0" TL"'),
        number_format(sheet_id, "offer_settle_tl", "NUMBER", '#,##0" TL"'),
        number_format(sheet_id, "drop_paint_tl", "NUMBER", '#,##0" TL"'),
        number_format(sheet_id, "drop_changed_tl", "NUMBER", '#,##0" TL"'),
        number_format(sheet_id, "drop_10k_km_tl", "NUMBER", '#,##0" TL"'),
        number_format(sheet_id, "drop_1yr_tl", "NUMBER", '#,##0" TL"'),
        number_format(sheet_id, "tramer_tl", "NUMBER", '#,##0" TL"'),
        number_format(sheet_id, "rank", "NUMBER", "0"),
        number_format(sheet_id, "value_score", "NUMBER", "0.0"),
        number_format(sheet_id, "motivation_score", "NUMBER", "0.0"),
        number_format(sheet_id, "price_drop_pct", "NUMBER", "0.0"),
        number_format(sheet_id, "num_price_cuts", "NUMBER", "0"),
        number_format(sheet_id, "bump_count", "NUMBER", "0"),
        number_format(sheet_id, "days_on_market", "NUMBER", "0"),
        *column_visibility_requests(sheet_id),
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


def _group_of(col_name: str) -> str:
    if col_name in MANUAL_COLUMNS:
        return "manual"
    if col_name in SCORE_COLUMNS:
        return "score"
    if col_name in VALUATION_COLUMNS:
        return "valuation"
    if col_name in DERIVED_COLUMNS:
        return "derived"
    return "source"


def header_band_requests(sheet_id: int) -> list[dict]:
    """Colour each header cell by its column group, merging contiguous same-group runs."""
    requests = []
    start = 0
    while start < len(SHEET_COLUMNS):
        group = _group_of(SHEET_COLUMNS[start])
        end = start + 1
        while end < len(SHEET_COLUMNS) and _group_of(SHEET_COLUMNS[end]) == group:
            end += 1
        requests.append(header_band(sheet_id, start, end, rgb(*GROUP_COLORS[group])))
        start = end
    return requests


def column_visibility_requests(sheet_id: int) -> list[dict]:
    """Show the first len(VISIBLE_COLUMNS) columns and hide the rest, deterministically."""
    n_visible = len(VISIBLE_COLUMNS)
    requests = [{
        "updateDimensionProperties": {
            "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 0, "endIndex": n_visible},
            "properties": {"hiddenByUser": False},
            "fields": "hiddenByUser",
        }
    }]
    if len(SHEET_COLUMNS) > n_visible:
        requests.append({
            "updateDimensionProperties": {
                "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": n_visible, "endIndex": len(SHEET_COLUMNS)},
                "properties": {"hiddenByUser": True},
                "fields": "hiddenByUser",
            }
        })
    return requests


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
        # Drop any saved criteria/sort that point past the (possibly narrower) new
        # column set, or the API rejects the whole request.
        max_idx = len(SHEET_COLUMNS)
        criteria = {k: v for k, v in (existing_filter.get("criteria") or {}).items() if int(k) < max_idx}
        if criteria:
            sheet_filter["criteria"] = criteria
        sort_specs = [s for s in (existing_filter.get("sortSpecs") or []) if int(s.get("dimensionIndex", 0)) < max_idx]
        if sort_specs:
            sheet_filter["sortSpecs"] = sort_specs
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


def resolve_service_account(explicit: str | None) -> str:
    """Resolve the service-account JSON path: explicit flag, then env var, then Bitwarden."""
    if explicit:
        return explicit
    env_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if env_path and Path(env_path).exists():
        return env_path
    return fetch_service_account_from_bitwarden()


def fetch_service_account_from_bitwarden() -> str:
    """Materialize the service-account JSON from the Bitwarden note to a 0600 file.

    Requires the vault to be unlocked: `export BW_SESSION="$(bw unlock --raw)"`."""
    session = os.environ.get("BW_SESSION")
    if not session:
        raise SystemExit(
            "No Google credentials available. Unlock Bitwarden first:\n"
            '    export BW_SESSION="$(bw unlock --raw)"\n'
            "or pass --service-account / set GOOGLE_APPLICATION_CREDENTIALS."
        )
    try:
        result = subprocess.run(
            ["bw", "get", "notes", BW_SERVICE_ACCOUNT_ITEM, "--session", session],
            capture_output=True, text=True, check=True,
        )
    except FileNotFoundError as exc:
        raise SystemExit(
            "Bitwarden CLI 'bw' not found on PATH. Install it, or pass --service-account."
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise SystemExit(
            f"Bitwarden could not read the service-account note: {(exc.stderr or '').strip()}"
        ) from exc

    note = result.stdout.strip()
    try:
        json.loads(note)
    except json.JSONDecodeError as exc:
        raise SystemExit("Bitwarden note is not valid service-account JSON.") from exc

    dest = Path(SERVICE_ACCOUNT_PATH)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(note)
    dest.chmod(0o600)
    return str(dest)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DB_PATH, help=f"SQLite DB path (default: {DB_PATH})")
    parser.add_argument("--local", default=DEFAULT_LOCAL_CSV, help=f"Local CSV output (default: {DEFAULT_LOCAL_CSV})")
    parser.add_argument("--spreadsheet-id", default=DEFAULT_SPREADSHEET_ID,
                        help="Google Sheet spreadsheet ID (default: baked-in All Cars sheet)")
    parser.add_argument("--worksheet", default=DEFAULT_WORKSHEET, help=f"Worksheet/tab name (default: {DEFAULT_WORKSHEET})")
    parser.add_argument("--service-account", default=None,
                        help="Service-account JSON path (default: $GOOGLE_APPLICATION_CREDENTIALS, then Bitwarden)")
    parser.add_argument("--local-only", action="store_true", help="Write the local CSV only; skip Google Sheets")
    parser.add_argument("--no-filter", action="store_true", help="Do not apply freeze/filter/color formatting")
    args = parser.parse_args()

    _, existing_rows = read_csv_rows(args.local)
    rows = preserve_manual_columns(load_all_cars(args.db), existing_rows)
    write_csv_rows(args.local, SHEET_COLUMNS, rows)

    active_count = sum(1 for row in rows if row.get("is_active") == "Yes")
    inactive_count = len(rows) - active_count

    if args.local_only or not args.spreadsheet_id:
        print(
            f"Wrote {args.local} with {len(rows)} total cars "
            f"({active_count} active, {inactive_count} inactive)."
        )
        return

    service_account = resolve_service_account(args.service_account)
    rows = sync_google_sheet(
        spreadsheet_id=args.spreadsheet_id,
        worksheet=args.worksheet,
        service_account=service_account,
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


if __name__ == "__main__":
    main()
