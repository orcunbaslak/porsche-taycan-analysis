"""HTML parsing logic for sahibinden.com listings."""

import re
from bs4 import BeautifulSoup


def parse_price(text):
    """Parse price string like '5.150.000 TL' → (5150000, 'TL')."""
    if not text:
        return None, "TL"
    text = text.strip()
    currency = "TL"
    if "EUR" in text or "€" in text:
        currency = "EUR"
    elif "USD" in text or "$" in text:
        currency = "USD"
    elif "GBP" in text or "£" in text:
        currency = "GBP"
    # Remove everything except digits
    digits = re.sub(r"[^\d]", "", text)
    price = int(digits) if digits else None
    return price, currency


def parse_km(text):
    """Parse km string like '45.000 km' → 45000."""
    if not text:
        return None
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else None


def parse_year(text):
    """Parse year like '2021' → 2021."""
    if not text:
        return None
    match = re.search(r"\d{4}", str(text))
    return int(match.group()) if match else None


def parse_listing_rows(html):
    """Parse search results page HTML → list of listing dicts."""
    soup = BeautifulSoup(html, "lxml")
    listings = []

    rows = soup.select("tr.searchResultsItem[data-id]")
    for row in rows:
        # Skip native ads
        if "nativeAd" in row.get("class", []):
            continue

        data_id = row.get("data-id")
        if not data_id:
            continue

        # Title and URL
        title_el = row.select_one("a.classifiedTitle")
        title = title_el.get("title", "").strip() or (title_el.get_text(strip=True) if title_el else None)
        url = title_el["href"] if title_el and title_el.has_attr("href") else None
        if url and not url.startswith("http"):
            url = f"https://www.sahibinden.com{url}"

        # Extract model from title
        model = _extract_model(title) if title else None

        # Table cells: model-year, km, color, price, date, city/district
        cells = row.select("td.searchResultsAttributeValue")
        year = parse_year(cells[0].get_text(strip=True)) if len(cells) > 0 else None
        km = parse_km(cells[1].get_text(strip=True)) if len(cells) > 1 else None
        color = cells[2].get_text(strip=True) if len(cells) > 2 else None

        # Price
        price_el = row.select_one("td.searchResultsPriceValue span")
        price_text = price_el.get_text(strip=True) if price_el else None
        price, currency = parse_price(price_text)

        # Date
        date_el = row.select_one("td.searchResultsDateValue span")
        listing_date = date_el.get_text(strip=True) if date_el else None

        # Location
        loc_el = row.select_one("td.searchResultsLocationValue")
        location_city = None
        location_district = None
        if loc_el:
            loc_parts = loc_el.get_text("\n", strip=True).split("\n")
            location_city = loc_parts[0] if len(loc_parts) > 0 else None
            location_district = loc_parts[1] if len(loc_parts) > 1 else None

        listings.append(
            {
                "sahibinden_id": data_id,
                "url": url,
                "title": title,
                "model": model,
                "year": year,
                "km": km,
                "color": color,
                "price": price,
                "currency": currency,
                "listing_date": listing_date,
                "location_city": location_city,
                "location_district": location_district,
            }
        )

    return listings


def _extract_model(title):
    """Extract Taycan model variant from listing title."""
    if not title:
        return None
    title_lower = title.lower()
    # Order matters — check most specific first
    variants = [
        "Turbo GT",
        "Turbo S",
        "Turbo",
        "GTS",
        "4S Cross Turismo",
        "4 Cross Turismo",
        "4S",
        "Cross Turismo",
    ]
    for v in variants:
        if v.lower() in title_lower:
            return v
    # Base Taycan
    if "taycan" in title_lower:
        return "Taycan"
    return None


def has_next_page(html):
    """Check if there's a next page in search results."""
    soup = BeautifulSoup(html, "lxml")
    next_btn = soup.select_one("a.prevNextBut[title='Sonraki']")
    return next_btn is not None


