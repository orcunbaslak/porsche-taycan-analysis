"""Hedonic fair-value model + offer engine for every buyable listing.

Fits log(price) on trim / ruhsat year / km (age-bucketed slopes) / painted
panels / değişen-class / declared-tramer / body type over the v_buyable view
(active, latest row per car, heavy-damage excluded), then derives:

- fair_ask      what the car *should* be listed at (ask basis)
- bargain_pct   how far under (+) / over (-) fair ask it is priced
- open/settle   suggested offer band (motivation-signal driven, fair-capped)
- drop_*        what-if columns: TL lost if a panel gets painted / a panel is
                changed / +10k km / +1 year of age
- trim_suspect  hp or traction contradicts the claimed trim (mislabeled ad)
- tramer_tl     tramer amount confessed in the free-text description
- verify_first  bargain too good to be true until proven otherwise

KEPT IN SYNC with analysis.ipynb Section 16a — same model spec and constants;
if you change one, change the other. Used by sync_all_cars_sheet.py to add
the valuation columns to the All Cars sheet.
"""

import re
import sqlite3

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

TRIM_MAP = {"Taycan": "base", "Cross Turismo": "base", "4 Cross Turismo": "4",
            "4S Cross Turismo": "4S", "4S": "4S", "GTS": "GTS", "Turbo": "Turbo",
            "Turbo S": "TurboS"}
TRIM_HP_FLOOR = {"4S": 450, "GTS": 550, "Turbo": 600, "TurboS": 700}
WAGON_BODIES = ("Station Wagon", "Hatchback 5 kapı")


def _hp(s):
    nums = [int(n) for n in re.findall(r"\d+", str(s or ""))]
    return max(nums) if nums else np.nan


def _tramer_tl(desc):
    t = str(desc or "").upper().replace("İ", "I")
    if "TRAMER" not in t:
        return np.nan
    if re.search(r"TRAMERS[I]?Z|TRAMER[I]?\s*(KAYDI\s*)?(YOKTUR|YOK|BULUNMAM)", t):
        return 0.0
    m = re.search(r"TRAMER[^0-9]{0,25}(\d[\d.,]*)\s*(BIN)?", t)
    if not m:
        return np.nan
    val = float(m.group(1).rstrip(".,").split(",")[0].replace(".", ""))
    if m.group(2):
        val *= 1000
    return val if 0 < val <= 5_000_000 else np.nan


