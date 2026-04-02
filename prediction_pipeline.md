# Old Model (Current Production) - Data Flow

## High-Level Pipeline

```mermaid
flowchart TB
    subgraph STATIC["Static Data (loaded on startup)"]
        S1[("band_genre_map.csv<br/>(local file)<br/>MH band → Band Name → Genre")]
        S2[("band_sku_price_data.csv<br/>(local file)<br/>Band Name → SKU → Price")]
        S3[("tour_data.csv<br/>(fetched from external URL)<br/>atvenu-forecast.votintsev.com<br/>Band → City, Venue, State,<br/>Capacity, Attendance")]
    end

    subgraph FORMAT["Page 1: File Formatting"]
        direction TB
        F1[/"User selects band<br/>from dropdown<br/>(63 bands)"/]
        F2[/"User uploads inventory file<br/>(CSV or Excel)<br/>Columns: Item Name, Product Type,<br/>Size, SKU, show columns"/]

        F3["Parse show columns from headers<br/>'City - MM/DD/YY ($X.XX/head)'<br/>→ extract city, date, price"]
        F2 --> F3

        F4["For each product × show:<br/>- Look up Genre from genre map<br/>- Look up product price by SKU<br/>- Set artistName, productType, size"]
        F1 --> F4
        F3 --> F4
        S1 -.->|genre lookup| F4
        S2 -.->|price by SKU| F4

        F5["Update venue details:<br/>- Match city → tour_data<br/>- Fill in venue name, state<br/>- Fill in attendance<br/>(fuzzy city matching)"]
        F4 --> F5
        S3 -.->|venue + attendance| F5

        F_OUT[("Formatted CSV<br/>Columns: artistName, Genre,<br/>showDate, venue name, venue city,<br/>venue state, attendance,<br/>product size, productType,<br/>product price, Item Name")]
        F5 --> F_OUT
    end

    subgraph PREDICT["Page 2: Prediction"]
        direction TB
        P_IN[/"Upload formatted CSV<br/>or use output from Page 1"/]

        P1{"Select prediction type"}
        P_IN --> P1

        P1 -->|"Sales Quantity By Size"| P2
        P1 -->|"Per Head Revenue"| P3

        P2["POST to external API<br/>fast-api-data-master-eugene59.replit.app<br/>/predict/size<br/>→ returns predicted_sales_quantity<br/>+ %_item_sales_per_category"]

        P3["POST to external API<br/>fast-api-data-master-eugene59.replit.app<br/>/predict/perhead<br/>→ returns predicted_$_per_head"]

        P2_OUT[("predicted_sales_by_size.csv<br/>+ Summary: total sales,<br/>avg per product, product types,<br/>show count")]
        P3_OUT[("predicted_per_head_revenue.csv<br/>+ Summary: avg/median/min/max<br/>$/head, venues, shows")]

        P2 --> P2_OUT
        P3 --> P3_OUT
    end

    subgraph API["External Prediction API (Replit)"]
        direction TB
        API1["FastAPI hosted on Replit<br/>fast-api-data-master-eugene59.replit.app"]
        API2["Size model (joblib)"]
        API3["Per head model (joblib)"]
        API1 --- API2
        API1 --- API3
    end

    FORMAT -.->|"formatted data<br/>(session state or download)"| PREDICT
    PREDICT <-->|"HTTP POST/response"| API
```

## Workflow Summary

### Page 1: File Formatting
1. User selects a band from the dropdown (63 Manhead bands)
2. User uploads an inventory file (CSV/Excel) with show columns in headers
3. System parses show dates/cities from column headers like `"Hershey - 11/08/24 ($7.00/head)"`
4. For each product row x show: builds a record with genre, SKU-based price, venue details
5. Venue name, state, and attendance are matched from external tour data via city name
6. Output: formatted CSV ready for prediction

### Page 2: Prediction
1. User uploads formatted CSV (or carries forward from Page 1)
2. User chooses prediction type:
   - **Sales Quantity By Size**: predicts units sold per product/size/show
   - **Per Head Revenue**: predicts $/head per show
3. Data is sent to an external FastAPI on Replit
4. Results returned with predictions + summary stats

## Architecture

```mermaid
flowchart LR
    USER["User Browser"] --> STREAMLIT["Streamlit App<br/>(single file, 775 lines)<br/>localhost:8502"]
    STREAMLIT -->|"fetch tour_data.csv"| EXTERNAL_CSV["atvenu-forecast.votintsev.com"]
    STREAMLIT -->|"POST /predict/size<br/>POST /predict/perhead"| REPLIT_API["FastAPI on Replit<br/>(hosts ML models)"]
    STREAMLIT -->|"read"| LOCAL[("Local CSV files<br/>band_genre_map.csv<br/>band_sku_price_data.csv")]
```

## Key Differences vs New Ashling Model

| Aspect | Old (This App) | New (Ashling) |
|--------|---------------|---------------|
| Prediction API | External Replit FastAPI | Local Flask on port 5000 |
| Model algorithm | Unknown (hosted externally) | ExtraTreesRegressor (2000 trees) |
| Model size | Unknown (remote) | ~2.9 GB joblib |
| Training data | Unknown (remote) | ~45,800 rows, retrainable |
| Weather data | Not used in formatting | Temperature, rain, snowfall |
| Social data | Not used in formatting | Spotify listeners, Instagram |
| Holiday awareness | No | Yes (US holidays + weekends) |
| Venue geocoding | No | Yes (ZIP → lat/lon) |
| Two prediction types | Size + Per Head (separate) | Size only (Per Head as Step 5) |
| Tour data source | External URL | Local CSV files |
| Price lookup | SKU-based from local CSV | Included in input CSV |
| Retraining | Not possible (remote model) | Built-in Step 3 |
| Data consolidation | Manual formatting only | Automated 5-step pipeline |