def parse_detail_page(html):
    """Parse a listing detail page → dict of fields."""
    soup = BeautifulSoup(html, "lxml")
    data = {}

    # --- Basic info from classifiedInfoList ---
    info_map = {
        "İlan No": "sahibinden_id",
        "İlan Tarihi": "listing_date",
        "Marka": "brand",
        "Seri": "series",
        "Model": "model_detail",
        "Yıl": "year",
        "Yakıt Tipi": "fuel_type",
        "Vites": "transmission",
        "Araç Durumu": "vehicle_condition",
        "KM": "km",
        "Km": "km",
        "Kasa Tipi": "body_type",
        "Motor Gücü": "engine_power",
        "Çekiş": "traction",
        "Renk": "color",
        "Garanti": "warranty",
        "Ağır Hasar Kayıtlı": "heavy_damage_record",
        "Plaka / Uyruk": "plate_nationality",
        "Kimden": "seller_type",
        "Takas": "trade_in",
    }

    info_items = soup.select("ul.classifiedInfoList li")
    for item in info_items:
        label_el = item.select_one("strong")
        value_el = item.select_one("span")
        if not label_el or not value_el:
            continue
        label = label_el.get_text(strip=True)
        value = value_el.get_text(strip=True)
        field = info_map.get(label)
        if field:
            data[field] = value

    # Parse km as integer
    if "km" in data:
        data["km"] = parse_km(data["km"])

    # --- Price ---
    price_el = soup.select_one("div.classifiedInfo h3")
    if price_el:
        price, currency = parse_price(price_el.get_text(strip=True))
        data["price"] = price
        data["currency"] = currency

    # --- Description ---
    desc_el = soup.select_one("div#classifiedDescription")
    if desc_el:
        data["description"] = desc_el.get_text(strip=True)

    # --- Seller info ---
    seller_name_el = soup.select_one("div.classifiedOwnerInfo h5")
    if seller_name_el:
        data["seller_name"] = seller_name_el.get_text(strip=True)

    seller_agent_el = soup.select_one("div.classifiedOwnerInfo span.store-name")
    if seller_agent_el:
        data["seller_agent"] = seller_agent_el.get_text(strip=True)

    # --- Damage parts ---
    data["damage_parts"] = _parse_damage_parts(soup)
    damage_counts = {"original": 0, "painted": 0, "local-painted": 0, "changed": 0}
    for part in data["damage_parts"]:
        status = part["status"]
        if status in damage_counts:
            damage_counts[status] += 1
    data["damage_original_count"] = damage_counts["original"]
    data["damage_painted_count"] = damage_counts["painted"]
    data["damage_local_painted_count"] = damage_counts["local-painted"]
    data["damage_changed_count"] = damage_counts["changed"]

    # --- Features ---
    data["features"] = _parse_features(soup)

    return data


def _parse_damage_parts(soup):
    """Parse the damage diagram."""
    parts = []
    container = soup.select_one("div.car-parts")
    if not container:
        return parts

    for div in container.find_all("div", recursive=False):
        classes = div.get("class", [])
        if not classes:
            continue
        # First class is part name, subsequent classes are status
        part_name = classes[0]
        status = "original"
        for cls in classes[1:]:
            # Classes have -new suffix: original-new, painted-new, changed-new, local-painted-new
            normalized = cls.replace("-new", "")
            if normalized in ("painted", "changed", "local-painted", "original"):
                status = normalized
                break
        parts.append({"part_name": part_name, "status": status})

    return parts


def _parse_features(soup):
    """Parse feature/equipment lists from classifiedProperties section."""
    features = []

    props = soup.select_one("div#classifiedProperties")
    if not props:
        return features

    # Features are structured as: <h3>Category</h3> followed by <ul> with <li class="selected">
    # Skip the first h3 which is "Boyalı veya Değişen Parça" (damage section)
    current_category = None
    for el in props.children:
        if el.name == "h3":
            cat_text = el.get_text(strip=True)
            # Skip damage-related header
            if "Boyalı" in cat_text or "Değişen" in cat_text:
                current_category = None
            else:
                current_category = cat_text
        elif el.name == "ul" and current_category:
            for li in el.select("li"):
                feature_name = li.get_text(strip=True)
                if not feature_name:
                    continue
                is_selected = "selected" in li.get("class", [])
                features.append(
                    {
                        "category": current_category,
                        "feature_name": feature_name,
                        "is_present": 1 if is_selected else 0,
                    }
                )

    return features
