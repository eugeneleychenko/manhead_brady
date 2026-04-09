from __future__ import annotations

import csv
import datetime as dt
import os
import re
from io import BytesIO, StringIO
from pathlib import Path
from typing import Any

import pandas as pd
import requests


CANADIAN_PROVINCES = {
    "AB",
    "BC",
    "MB",
    "NB",
    "NL",
    "NS",
    "NT",
    "NU",
    "ON",
    "PE",
    "QC",
    "SK",
    "YT",
}

TOUR_COLUMNS = [
    "Date",
    "City",
    "State",
    "Zip",
    "Venue",
    "Venue Actual %",
    "Capacity",
    "Attend",
    "Currency",
    "Exch. Rate",
    "Per Head",
    "Gross",
    "Tax",
    "Payment Fees",
    "Venue Fee",
    "Venue Adjust.",
    "Vend Fee",
    "Ext Exp",
    "Bootleg Exp",
    "Selling Exp",
    "Net Receipts",
]

OUTPUT_COLUMNS = [
    "artistName",
    "Genre",
    "showDate",
    "HolidayStatus",
    "venue name",
    "venue city",
    "venue state",
    "venue country",
    "venue postalCode",
    "merch category",
    "productType",
    "product size",
    "attendance",
    "product price",
    "temperature_daily_mean",
    "rain",
    "snowfall",
    "spotifyMonthlyListeners",
    "Instagram",
    "venue capacity",
    "spotifyMissing",
]

US_HOLIDAYS = {
    dt.date(2025, 1, 1),
    dt.date(2025, 1, 20),
    dt.date(2025, 2, 17),
    dt.date(2025, 5, 26),
    dt.date(2025, 6, 19),
    dt.date(2025, 7, 4),
    dt.date(2025, 9, 1),
    dt.date(2025, 10, 13),
    dt.date(2025, 11, 11),
    dt.date(2025, 11, 27),
    dt.date(2025, 12, 25),
    dt.date(2026, 1, 1),
    dt.date(2026, 1, 19),
    dt.date(2026, 2, 16),
    dt.date(2026, 5, 25),
    dt.date(2026, 6, 19),
    dt.date(2026, 7, 4),
    dt.date(2026, 9, 7),
    dt.date(2026, 10, 12),
    dt.date(2026, 11, 11),
    dt.date(2026, 11, 26),
    dt.date(2026, 12, 25),
}


class ConversionInputError(ValueError):
    """Raised when converter inputs are missing required information."""


def _safe_decode_csv(file_bytes: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return file_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ConversionInputError("Could not decode uploaded CSV file.")


def _clean_num(value: Any) -> float:
    if value is None:
        return 0.0
    value_str = str(value).replace("$", "").replace(",", "").strip()
    if not value_str:
        return 0.0
    try:
        return float(value_str)
    except ValueError:
        return 0.0


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).lower()


def _holiday_status(show_date: dt.date) -> int:
    if show_date.weekday() >= 5:
        return 1
    return 1 if show_date in US_HOLIDAYS else 0


def _venue_country(state_code: str) -> str:
    return "Canada" if state_code.strip().upper() in CANADIAN_PROVINCES else "United States"


def _parse_sales_report(file_bytes: bytes) -> pd.DataFrame:
    text = _safe_decode_csv(file_bytes)
    rows: list[dict[str, Any]] = []
    reader = csv.reader(StringIO(text))

    skip_prefixes = (
        "APPAREL",
        "OTHER",
        "MUSIC",
        "TOTAL",
        "GRAND",
        "SUBTOTAL",
        "SKU,",
        "UPC,",
    )

    for parts in reader:
        if not parts:
            continue
        raw_line = ",".join(parts).strip()
        if not raw_line:
            continue
        if raw_line.startswith(skip_prefixes):
            continue
        if len(parts) < 9:
            continue

        item_name = (parts[1] or "").strip()
        if not item_name:
            continue

        product_type = (parts[2] or "").strip() or "Unknown"
        product_size = (parts[4] or "").strip() or "ONE SIZE"
        sold_str = (parts[5] or "").strip()
        sold = int(sold_str) if sold_str.lstrip("-").isdigit() else 0
        price = _clean_num(parts[8] if len(parts) > 8 else "")
        if price <= 0:
            continue

        rows.append(
            {
                "Item Name": item_name,
                "productType": product_type,
                "product size": product_size,
                "actual_sold": sold,
                "product price": price,
            }
        )

    if not rows:
        raise ConversionInputError(
            "No valid merch rows were found in the sales report. "
            "Check that the report includes item rows with positive prices."
        )
    return pd.DataFrame(rows)


