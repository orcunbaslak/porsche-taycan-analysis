import os
import tempfile

from db.database import init_db, get_connection


def _table_columns(conn, table):
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def test_init_db_creates_listing_signals_table():
    with tempfile.TemporaryDirectory() as d:
        db_path = os.path.join(d, "t.db")
        init_db(db_path)
        conn = get_connection(db_path)
        cols = _table_columns(conn, "listing_signals")
        conn.close()
    expected = {
        "sahibinden_id", "is_active", "runs_seen", "first_seen_date",
        "last_seen_date", "days_on_market", "bump_count", "bump_cadence_days",
        "first_price", "current_price", "max_price", "min_price",
        "total_price_drop", "price_drop_pct", "num_price_cuts",
        "last_price_cut_date", "motivation_score", "insufficient_history",
        "computed_at",
    }
    assert expected.issubset(cols)
