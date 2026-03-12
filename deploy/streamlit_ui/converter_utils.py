from __future__ import annotations

import csv
import datetime as dt
import re
from io import StringIO
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