def _parse_tour_summary(file_bytes: bytes) -> pd.DataFrame:
    csv_text = _safe_decode_csv(file_bytes)
    csv_bytes = csv_text.encode("utf-8")

    # Expected atVenu export format (4 metadata lines first).
    tour_df = pd.read_csv(
        StringIO(csv_text),
        skiprows=4,
        header=None,
        names=TOUR_COLUMNS,
    )
    valid_dates = tour_df["Date"].astype(str).str.contains(r"/", na=False)

    # Fallback to regular header-based CSV if needed.
    if int(valid_dates.sum()) == 0:
        fallback_df = pd.read_csv(StringIO(csv_text))
        required = {"Date", "City", "State", "Zip", "Venue", "Capacity", "Attend"}
        if not required.issubset(set(fallback_df.columns)):
            raise ConversionInputError(
                "Tour summary CSV does not match expected format. "
                "Required columns: Date, City, State, Zip, Venue, Capacity, Attend."
            )
        tour_df = fallback_df.copy()
        valid_dates = tour_df["Date"].astype(str).str.contains(r"/", na=False)

    tour_df = tour_df[valid_dates].copy()
    if tour_df.empty:
        raise ConversionInputError("Tour summary CSV has no rows with valid show dates.")

    tour_df["show_date_parsed"] = pd.to_datetime(tour_df["Date"], errors="coerce")
    tour_df = tour_df[tour_df["show_date_parsed"].notna()].copy()
    if tour_df.empty:
        raise ConversionInputError("Could not parse any show dates from the tour summary CSV.")

    tour_df["showDate"] = tour_df["show_date_parsed"].dt.strftime("%Y-%m-%d")
    tour_df["attendance"] = tour_df["Attend"].apply(_clean_num).astype(int)
    tour_df["venue capacity"] = tour_df["Capacity"].apply(_clean_num).astype(int)
    tour_df["venue city"] = tour_df["City"].astype(str).str.strip()
    tour_df["venue state"] = tour_df["State"].astype(str).str.strip()
    tour_df["venue name"] = tour_df["Venue"].astype(str).str.strip()
    tour_df["venue postalCode"] = (
        tour_df["Zip"]
        .astype(str)
        .str.replace(r"\.0$", "", regex=True)
        .str.strip()
    )
    tour_df["venue country"] = tour_df["venue state"].apply(_venue_country)
    return tour_df


def _detect_show_date_from_filename(file_name: str) -> str | None:
    match = re.search(r"(\d{1,2})-(\d{1,2})-(\d{4})", file_name)
    if not match:
        return None
    month, day, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
    try:
        return dt.date(year, month, day).strftime("%Y-%m-%d")
    except ValueError:
        return None


def _find_show_row(
    tour_df: pd.DataFrame,
    sales_file_name: str,
    override_show_date: str | None,
) -> pd.Series:
    show_date = (override_show_date or "").strip() or _detect_show_date_from_filename(sales_file_name)
    if show_date:
        matches = tour_df[tour_df["showDate"] == show_date]
        if not matches.empty:
            return matches.iloc[0]
        raise ConversionInputError(
            f"Show date '{show_date}' not found in uploaded tour summary."
        )

    if int(tour_df.shape[0]) == 1:
        return tour_df.iloc[0]

    suggested = ", ".join(sorted(set(tour_df["showDate"].head(8).tolist())))
    raise ConversionInputError(
        "Could not infer show date from sales report file name. "
        "Provide a show date override in YYYY-MM-DD format. "
        f"Sample dates found: {suggested}"
    )


def _optional_csv(path: str | None) -> pd.DataFrame:
    if not path:
        return pd.DataFrame()
    file_path = Path(path)
    if not file_path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(file_path)
    except Exception:
        return pd.DataFrame()


def _lookup_band_value(
    band_name: str,
    df: pd.DataFrame,
    candidate_cols: list[str],
    value_col: str,
) -> Any:
    if df.empty or value_col not in df.columns:
        return None

    norm_band = _normalize_text(band_name)
    for candidate_col in candidate_cols:
        if candidate_col not in df.columns:
            continue
        norm_series = df[candidate_col].fillna("").astype(str).map(_normalize_text)
        matches = df[norm_series == norm_band]
        if not matches.empty:
            return matches.iloc[0].get(value_col)
    return None


def _genre_for_band(
    band_name: str,
    artist_meta_df: pd.DataFrame,
    band_genre_df: pd.DataFrame,
) -> str:
    artist_meta_genre = _lookup_band_value(
        band_name,
        artist_meta_df,
        ["artistName"],
        "Genre",
    )
    if artist_meta_genre:
        return str(artist_meta_genre)

    mapped_genre = _lookup_band_value(
        band_name,
        band_genre_df,
        ["Band Name", "MH band"],
        "Genre",
    )
    if mapped_genre:
        return str(mapped_genre)
    return "Other"