def compute_fair_values(db_path: str = "taycan.db") -> pd.DataFrame:
    """Return the buyable universe with fair_ask / offers / what-if columns."""
    conn = sqlite3.connect(db_path)
    try:
        fv = pd.read_sql_query(
            """
            SELECT v.*, s.motivation_score, s.days_on_market, s.num_price_cuts
            FROM v_buyable v LEFT JOIN listing_signals s ON s.sahibinden_id = v.sahibinden_id
            WHERE v.price > 1000000 AND v.year >= 2019
            """,
            conn,
        )
    finally:
        conn.close()

    fv["is_wagon"] = fv["body_type"].isin(WAGON_BODIES).astype(int)
    fv["trim"] = fv["model"].map(TRIM_MAP).fillna("base")
    fv["hp"] = fv["engine_power"].map(_hp)
    _hp_bad = [hp < TRIM_HP_FLOOR.get(t, 0) if pd.notna(hp) else False
               for t, hp in zip(fv["trim"], fv["hp"])]
    _rwd_bad = (fv["trim"] != "base") & fv["traction"].fillna("").str.contains("Arkadan")
    fv["trim_suspect"] = np.array(_hp_bad) | _rwd_bad.to_numpy()
    fv["tramer_tl"] = fv["description"].map(_tramer_tl)
    fv["has_tramer"] = (fv["tramer_tl"] > 0).astype(int)

    fv["km10"] = fv["km"].clip(0, 200000) / 10000.0
    _age = 2026 - fv["year"]
    fv["km_young"] = np.where(_age <= 2, fv["km10"], 0.0)
    fv["km_mid"] = np.where((_age >= 3) & (_age <= 4), fv["km10"], 0.0)
    fv["km_old"] = np.where(_age >= 5, fv["km10"], 0.0)
    fv["painted"] = (fv["damage_painted_count"].fillna(0)
                     + fv["damage_local_painted_count"].fillna(0)).clip(0, 4)
    fv["any_changed"] = (fv["damage_changed_count"].fillna(0) > 0).astype(int)
    fv["log_price"] = np.log(fv["price"])

    hedonic = smf.ols(
        "log_price ~ C(trim, Treatment('base')) + C(year) + km_young + km_mid + km_old"
        " + painted + any_changed + has_tramer + is_wagon",
        data=fv[~fv["trim_suspect"]],
    ).fit()

    fv["fair_ask"] = np.exp(hedonic.predict(fv))
    fv["bargain_pct"] = (fv["fair_ask"] - fv["price"]) / fv["fair_ask"] * 100
    fv["verify_first"] = fv["bargain_pct"] > 12

    _b = hedonic.params
    fv["drop_next_paint"] = fv["fair_ask"] * (1 - np.exp(_b["painted"]))
    fv["drop_if_changed"] = np.where(fv["any_changed"] == 0,
                                     fv["fair_ask"] * (1 - np.exp(_b["any_changed"])), 0.0)
    _kmslope = np.select([_age <= 2, (_age >= 3) & (_age <= 4)],
                         [_b["km_young"], _b["km_mid"]], _b["km_old"])
    fv["drop_10k_km"] = fv["fair_ask"] * (1 - np.exp(_kmslope))
    _ycoef = {int(k.split("T.")[1].rstrip("]")): v for k, v in _b.items()
              if k.startswith("C(year)")}
    _ycoef[2019] = 0.0
    fv["drop_1yr"] = [fa * (1 - np.exp(_ycoef[y - 1] - _ycoef[y])) if (y - 1) in _ycoef else np.nan
                      for fa, y in zip(fv["fair_ask"], fv["year"])]

    _mot = fv["motivation_score"].fillna(0)
    _cuts = fv["num_price_cuts"].fillna(0)
    _dom = fv["days_on_market"].fillna(0)
    _discount = (0.04 + 0.0007 * _mot + 0.008 * _cuts.clip(0, 3)
                 + np.where(_dom > 120, 0.015, 0)).clip(0, 0.14)
    fv["settle"] = np.minimum(fv["price"] * (1 - _discount), fv["fair_ask"] * 0.96)
    fv["open"] = (fv["settle"] * 0.96 / 25000).round() * 25000
    fv["settle"] = (fv["settle"] / 25000).round() * 25000
    return fv


# Sheet-facing column names (display strings). All money columns in FULL TL.
VALUATION_EXPORT_COLUMNS = [
    "fair_ask_tl",
    "bargain_pct",
    "offer_open_tl",
    "offer_settle_tl",
    "drop_paint_tl",
    "drop_changed_tl",
    "drop_10k_km_tl",
    "drop_1yr_tl",
    "tramer_tl",
    "trim_suspect",
    "verify_first",
]


def _tl(value) -> str:
    return "" if pd.isna(value) else str(int(round(value)))


def valuation_by_id(db_path: str = "taycan.db") -> dict[str, dict[str, str]]:
    """Map sahibinden_id -> {VALUATION_EXPORT_COLUMNS as display strings}."""
    fv = compute_fair_values(db_path)
    result: dict[str, dict[str, str]] = {}
    for _, r in fv.iterrows():
        result[str(r["sahibinden_id"])] = {
            "fair_ask_tl": _tl(r["fair_ask"]),
            "bargain_pct": f"{r['bargain_pct']:.1f}",
            "offer_open_tl": _tl(r["open"]),
            "offer_settle_tl": _tl(r["settle"]),
            "drop_paint_tl": _tl(r["drop_next_paint"]),
            "drop_changed_tl": _tl(r["drop_if_changed"]),
            "drop_10k_km_tl": _tl(r["drop_10k_km"]),
            "drop_1yr_tl": _tl(r["drop_1yr"]),
            "tramer_tl": "" if pd.isna(r["tramer_tl"]) else str(int(r["tramer_tl"])),
            "trim_suspect": "Yes" if r["trim_suspect"] else "",
            "verify_first": "Yes" if r["verify_first"] else "",
        }
    return result
