CREATE TABLE IF NOT EXISTS scrape_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    total_listings INTEGER,
    status TEXT DEFAULT 'running'  -- running, completed, failed
);

CREATE TABLE IF NOT EXISTS listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scrape_run_id INTEGER REFERENCES scrape_runs(id),
    sahibinden_id TEXT NOT NULL,
    url TEXT,
    title TEXT,
    model TEXT,
    year INTEGER,
    km INTEGER,
    color TEXT,
    price INTEGER,
    currency TEXT DEFAULT 'TL',
    listing_date TEXT,
    location_city TEXT,
    location_district TEXT,
    -- Detail page fields
    fuel_type TEXT,
    transmission TEXT,
    vehicle_condition TEXT,
    body_type TEXT,
    engine_power TEXT,
    traction TEXT,
    warranty TEXT,
    heavy_damage_record TEXT,
    plate_nationality TEXT,
    seller_type TEXT,
    trade_in TEXT,
    description TEXT,
    -- Seller info
    seller_name TEXT,
    seller_agent TEXT,
    seller_phone TEXT,
    seller_years INTEGER,
    -- Damage summary
    damage_original_count INTEGER,
    damage_painted_count INTEGER,
    damage_local_painted_count INTEGER,
    damage_changed_count INTEGER,
    -- Metadata
    detail_scraped INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(scrape_run_id, sahibinden_id)
);

CREATE TABLE IF NOT EXISTS damage_parts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id INTEGER REFERENCES listings(id),
    part_name TEXT,
    status TEXT
);

CREATE TABLE IF NOT EXISTS features (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id INTEGER REFERENCES listings(id),
    category TEXT,
    feature_name TEXT,
    is_present INTEGER
);