def _instagram_for_band(band_name: str, artist_meta_df: pd.DataFrame) -> int:
    value = _lookup_band_value(
        band_name,
        artist_meta_df,
        ["artistName"],
        "Instagram_followers",
    )
    return int(_clean_num(value))


def _spotify_for_band(band_name: str, spotify_df: pd.DataFrame) -> tuple[int, int]:
    value = _lookup_band_value(
        band_name,
        spotify_df,
        ["artistName"],
        "spotifyMonthlyListeners",
    )
    if value is None or _clean_num(value) <= 0:
        return 0, 1
    return int(_clean_num(value)), 0


def _geocode_city(city: str, state: str) -> tuple[float | None, float | None]:
    try:
        resp = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={
                "name": f"{city} {state}",
                "count": 1,
                "language": "en",
                "format": "json",
            },
            timeout=10,
        )
        payload = resp.json()
        results = payload.get("results", [])
        if results:
            return float(results[0]["latitude"]), float(results[0]["longitude"])
    except Exception:
        pass
    return None, None


def _fetch_weather(lat: float | None, lon: float | None, show_date: str) -> dict[str, float]:
    defaults = {"temperature_daily_mean": 15.0, "rain": 0.0, "snowfall": 0.0}
    if lat is None or lon is None:
        return defaults
    try:
        resp = requests.get(
            "https://archive-api.open-meteo.com/v1/archive",
            params={
                "latitude": lat,
                "longitude": lon,
                "start_date": show_date,
                "end_date": show_date,
                "daily": "temperature_2m_mean,rain_sum,snowfall_sum",
                "timezone": "auto",
            },
            timeout=15,
        )
        payload = resp.json().get("daily", {})
        return {
            "temperature_daily_mean": float((payload.get("temperature_2m_mean") or [defaults["temperature_daily_mean"]])[0] or defaults["temperature_daily_mean"]),
            "rain": float((payload.get("rain_sum") or [defaults["rain"]])[0] or defaults["rain"]),
            "snowfall": float((payload.get("snowfall_sum") or [defaults["snowfall"]])[0] or defaults["snowfall"]),
        }
    except Exception:
        return defaults


