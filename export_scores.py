#!/usr/bin/env python3
"""Score every active Taycan with the notebook's Value Score and export to CSV for Excel.

Universe: every currently-ACTIVE car (deduped by sahibinden_id, taken from its most recent
detailed row, with current price/km), excluding Cross Turismo — the same set the notebook
scores. Mirrors analysis.ipynb Section 2 (disqualification), Section 3 (derived metrics) and
Section 5 (value score). Adds a `price_history` column (price changes across scrape runs) and
the bargain-signal metrics from Section 15.

Usage:
    python export_scores.py                 # -> taycan_scores.csv
    python export_scores.py -o my.csv
"""
import argparse
import os
import re
from datetime import datetime

import pandas as pd

from scraper.parsers import parse_listing_date
from scraper.signals import compute_car_metrics

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "taycan.db")

# --- Disqualification thresholds (kept in sync with notebook Section 2) ---
CURRENT_YEAR = 2026
DISQUALIFY_HEAVY_DAMAGE = True
DISQUALIFY_CHANGED_THRESHOLD = 3
NEW_CAR_YEAR_THRESHOLD = 2023
DISQUALIFY_NEW_CAR_CHANGED = False


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

    for col in ["price_score", "km_score", "damage_score", "feature_score", "depr_score"]:
        df[col] = scores[col].round(3)
    return df


def bargain_and_history(conn):
    """Per car: bargain-signal metrics + a readable price-change-history string."""
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
        # price-change history: collapse consecutive equal prices into change points
        pts, compact = [(o["run_date"], o["price"]) for o in obs if o["price"] is not None], []
        for d, p in pts:
            if not compact or compact[-1][1] != p:
                compact.append((d, p))
        out[sid] = {
            "motivation_score": round(m["motivation_score"], 1),
            "price_drop_pct": round(m["price_drop_pct"], 1),
            "num_price_cuts": m["num_price_cuts"],
            "bump_count": m["bump_count"],
            "days_on_market": m["days_on_market"],
            "runs_seen": m["runs_seen"],
            "price_history": " -> ".join(f"{p:,} ({d.strftime('%d %b %y')})" for d, p in compact),
        }
    return out


COLUMNS = [
    "rank", "value_score", "model", "year", "km", "price",
    "motivation_score", "price_drop_pct", "num_price_cuts", "bump_count", "days_on_market",
    "is_clean", "is_bayi", "damage_changed_count", "damage_painted_count", "damage_local_painted_count",
    "feature_count", "battery", "seller_type", "heavy_damage_record", "km_per_year",
    "price_score", "km_score", "damage_score", "feature_score", "depr_score",
    "trim_mult", "clean_bonus", "bayi_bonus", "new_changed_penalty",
    "price_history", "dq_reason", "sahibinden_id", "title", "url",
]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-o", "--output", default="taycan_scores.csv", help="CSV path (default: taycan_scores.csv)")
    ap.add_argument("--db", default=DB_PATH, help="SQLite DB path")
    args = ap.parse_args()

    import sqlite3
    conn = sqlite3.connect(args.db)
    df, df_features = load_active_scorable(conn)
    df = add_derived_metrics(df)
    df = add_disqualification(df)

    # Value score is computed on the eligible set only (matching the notebook's normalization);
    # disqualified cars are still listed (flagged via dq_reason) with a blank value_score.
    eligible = calculate_value_score(df[df["dq_reason"].isna()].copy(), df_features)
    out = pd.concat([eligible, df[df["dq_reason"].notna()].copy()], ignore_index=True, sort=False)

    bh = bargain_and_history(conn)
    conn.close()
    for col in ["motivation_score", "price_drop_pct", "num_price_cuts", "bump_count",
                "days_on_market", "runs_seen", "price_history"]:
        out[col] = out["sahibinden_id"].map(lambda s, c=col: bh.get(s, {}).get(c))

    out = out.sort_values("value_score", ascending=False, na_position="last").reset_index(drop=True)
    out.insert(0, "rank", range(1, len(out) + 1))
    out["is_clean"] = out["is_clean"].map({True: "Yes", False: "No"})
    out["is_bayi"] = out["is_bayi"].map({True: "Yes", False: "No"})

    cols = [c for c in COLUMNS if c in out.columns]
    # utf-8-sig so Excel renders Turkish characters correctly
    out[cols].to_csv(args.output, index=False, encoding="utf-8-sig")
    print(f"Wrote {len(out)} cars to {args.output}  "
          f"({out['value_score'].notna().sum()} scored, {out['dq_reason'].notna().sum()} disqualified)")


if __name__ == "__main__":
    main()
