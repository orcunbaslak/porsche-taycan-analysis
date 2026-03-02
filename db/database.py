import sqlite3
import os
from datetime import datetime


DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "taycan.db")
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")


def get_connection(db_path=None):
    conn = sqlite3.connect(db_path or DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path=None):
    conn = get_connection(db_path)
    with open(SCHEMA_PATH) as f:
        conn.executescript(f.read())
    _run_migrations(conn)
    conn.close()


def _run_migrations(conn):
    """Apply schema migrations for columns added after initial release."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(listings)").fetchall()}
    if "is_active" not in columns:
        conn.execute("ALTER TABLE listings ADD COLUMN is_active INTEGER DEFAULT 1")
        conn.commit()


def create_scrape_run(conn):
    cur = conn.execute(
        "INSERT INTO scrape_runs (started_at, status) VALUES (?, 'running')",
        (datetime.now().isoformat(),),
    )
    conn.commit()
    return cur.lastrowid


def finish_scrape_run(conn, run_id, total_listings, status="completed"):
    conn.execute(
        "UPDATE scrape_runs SET finished_at=?, total_listings=?, status=? WHERE id=?",
        (datetime.now().isoformat(), total_listings, status, run_id),
    )
    conn.commit()


def upsert_listing_summary(conn, run_id, data):
    """Insert or update a listing from search results page."""
    conn.execute(
        """INSERT INTO listings (
            scrape_run_id, sahibinden_id, url, title, model, year, km, color,
            price, currency, listing_date, location_city, location_district
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(scrape_run_id, sahibinden_id) DO UPDATE SET
            url=excluded.url, title=excluded.title, model=excluded.model,
            year=excluded.year, km=excluded.km, color=excluded.color,
            price=excluded.price, currency=excluded.currency,
            listing_date=excluded.listing_date, location_city=excluded.location_city,
            location_district=excluded.location_district,
            is_active=1
        """,
        (
            run_id,
            data["sahibinden_id"],
            data.get("url"),
            data.get("title"),
            data.get("model"),
            data.get("year"),
            data.get("km"),
            data.get("color"),
            data.get("price"),
            data.get("currency", "TL"),
            data.get("listing_date"),
            data.get("location_city"),
            data.get("location_district"),
        ),
    )
    conn.commit()


def update_listing_details(conn, listing_id, data):
    """Update a listing with detail page data."""
    conn.execute(
        """UPDATE listings SET
            fuel_type=?, transmission=?, vehicle_condition=?, body_type=?,
            engine_power=?, traction=?, warranty=?, heavy_damage_record=?,
            plate_nationality=?, seller_type=?, trade_in=?, description=?,
            seller_name=?, seller_agent=?, seller_phone=?, seller_years=?,
            damage_original_count=?, damage_painted_count=?,
            damage_local_painted_count=?, damage_changed_count=?,
            detail_scraped=1
        WHERE id=?""",
        (
            data.get("fuel_type"),
            data.get("transmission"),
            data.get("vehicle_condition"),
            data.get("body_type"),
            data.get("engine_power"),
            data.get("traction"),
            data.get("warranty"),
            data.get("heavy_damage_record"),
            data.get("plate_nationality"),
            data.get("seller_type"),
            data.get("trade_in"),
            data.get("description"),
            data.get("seller_name"),
            data.get("seller_agent"),
            data.get("seller_phone"),
            data.get("seller_years"),
            data.get("damage_original_count"),
            data.get("damage_painted_count"),
            data.get("damage_local_painted_count"),
            data.get("damage_changed_count"),
            listing_id,
        ),
    )
    conn.commit()


def insert_damage_parts(conn, listing_id, parts):
    """Insert damage part records for a listing."""
    conn.executemany(
        "INSERT INTO damage_parts (listing_id, part_name, status) VALUES (?, ?, ?)",
        [(listing_id, p["part_name"], p["status"]) for p in parts],
    )
    conn.commit()


def insert_features(conn, listing_id, features):
    """Insert feature records for a listing."""
    conn.executemany(
        "INSERT INTO features (listing_id, category, feature_name, is_present) VALUES (?, ?, ?, ?)",
        [(listing_id, f["category"], f["feature_name"], f["is_present"]) for f in features],
    )
    conn.commit()


def get_unscraped_listings(conn, run_id):
    """Get listings that haven't had their detail pages scraped yet."""
    rows = conn.execute(
        "SELECT id, sahibinden_id, url FROM listings WHERE scrape_run_id=? AND detail_scraped=0",
        (run_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_latest_run_id(conn):
    """Get the most recent scrape run ID."""
    row = conn.execute(
        "SELECT id FROM scrape_runs ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return row["id"] if row else None


def get_run_stats(conn, run_id):
    """Get stats for a scrape run."""
    total = conn.execute(
        "SELECT COUNT(*) as cnt FROM listings WHERE scrape_run_id=?", (run_id,)
    ).fetchone()["cnt"]
    scraped = conn.execute(
        "SELECT COUNT(*) as cnt FROM listings WHERE scrape_run_id=? AND detail_scraped=1",
        (run_id,),
    ).fetchone()["cnt"]
    return {"total": total, "detail_scraped": scraped}


def get_all_known_ids(conn):
    """Get all sahibinden_ids that exist in any run."""
    rows = conn.execute("SELECT DISTINCT sahibinden_id FROM listings").fetchall()
    return {row["sahibinden_id"] for row in rows}


def get_previously_scraped_ids(conn, current_run_id):
    """Get sahibinden_ids that were detail-scraped in any previous run."""
    rows = conn.execute(
        """SELECT DISTINCT sahibinden_id FROM listings
           WHERE scrape_run_id < ? AND detail_scraped = 1""",
        (current_run_id,),
    ).fetchall()
    return {row["sahibinden_id"] for row in rows}


def copy_from_previous_run(conn, current_run_id, sahibinden_id):
    """
    Copy detail data, damage parts, and features from the most recent
    previous run into the current run's listing.
    Returns True if successful.
    """
    # Find the most recent previous listing with detail data
    prev = conn.execute(
        """SELECT * FROM listings
           WHERE sahibinden_id = ? AND scrape_run_id < ? AND detail_scraped = 1
           ORDER BY scrape_run_id DESC LIMIT 1""",
        (sahibinden_id, current_run_id),
    ).fetchone()

    if not prev:
        return False

    prev_listing_id = prev["id"]

    # Get current listing id and model
    cur = conn.execute(
        """SELECT id, model FROM listings
           WHERE scrape_run_id = ? AND sahibinden_id = ?""",
        (current_run_id, sahibinden_id),
    ).fetchone()

    if not cur:
        return False

    cur_listing_id = cur["id"]

    # Use previous model if current is None (list page couldn't extract it)
    model = prev["model"] if not cur["model"] and prev["model"] else cur["model"]

    # Copy detail fields (NOT price/km/year/title — those come from list page and may have changed)
    conn.execute(
        """UPDATE listings SET
            model = ?,
            fuel_type = ?, transmission = ?, vehicle_condition = ?, body_type = ?,
            engine_power = ?, traction = ?, warranty = ?, heavy_damage_record = ?,
            plate_nationality = ?, seller_type = ?, trade_in = ?, description = ?,
            seller_name = ?, seller_agent = ?, seller_phone = ?, seller_years = ?,
            damage_original_count = ?, damage_painted_count = ?,
            damage_local_painted_count = ?, damage_changed_count = ?,
            detail_scraped = 1
        WHERE id = ?""",
        (
            model,
            prev["fuel_type"], prev["transmission"], prev["vehicle_condition"], prev["body_type"],
            prev["engine_power"], prev["traction"], prev["warranty"], prev["heavy_damage_record"],
            prev["plate_nationality"], prev["seller_type"], prev["trade_in"], prev["description"],
            prev["seller_name"], prev["seller_agent"], prev["seller_phone"], prev["seller_years"],
            prev["damage_original_count"], prev["damage_painted_count"],
            prev["damage_local_painted_count"], prev["damage_changed_count"],
            cur_listing_id,
        ),
    )

    # Copy damage parts
    prev_parts = conn.execute(
        "SELECT part_name, status FROM damage_parts WHERE listing_id = ?",
        (prev_listing_id,),
    ).fetchall()

    if prev_parts:
        conn.executemany(
            "INSERT INTO damage_parts (listing_id, part_name, status) VALUES (?, ?, ?)",
            [(cur_listing_id, row["part_name"], row["status"]) for row in prev_parts],
        )

    # Copy features
    prev_features = conn.execute(
        "SELECT category, feature_name, is_present FROM features WHERE listing_id = ?",
        (prev_listing_id,),
    ).fetchall()

    if prev_features:
        conn.executemany(
            "INSERT INTO features (listing_id, category, feature_name, is_present) VALUES (?, ?, ?, ?)",
            [(cur_listing_id, row["category"], row["feature_name"], row["is_present"]) for row in prev_features],
        )

    conn.commit()
    return True


def update_listing_model(conn, listing_id, model):
    """Update the model column for a listing (used when detail page provides model_detail)."""
    conn.execute(
        "UPDATE listings SET model = ? WHERE id = ? AND (model IS NULL OR model = '')",
        (model, listing_id),
    )
    conn.commit()


def mark_inactive_listings(conn, run_id):
    """
    Mark listings from any run as inactive if their sahibinden_id
    is not present in the current run's search results.
    Returns the number of deactivated listings.
    """
    cur = conn.execute(
        """UPDATE listings SET is_active = 0
           WHERE is_active = 1
           AND sahibinden_id NOT IN (
               SELECT sahibinden_id FROM listings WHERE scrape_run_id = ?
           )""",
        (run_id,),
    )
    conn.commit()
    return cur.rowcount