def convert_sales_reports_to_prediction_input(
    *,
    sales_report_bytes: bytes,
    sales_report_name: str,
    tour_summary_bytes: bytes,
    band_name: str,
    artist_meta_path: str | None = None,
    spotify_path: str | None = None,
    band_genre_map_path: str | None = None,
    show_date_override: str | None = None,
    fetch_weather: bool = False,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    band_name = band_name.strip()
    if not band_name:
        raise ConversionInputError("Band name is required.")

    sales_df = _parse_sales_report(sales_report_bytes)
    tour_df = _parse_tour_summary(tour_summary_bytes)
    show = _find_show_row(tour_df, sales_report_name, show_date_override)

    show_date = str(show["showDate"])
    show_date_obj = dt.datetime.strptime(show_date, "%Y-%m-%d").date()

    artist_meta_df = _optional_csv(artist_meta_path)
    spotify_df = _optional_csv(spotify_path)
    band_genre_df = _optional_csv(band_genre_map_path)

    genre = _genre_for_band(band_name, artist_meta_df, band_genre_df)
    instagram = _instagram_for_band(band_name, artist_meta_df)
    spotify_listeners, spotify_missing = _spotify_for_band(band_name, spotify_df)
    holiday_status = _holiday_status(show_date_obj)

    venue_city = str(show["venue city"])
    venue_state = str(show["venue state"])
    weather = {"temperature_daily_mean": 15.0, "rain": 0.0, "snowfall": 0.0}
    if fetch_weather:
        lat, lon = _geocode_city(venue_city, venue_state)
        weather = _fetch_weather(lat, lon, show_date)

    output_rows: list[dict[str, Any]] = []
    for _, item in sales_df.iterrows():
        output_rows.append(
            {
                "artistName": band_name,
                "Genre": genre,
                "showDate": show_date,
                "HolidayStatus": holiday_status,
                "venue name": str(show["venue name"]),
                "venue city": venue_city,
                "venue state": venue_state,
                "venue country": str(show["venue country"]),
                "venue postalCode": str(show["venue postalCode"]),
                "merch category": str(item["Item Name"]),
                "productType": str(item["productType"]),
                "product size": str(item["product size"]),
                "attendance": int(show["attendance"]),
                "product price": float(item["product price"]),
                "temperature_daily_mean": float(weather["temperature_daily_mean"]),
                "rain": float(weather["rain"]),
                "snowfall": float(weather["snowfall"]),
                "spotifyMonthlyListeners": int(spotify_listeners),
                "Instagram": int(instagram),
                "venue capacity": int(show["venue capacity"]),
                "spotifyMissing": int(spotify_missing),
            }
        )

    out_df = pd.DataFrame(output_rows)
    out_df = out_df[OUTPUT_COLUMNS]

    metadata = {
        "band_name": band_name,
        "show_date": show_date,
        "venue_name": str(show["venue name"]),
        "rows_out": int(out_df.shape[0]),
        "fetch_weather": bool(fetch_weather),
    }
    return out_df, metadata


# ---------------------------------------------------------------------------
# Step 3: Inventory / Forecast file converter
# ---------------------------------------------------------------------------

TOUR_DATA_URL = "https://atvenu-forecast.votintsev.com/tour_data.csv"
TOUR_DATA_COLUMNS = [
    "Band", "Show Date", "City", "ST", "Venue", "Nights", "Type",
    "Capacity", "Attn", "PPH", "Col10", "Merch", "Col12", "Expenses",
    "Col14", "Net", "Col16",
]

ATVENU_API_ENDPOINT = "https://api.atvenu.com"
ATVENU_API_TOKEN = os.environ.get("ATVENU_API_TOKEN", "live_yvYLBo32dRE9z_yCdhwU")
ATTENDANCE_RATIO = 0.80

US_CITY_STATE = {
    "Lancaster": "PA", "Englewood": "NJ", "Flint": "MI", "Prior Lake": "MN",
    "Kansas City": "MO", "Saint Louis": "MO", "St. Louis": "MO",
    "West Palm Beach": "FL", "Miami": "FL", "Myrtle Beach": "SC",
    "Las Vegas": "NV", "North Tonawanda": "NY", "Greensburg": "PA",
    "San Jose": "CA", "San Francisco": "CA", "Los Angeles": "CA",
    "San Diego": "CA", "New York": "NY", "Brooklyn": "NY", "Chicago": "IL",
    "Houston": "TX", "Dallas": "TX", "Austin": "TX", "Denver": "CO",
    "Seattle": "WA", "Portland": "OR", "Phoenix": "AZ", "Atlanta": "GA",
    "Nashville": "TN", "Boston": "MA", "Philadelphia": "PA", "Pittsburgh": "PA",
    "Detroit": "MI", "Minneapolis": "MN", "St. Paul": "MN", "Milwaukee": "WI",
    "Cleveland": "OH", "Columbus": "OH", "Cincinnati": "OH", "Indianapolis": "IN",
    "Charlotte": "NC", "Raleigh": "NC", "Tampa": "FL", "Orlando": "FL",
    "Jacksonville": "FL", "Baltimore": "MD", "Washington": "DC", "Richmond": "VA",
    "Norfolk": "VA", "New Orleans": "LA", "Memphis": "TN", "Louisville": "KY",
    "Oklahoma City": "OK", "Tulsa": "OK", "Salt Lake City": "UT", "Boise": "ID",
    "Omaha": "NE", "Des Moines": "IA", "Buffalo": "NY", "Rochester": "NY",
    "Syracuse": "NY", "Albany": "NY", "Hartford": "CT", "Providence": "RI",
    "Birmingham": "AL", "Knoxville": "TN", "Chattanooga": "TN", "Reno": "NV",
    "Albuquerque": "NM", "El Paso": "TX", "Tucson": "AZ", "Honolulu": "HI",
    "Anchorage": "AK", "Wichita": "KS", "Little Rock": "AR", "Sacramento": "CA",
    "Sarasota": "FL", "Fort Myers": "FL", "Fort Lauderdale": "FL",
    "Pompano Beach": "FL", "Boca Raton": "FL", "Temecula": "CA", "Chandler": "AZ",
    "Red Bank": "NJ", "Oxon Hill": "MD", "Durham": "NC", "Lincoln City": "OR",
    "Hershey": "PA", "Bensalem": "PA", "Greenville": "SC", "Morrison": "CO",
    "Napa": "CA", "Valley Center": "CA", "Rancho Mirage": "CA",
    "Toronto": "ON", "Montreal": "QC", "Vancouver": "BC", "Calgary": "AB",
    "Edmonton": "AB", "Ottawa": "ON", "Winnipeg": "MB", "Halifax": "NS",
}

INCLUDED_BANDS = [
    "2 Chainz (MH)",
    "A Bowie Celebration (MH)",
    "A.C.E.",
    "ASIA (MH)",
    "Aaron Lewis",
    "Air Supply",
    "Alan Parsons Live",
    "Alanis Morissette (MH)",
    "Alanis Morissette Wellness Brand",
    "Alec Benjamin (MH)",
    "Alice in Chains (MH)",
    "All That Remains (MH)",
    "Andrea Gibson (MH)",
    "Andrew McMahon in the Wilderness (MH)",
    "Apocalyptica",
    "Atarashii Gakko! (MH)",
    "Austin Snell (MH)",
    "B 52's",
    "BOYS LIKE GIRLS (MH)",
    "Bert Kreischer (MH)",
    "Billy Idol (Manhead)",
    "Billy Porter (MH)",
    "Black Pistol Fire",
    "Black Veil Brides (MH)",
    "Blindside (MH)",
    "Brantley Gilbert (MH)",
    "Bunnie (MH)",
    "Butch Walker",
    "COIN",
    "Celebrating David Bowie",
    "Celtic Tenor",
    "Celtic Thunder (MH)",
    "Celtic Woman",
    "Christopher Cross (MH)",
    "Chvrches (MH)",
    "Circa Waves (MH)",
    "Clandestine",
    "Clare Bowen (MH)",
    "Clay Walker (MH)",
    "Coheed and Cambria (MH)",
    "Counting Crows (MH)",
    "Country Music Association (MH)",
    "Courtney Love",
    "Cyndi Lauper (MH)",
    "DIDO",
    "DIR EN GREY (MH)",
    "Dashboard Confessional (MH)",
    "Dean Lewis (MH)",
    "Death Stranding",
    "Deftones (MH)",
    "Dolly Parton (MH)",
    "Eagles Of Death Metal (Manhead)",
    "EarthGang",
    "Emerald Cup Festival (MH)",
    "Emilia (MH)",
    "Empire of the Sun (MH)",
    "Fall Out Boy",
    "Fall Out Boy (Pop Up Shops)",
    "Fear Factory",
    "Games We Play (MH)",
    "Gang of Youths (MH)",
    "Garbage (MH)",
    "Gavin DeGraw",
    "Goodbye June (MH)",
    "Goodie Mob",
    "Grace Bowers",
    "Halestorm (MH)",
    "INHALER (MH)",
    "Ian Munsick (MH)",
    "India Arie (Manhead)",
    "J.I.D.",
    "JXDN",
    "Jack's Mannequin (MH)",
    "Jackson Browne (MH)",
    "Jelly Roll (MH)",
    "Jerry Cantrell (MH)",
    "Jewel (Manhead)",
    "Joan Jett (MH)",
    "Joe Perry Project",
    "Joey Valence & Brae (MH)",
    "John Lodge",
    "Joji (MH)",
    "Jukebox The Ghost (Manhead)",
    "Justin Hayward (Manhead)",
    "Kameron Marlowe (MH)",
    "Kevin Griffin",
    "Key Glock (MH)",
    "Kiesza",
    "L.I.F.T.",
    "LIMP BIZKIT (MH)",
    "Labrinth (MH)",
    "Lainey Wilson (MH)",
    "Lanie Gardner (MH)",
    "Lauren Jauregui (MH)",
    "Lennon Stella (MH)",
    "Liz Phair (MH)",
    "Lukas Nelson (MH)",
    "Lykke Li (MH)",
    "Lynchburg Music Fest (Artist)",
    "Machine Gun Kelly (MH)",
    "Macklemore (MH)",
    "Maddie Zahm (MH)",
    "Madness (MH)",
    "Manchester Orchestra (MH)",
    "Manhead",
    "Manhead Merchandise",
    "Manhead Training Account",
    "Marc Rebillet (MH)",
    "Marina (MH)",
    "Marvelous 3",
    "Masiwei (MH)",
    "Matt And Kim",
    "Matt Nathanson",
    "Max",
    "Maxwell (Manhead)",
    "Megadeth",
    "Michael Franti & Spearhead (Manhead)",
    "Midnight Oil (MH)",
    "Midtown",
    "Miyavi",
    "Moody Blues (MH)",
    "Morrissey",
    "Morrissey (Pop Up Shops)",
    "Motion City Soundtrack - MH",
    "Mt Eddy",
    "Music City Skate Jam",
    "NIKI",
    "Nessa Barrett (MH)",
    "New Edition",
    "Noel Gallagher HFB (MH)",
    "Old Dominion (MH)",
    "Oliver Anthony (MH)",
    "Panic! At the Disco",
    "Paul Simon (MH)",
    "Persona Live",
    "Peter Bjorn and John",
    "Pilgrimage Festival",
    "RATT (MH)",
    "Rich Brian MH",
    "Rivers Cuomo",
    "Royal Blood (MH)",
    "Ryan Bingham (MH)",
    "SIA",
    "Scissor Happy",
    "Seal (MH)",
    "Sebastian Maniscalco (MH)",
    "Sexyy Red",
    "Shame",
    "Sirius XM",
    "Skegss (MH)",
    "Smoky Mountain Christmas Carol",
    "SoMo",
    "Sofia Isella",
    "Sombr (MH)",
    "Something Corporate (MH)",
    "Sonic Symphony",
    "Soul Asylum (MH)",
    "Stardew Valley",
    "Taylor Tomlinson (MH)",
    "Temples (MH)",
    "The Band Loula",
    "The Buggles (MH)",
    "The Chats (MH)",
    "The Damned Things",
    "The Gaslight Anthem (MH)",
    "The Interrupters (MH)",
    "The Marley Brothers (MH)",
    "The Naked and Famous",
    "The Naked and Famous (MH)",
    "The Pretenders",
    "The Pussycat Dolls",
    "The Romantics",
    "The Sisters Of Mercy (MH)",
    "The Smashing Pumpkins (MH)",
    "The Temper Trap (MH)",
    "The Zombies (MH)",
    "Toto (MH)",
    "Train",
    "Trevor Noah (MH)",
    "Two Door Cinema Club (MH)",
    "Tyler Childers (MH)",
    "Tyler Hubbard (MH)",
    "Umphreys McGee",
    "W.A.S.P",
    "WILLIE'S RESERVE (MH)",
    "War of Ages (MH)",
    "Warren Hue",
    "Warren Hue - Ship to Home",
    "Waylon Wyatt",
    "We The Kings",
    "We Three (MH)",
    "Weezer (MH)",
    "Weird Al Yankovic (MH)",
    "White Album Tour",
    "Will Smith (MH)",
    "Willow (MH)",
    "X Ambassadors (MH)",
    "YES (MH)",
    "Yellowcard (MH)",
    "Zac Brown Band (MH)",
    "Zach Top (MH)",
    "Zedd (MH)",
]


def _fetch_tour_data() -> pd.DataFrame:
    """Download tour_data.csv from external URL."""
    try:
        resp = requests.get(TOUR_DATA_URL, timeout=15)
        resp.raise_for_status()
        tour_df = pd.read_csv(
            StringIO(resp.text),
            header=None,
            names=TOUR_DATA_COLUMNS,
            engine="python",
            on_bad_lines="warn",
        )
        if (
            isinstance(tour_df["Band"].iloc[0], str)
            and tour_df["Band"].iloc[0] == "Band"
        ):
            tour_df = tour_df.iloc[1:].reset_index(drop=True)
        for col in ("Capacity", "Attn"):
            tour_df[col] = pd.to_numeric(tour_df[col], errors="coerce")
        return tour_df
    except Exception:
        return pd.DataFrame(columns=TOUR_DATA_COLUMNS)


def _build_venue_lookup_from_tour_data(
    tour_df: pd.DataFrame,
    band_name: str,
) -> dict[str, dict[str, Any]]:
    """Build a city->venue-details dict from the stored tour_data."""
    band_with_mh = f"{band_name} (MH)"
    band_shows = tour_df[
        (tour_df["Band"] == band_name) | (tour_df["Band"] == band_with_mh)
    ]
    lookup: dict[str, dict[str, Any]] = {}
    for _, row in band_shows.iterrows():
        city = str(row.get("City", "")).strip()
        if not city:
            continue
        attendance = int(_clean_num(row.get("Attn", 0)))
        capacity = int(_clean_num(row.get("Capacity", 0)))
        lookup[city.lower()] = {
            "venue": str(row.get("Venue", "") or ""),
            "state": str(row.get("ST", "") or ""),
            "attendance": attendance,
            "capacity": capacity if capacity > 0 else attendance,
            "zip": "",
        }
        if "," in city:
            short = city.split(",")[0].strip()
            lookup[short.lower()] = lookup[city.lower()]
    return lookup


_SHOWS_QUERY = """
query getFutureShows(
  $firstForAccounts: Int!, $afterForAccounts: String,
  $firstForTours: Int!, $firstForShows: Int!,
  $dateRange: DateRange!
) {
  organization {
    accounts(first: $firstForAccounts, after: $afterForAccounts) {
      pageInfo { endCursor hasNextPage }
      nodes {
        name
        tours(first: $firstForTours) {
          nodes {
            shows(first: $firstForShows, showsOverlap: $dateRange) {
              nodes {
                showDate capacity attendance
                location { name city country }
              }
            }
          }
        }
      }
    }
  }
}
"""


def _fetch_atvenu_api_venues(band_name: str) -> dict[str, dict[str, Any]]:
    """Fetch venue data from atVenu GraphQL API for a band. Returns city->details.

    Uses raw requests.post() instead of gql to avoid extra dependency on
    Streamlit Cloud where gql is not installed.
    """
    from datetime import datetime, timedelta

    start = datetime.now().strftime("%Y-%m-%d")
    end = (datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d")
    lookup: dict[str, dict[str, Any]] = {}
    cursor = None
    headers = {
        "Content-Type": "application/json",
        "x-api-key": ATVENU_API_TOKEN,
    }

    try:
        while True:
            payload = {
                "query": _SHOWS_QUERY,
                "variables": {
                    "firstForAccounts": 20,
                    "afterForAccounts": cursor,
                    "firstForTours": 10,
                    "firstForShows": 50,
                    "dateRange": {"start": start, "end": end},
                },
            }
            resp = requests.post(
                ATVENU_API_ENDPOINT, json=payload, headers=headers, timeout=30
            )
            resp.raise_for_status()
            body = resp.json()
            if "errors" in body:
                break
            data = body.get("data", {})
            accounts_conn = data.get("organization", {}).get("accounts", {})

            for account in accounts_conn.get("nodes", []):
                if account["name"].lower().strip() != band_name.lower().strip():
                    continue
                for tour in account.get("tours", {}).get("nodes", []):
                    for show in tour.get("shows", {}).get("nodes", []):
                        loc = show.get("location") or {}
                        city_raw = loc.get("city") or ""
                        city, api_state = ("", "")
                        if "," in city_raw:
                            city, api_state = city_raw.split(",", 1)
                            city, api_state = city.strip(), api_state.strip()
                        else:
                            city = city_raw.strip()

                        if not city:
                            continue

                        state = api_state
                        if not state or state == "null":
                            state = US_CITY_STATE.get(city, "")

                        cap = int(show.get("capacity") or 0)
                        attn = show.get("attendance")
                        est = int(attn) if attn else int(cap * ATTENDANCE_RATIO)

                        lookup[city.lower()] = {
                            "venue": loc.get("name", ""),
                            "state": state,
                            "attendance": est,
                            "capacity": cap,
                            "zip": "",
                        }

            pi = accounts_conn.get("pageInfo", {})
            if not pi.get("hasNextPage"):
                break
            cursor = pi.get("endCursor")

        return lookup
    except Exception:
        return {}


def _match_city(
    city: str,
    lookup: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    key = city.lower().strip()
    if key in lookup:
        return lookup[key]
    for lk_city, details in lookup.items():
        if key in lk_city or lk_city in key:
            return details
    return None


def _parse_inventory_file(
    file_bytes: bytes,
    file_name: str,
) -> tuple[pd.DataFrame, list[dict[str, str]]]:
    """
    Parse a raw atvenu inventory/forecast file (CSV or Excel).
    Returns (products_df, shows_list) where shows_list has city/date entries.
    """
    ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else "csv"
    if ext in ("xlsx", "xls"):
        inventory_df = pd.read_excel(BytesIO(file_bytes))
    else:
        text = _safe_decode_csv(file_bytes)
        inventory_df = pd.read_csv(StringIO(text))

    show_pattern = re.compile(
        r"^(.+?)\s*-\s*(\d{1,2}/\d{1,2}/\d{2,4})\s*(?:\(.*\))?$"
    )
    shows: list[dict[str, str]] = []
    for col in inventory_df.columns:
        m = show_pattern.match(col.strip())
        if not m:
            continue
        city = m.group(1).strip()
        date_part = m.group(2).strip()
        try:
            date_obj = dt.datetime.strptime(date_part, "%m/%d/%y")
        except ValueError:
            try:
                date_obj = dt.datetime.strptime(date_part, "%m/%d/%Y")
            except ValueError:
                continue
        shows.append({
            "city": city,
            "date": date_obj.strftime("%Y-%m-%d"),
        })

    if not shows:
        raise ConversionInputError(
            "No show columns found. Expected column headers like "
            "'City - MM/DD/YY ($X.XX/head)'."
        )

    products: list[dict[str, Any]] = []
    for _, row in inventory_df.iterrows():
        item_name = row.get("Item Name")
        if pd.isna(item_name) or not str(item_name).strip():
            continue
        products.append({
            "Item Name": str(item_name).strip(),
            "productType": str(row.get("Product Type", "Unknown")).strip(),
            "product size": str(row.get("Size", "ONE SIZE")).strip() or "ONE SIZE",
            "SKU": str(row.get("SKU", "")).strip(),
        })

    if not products:
        raise ConversionInputError("No product rows found in inventory file.")

    return pd.DataFrame(products), shows


def convert_inventory_to_prediction_input(
    *,
    file_bytes: bytes,
    file_name: str,
    band_name: str,
    price_df: pd.DataFrame | None = None,
    artist_meta_path: str | None = None,
    spotify_path: str | None = None,
    band_genre_map_path: str | None = None,
    fetch_weather: bool = False,
    progress_callback: Any = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """
    Convert a raw atvenu inventory/forecast file into the 21-column
    prediction input format.
    """
    band_name = band_name.strip()
    if not band_name:
        raise ConversionInputError("Band name is required.")

    products_df, shows = _parse_inventory_file(file_bytes, file_name)

    if progress_callback:
        progress_callback(f"Parsed {len(products_df)} products and {len(shows)} shows")

    # Price lookup by SKU
    if price_df is not None and not price_df.empty:
        band_with_mh = f"{band_name} (MH)"
        band_prices = price_df[
            (price_df["Band Name"] == band_name)
            | (price_df["Band Name"] == band_with_mh)
        ]
        sku_to_price = {}
        for _, pr in band_prices.iterrows():
            sku_to_price[str(pr["SKU"]).strip()] = float(pr["Price"])
    else:
        sku_to_price = {}

    # Venue lookup: stored tour data first, then atVenu API fallback
    if progress_callback:
        progress_callback("Fetching venue data from tour_data.csv...")
    tour_df = _fetch_tour_data()
    venue_lookup = _build_venue_lookup_from_tour_data(tour_df, band_name)

    cities_missing = [
        s["city"] for s in shows if _match_city(s["city"], venue_lookup) is None
    ]
    api_lookup: dict[str, dict[str, Any]] = {}
    if cities_missing:
        if progress_callback:
            progress_callback(
                f"{len(cities_missing)} cities not in stored data, "
                "trying atVenu API..."
            )
        api_lookup = _fetch_atvenu_api_venues(band_name)

    # Enrichment data
    artist_meta_df = _optional_csv(artist_meta_path)
    spotify_df = _optional_csv(spotify_path)
    band_genre_df = _optional_csv(band_genre_map_path)

    genre = _genre_for_band(band_name, artist_meta_df, band_genre_df)
    instagram = _instagram_for_band(band_name, artist_meta_df)
    spotify_listeners, spotify_missing = _spotify_for_band(band_name, spotify_df)

    # Build output rows
    output_rows: list[dict[str, Any]] = []
    venue_match_count = 0
    price_miss_skus: list[str] = []

    for show in shows:
        show_date = show["date"]
        show_date_obj = dt.datetime.strptime(show_date, "%Y-%m-%d").date()
        holiday_status = _holiday_status(show_date_obj)

        venue_info = _match_city(show["city"], venue_lookup)
        if venue_info is None:
            venue_info = _match_city(show["city"], api_lookup)
        if venue_info:
            venue_match_count += 1

        venue_name = venue_info["venue"] if venue_info else ""
        venue_state = venue_info["state"] if venue_info else US_CITY_STATE.get(show["city"], "")
        attendance = venue_info["attendance"] if venue_info else 0
        capacity = venue_info["capacity"] if venue_info else 0
        postal_code = venue_info.get("zip", "") if venue_info else ""
        venue_country = _venue_country(venue_state) if venue_state else "United States"

        weather = {"temperature_daily_mean": 15.0, "rain": 0.0, "snowfall": 0.0}
        if fetch_weather:
            lat, lon = _geocode_city(show["city"], venue_state)
            weather = _fetch_weather(lat, lon, show_date)

        for _, product in products_df.iterrows():
            sku = str(product["SKU"])
            price = sku_to_price.get(sku, None)
            if price is None and sku:
                price_miss_skus.append(sku)

            output_rows.append({
                "artistName": band_name,
                "Genre": genre,
                "showDate": show_date,
                "HolidayStatus": holiday_status,
                "venue name": venue_name,
                "venue city": show["city"],
                "venue state": venue_state,
                "venue country": venue_country,
                "venue postalCode": postal_code,
                "merch category": str(product["Item Name"]),
                "productType": str(product["productType"]),
                "product size": str(product["product size"]),
                "attendance": int(attendance),
                "product price": float(price) if price is not None else float("nan"),
                "temperature_daily_mean": float(weather["temperature_daily_mean"]),
                "rain": float(weather["rain"]),
                "snowfall": float(weather["snowfall"]),
                "spotifyMonthlyListeners": int(spotify_listeners),
                "Instagram": int(instagram),
                "venue capacity": int(capacity),
                "spotifyMissing": int(spotify_missing),
            })

    out_df = pd.DataFrame(output_rows)
    out_df = out_df[OUTPUT_COLUMNS]

    unique_price_misses = sorted(set(price_miss_skus))
    metadata = {
        "band_name": band_name,
        "shows_parsed": len(shows),
        "products_parsed": len(products_df),
        "rows_out": int(out_df.shape[0]),
        "venue_matches": venue_match_count,
        "venue_misses": len(shows) - venue_match_count,
        "price_miss_skus": unique_price_misses,
        "fetch_weather": bool(fetch_weather),
        "show_dates": [s["date"] for s in shows],
        "show_cities": [s["city"] for s in shows],
    }
    return out_df, metadata
