"""
Fetch future show data (capacity, venue, state) from the atVenu GraphQL API.
Used by prediction-streamlit.py to estimate attendance as 80% of venue capacity.
"""

import os
import pandas as pd
from datetime import datetime, timedelta

ATVENU_API_ENDPOINT = "https://api.atvenu.com"
ATVENU_API_TOKEN = os.environ.get("ATVENU_API_TOKEN", "live_yvYLBo32dRE9z_yCdhwU")

ATTENDANCE_RATIO = 0.80

US_CITY_STATE = {
    "Lancaster": "PA", "Englewood": "NJ", "Flint": "MI", "Prior Lake": "MN",
    "Kansas City": "MO", "Saint Louis": "MO", "St. Louis": "MO", "West Palm Beach": "FL",
    "Miami": "FL", "Myrtle Beach": "SC", "Mrytle Beach": "SC", "Las Vegas": "NV",
    "North Tonawanda": "NY", "Greensburg": "PA", "San Jose": "CA", "San Francisco": "CA",
    "Los Angeles": "CA", "San Diego": "CA", "New York": "NY", "Brooklyn": "NY",
    "Chicago": "IL", "Houston": "TX", "Dallas": "TX", "Austin": "TX", "Denver": "CO",
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
    "Sarasota": "FL", "Fort Myers": "FL", "Fort Lauderdale": "FL", "Pompano Beach": "FL",
    "Boca Raton": "FL", "Temecula": "CA", "Chandler": "AZ", "Red Bank": "NJ",
    "Oxon Hill": "MD", "Durham": "NC", "Lincoln City": "OR", "Hershey": "PA",
    "Bensalem": "PA", "Greenville": "SC", "Morrison": "CO", "Napa": "CA",
    "Valley Center": "CA", "Rancho Mirage": "CA",
    "Toronto": "ON", "Montreal": "QC", "Vancouver": "BC", "Calgary": "AB",
    "Edmonton": "AB", "Ottawa": "ON", "Winnipeg": "MB", "Halifax": "NS",
}


def _resolve_state(city, api_state):
    if api_state and api_state != "null" and api_state.strip():
        return api_state
    for known_city, st in US_CITY_STATE.items():
        if city.lower() == known_city.lower():
            return st
    return ""


def _get_client():
    from gql import Client, gql
    from gql.transport.requests import RequestsHTTPTransport

    transport = RequestsHTTPTransport(
        url=ATVENU_API_ENDPOINT,
        headers={"x-api-key": ATVENU_API_TOKEN},
        retries=3,
        timeout=30,
    )
    return Client(transport=transport, fetch_schema_from_transport=True)


SHOWS_QUERY_STR = """
query getFutureShows(
  $firstForAccounts: Int!,
  $afterForAccounts: String,
  $firstForTours: Int!,
  $firstForShows: Int!,
  $dateRange: DateRange!
) {
  organization {
    name
    accounts(first: $firstForAccounts, after: $afterForAccounts) {
      pageInfo { endCursor hasNextPage }
      nodes {
        name
        tours(first: $firstForTours) {
          nodes {
            name
            shows(first: $firstForShows, showsOverlap: $dateRange) {
              nodes {
                showDate
                capacity
                attendance
                nights
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


def _parse_city_state(location_city):
    if not location_city:
        return "", ""
    parts = location_city.split(",")
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return location_city, ""


def fetch_shows_from_api(start_date=None, end_date=None):
    """
    Fetch all future shows from atVenu API.
    Returns a list of dicts with keys: Band, Show Date, City, ST, Venue, Capacity, Attn.
    """
    from gql import gql

    if not start_date:
        start_date = datetime.now().strftime("%Y-%m-%d")
    if not end_date:
        end_date = (datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d")

    client = _get_client()
    query = gql(SHOWS_QUERY_STR)
    all_shows = []
    cursor = None

    while True:
        data = client.execute(
            query,
            variable_values={
                "firstForAccounts": 20,
                "afterForAccounts": cursor,
                "firstForTours": 10,
                "firstForShows": 50,
                "dateRange": {"start": start_date, "end": end_date},
            },
        )

        accounts_conn = data["organization"]["accounts"]
        for account in accounts_conn["nodes"]:
            band_name = account.get("name", "")
            for tour in account.get("tours", {}).get("nodes", []):
                for show in tour.get("shows", {}).get("nodes", []):
                    location = show.get("location") or {}
                    city_raw = location.get("city", "")
                    city, state = _parse_city_state(city_raw)

                    capacity = show.get("capacity") or 0
                    attn = show.get("attendance")

                    show_date = show.get("showDate", "")
                    if show_date:
                        try:
                            show_date = datetime.strptime(show_date, "%Y-%m-%d").strftime("%m/%d/%Y")
                        except Exception:
                            pass

                    all_shows.append({
                        "Band": band_name,
                        "Show Date": show_date,
                        "City": city,
                        "ST": state,
                        "Venue": location.get("name", ""),
                        "Capacity": int(capacity),
                        "Attn": int(attn) if attn else 0,
                    })

        page_info = accounts_conn["pageInfo"]
        if not page_info["hasNextPage"]:
            break
        cursor = page_info["endCursor"]

    return all_shows


def get_band_venue_data(band_name, start_date=None, end_date=None):
    """
    Fetch venue data for a specific band. Returns a dict keyed by lowercase city name:
    {city: {venue, state, capacity, estimated_attendance}}
    """
    all_shows = fetch_shows_from_api(start_date, end_date)

    venue_lookup = {}
    for show in all_shows:
        if show["Band"].lower().strip() != band_name.lower().strip():
            continue

        city = show["City"].strip()
        if not city:
            continue

        capacity = show["Capacity"]
        attn = show["Attn"]
        estimated_attendance = attn if attn > 0 else int(capacity * ATTENDANCE_RATIO)

        venue_lookup[city.lower()] = {
            "venue": show["Venue"],
            "state": _resolve_state(city, show["ST"]),
            "capacity": capacity,
            "attendance": estimated_attendance,
            "show_date": show["Show Date"],
        }

    return venue_lookup
