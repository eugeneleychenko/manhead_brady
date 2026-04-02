# New Prediction Model Flow

```mermaid
flowchart TD
    subgraph External["External Data Sources"]
        ATV["atVenu.com"]
        OM["Open-Meteo API<br/><i>Historical weather</i>"]
        SPOT["Spotify CSV<br/><i>Monthly listeners</i>"]
        IG["Artist Metadata CSV<br/><i>Instagram followers, Genre</i>"]
    end

    subgraph Input["Raw Input Files from atVenu"]
        SR["Sales Report CSV<br/><i>atvenu > Reports > Tour > Sales Report</i>"]
        TS["Tour Summary CSV<br/><i>atvenu > Reports > Tour > Tour Summary</i>"]
        INV["Inventory File (Excel/CSV)<br/><i>atvenu > Tours > MerchIQ ><br/>Tour Forecast > Products</i>"]
    end

    ATV --> SR
    ATV --> TS
    ATV --> INV

    subgraph App["mh-predict-new-model.streamlit.app"]

        S1["<b>Step 1: Add New Artist Data</b><br/>Artist name, Instagram followers, Genre<br/><i>Only needed for new/unknown artists</i>"]

        subgraph PathA["Path A: Full Consolidation Pipeline"]
            S2["<b>Step 2: Format & Consolidate</b><br/>Drops raw files into CSVs/ folders,<br/>runs consolidate_pipeline.py<br/><i>Output: merged_with_weather.csv (21 cols)</i>"]
        end

        subgraph PathB["Path B: Quick Converter"]
            S6["<b>Step 6: Sales Report Converter</b><br/>Upload sales report + tour summary<br/>Enter band name, optional date override<br/><i>Output: converted_prediction_input.csv (21 cols)</i>"]
        end

        S4["<b>Step 4: Run Predictions</b><br/>Upload 21-column CSV<br/>Sends to Flask API<br/><i>Output: predictions with sales qty per SKU/size</i>"]

        S5["<b>Step 5: Revenue Per Head</b><br/>Upload Step 4 output<br/>Calculates $/head metrics<br/><i>Output: predictions + revenue per head summary</i>"]
    end

    subgraph Backend["Prediction Backend (Replit Reserved VM)"]
        API["Flask API<br/>manhead-new-prediction-mar-26.replit.app<br/><b>/api/predict</b><br/><i>ExtraTreesRegressor model (2.8 GB)</i>"]
    end

    S1 --> IG
    IG --> S2
    IG --> S6
    SPOT --> S2
    SPOT --> S6
    OM --> S2
    OM -.->|"Optional: fetch weather"| S6

    INV --> S2
    SR --> S6
    TS --> S6
    SR --> S2
    TS --> S2

    S2 -->|"merged_with_weather.csv<br/>21 columns"| S4
    S6 -->|"converted_prediction_input.csv<br/>21 columns"| S4

    S4 -->|"HTTP POST /api/predict<br/>multipart file upload"| API
    API -->|"JSON predictions"| S4

    S4 -->|"prediction output CSV"| S5

    style PathA fill:#e8f4e8,stroke:#4a9e4a
    style PathB fill:#e8e8f4,stroke:#4a4a9e
    style Backend fill:#f4e8e8,stroke:#9e4a4a
    style External fill:#f4f4e8,stroke:#9e9e4a
```

## 21-Column Prediction Input Format
Both Path A and Path B produce a CSV with these columns:

```
artistName, Genre, showDate, HolidayStatus, venue name, venue city,
venue state, venue country, venue postalCode, merch category, productType,
product size, attendance, product price, temperature_daily_mean, rain,
snowfall, spotifyMonthlyListeners, Instagram, venue capacity, spotifyMissing
```

## Quick Reference

| Path | When to Use | Input Files | Enrichment |
|------|-------------|-------------|------------|
| **Path A** (Step 2) | Bulk processing, full enrichment | Inventory + Sales Reports + Tour Summary dropped into CSVs/ folders | Real weather, Spotify, Instagram from files |
| **Path B** (Step 6) | Quick single-show conversion | Sales Report CSV + Tour Summary CSV uploaded directly | Default weather (15C, no rain) unless checkbox enabled |
