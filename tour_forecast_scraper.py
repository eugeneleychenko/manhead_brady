from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
import sys
import os
import time
import logging
import csv
import re
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'prediction'))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

login_url = 'https://artist.atvenu.com/users/sign_in'
email = 'chriswithmanhead@gmail.com'
password = 'cali2580'

BANDS_CSV = 'bandsTableWithMerchIQ.csv'
GENRE_CSV = 'prediction/band_genre_map.csv'
TOUR_DATA_CSV = 'tour_data.csv'
SKU_PRICE_CSV = 'prediction/band_sku_price_data.csv'

timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
OUTPUT_CSV = f'tour_forecast_all_bands_{timestamp}.csv'


def load_genre_map(filepath):
    """Load MH band name -> Genre mapping."""
    genres = {}
    with open(filepath, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            genres[row['MH band']] = {
                'band_name': row['Band Name'],
                'genre': row['Genre']
            }
    return genres


def load_sku_prices(filepath):
    """Load SKU -> Price mapping."""
    prices = {}
    with open(filepath, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            prices[(row['Band Name'], row['SKU'])] = row['Price']
    return prices


def load_tour_data(filepath):
    """Load tour data for venue/attendance lookup."""
    venues = {}
    try:
        with open(filepath, 'r') as f:
            reader = csv.reader(f)
            for row in reader:
                if len(row) >= 5:
                    band = row[0]
                    date = row[1] if len(row) > 1 else ''
                    city = row[2] if len(row) > 2 else ''
                    state = row[3] if len(row) > 3 else ''
                    venue = row[4] if len(row) > 4 else ''
                    capacity = row[7] if len(row) > 7 else '0'
                    attendance = row[8] if len(row) > 8 else '0'
                    key = (band, city)
                    venues[key] = {
                        'venue': venue,
                        'state': state,
                        'capacity': capacity,
                        'attendance': attendance
                    }
    except FileNotFoundError:
        logging.warning(f"Tour data file not found: {filepath}")
    return venues


def load_venue_capacity_from_api():
    """Fetch venue capacity for all future shows via atVenu GraphQL API."""
    try:
        from atvenu_api import fetch_shows_from_api
        shows = fetch_shows_from_api()
        capacity_lookup = {}
        for show in shows:
            band = show['Band']
            city = show['City']
            if band and city:
                key = (band, city.lower())
                capacity_lookup[key] = {
                    'capacity': show['Capacity'],
                    'attendance': show['Attn'],
                    'venue': show['Venue'],
                    'state': show['ST'],
                }
        logging.info(f"Loaded {len(capacity_lookup)} venue entries from atVenu API")
        return capacity_lookup
    except Exception as e:
        logging.warning(f"Failed to load venue data from atVenu API: {e}")
        return {}


def convert_to_forecast_url(merchiq_link):
    """Convert MerchIQ link to tour_forecast_merch_items URL."""
    match = re.search(r'talents/(\d+)/tours/(\d+)', merchiq_link)
    if match:
        return f'https://artist.atvenu.com/as/talents/{match.group(1)}/tour_forecast_merch_items?tour_id={match.group(2)}'
    match = re.search(r'talents/(\d+)/tour_forecast_merch_items\?tour_id=(\d+)', merchiq_link)
    if match:
        return merchiq_link
    return None


def extract_product_type_from_name(product_name):
    """Infer product type from the product name."""
    name_lower = product_name.lower()
    if any(w in name_lower for w in ['tee', 't-shirt', 'shirt']):
        return 'T-Shirt'
    if any(w in name_lower for w in ['hoodie', 'hood', 'sweatshirt', 'pullover']):
        return 'Hoodie/Outerwear'
    if any(w in name_lower for w in ['tank']):
        return 'Tank Top'
    if any(w in name_lower for w in ['hat', 'cap', 'beanie']):
        return 'Hat/Headwear'
    if any(w in name_lower for w in ['poster', 'print', 'litho']):
        return 'Poster/Print'
    if any(w in name_lower for w in ['blanket', 'towel', 'flag']):
        return 'Lifestyle'
    if any(w in name_lower for w in ['koozie', 'cup', 'mug', 'bottle', 'pint']):
        return 'Drinkware'
    if any(w in name_lower for w in ['bandana', 'bag', 'tote', 'patch', 'pin', 'sticker', 'keychain', 'lanyard', 'bracelet']):
        return 'Accessory'
    return 'Other'


def extract_size_from_sku(sku):
    """Extract size from SKU string."""
    sku_upper = sku.upper()
    for size in ['3XL', '3X', 'XXXL', '2XL', 'XXL', 'XL', 'L', 'M', 'S']:
        if sku_upper.endswith(f'-{size}'):
            return size
    return 'ONE SIZE'


def scrape_forecast_page(driver, band_name, genre_info, sku_prices, tour_data, api_venues):
    """Scrape the tour forecast products page for a band."""
    rows = []

    artist_name = genre_info['band_name'] if genre_info else band_name.replace(' (MH)', '')
    genre = genre_info['genre'] if genre_info else ''

    # Extract show dates and cities from header table (index 9 - the one with class containing 'header')
    show_columns = driver.execute_script("""
        var headers = document.querySelectorAll('td.med-date');
        if (headers.length === 0) {
            headers = document.querySelectorAll('td.borderless.med-date');
        }
        var shows = [];
        for (var i = 0; i < headers.length; i++) {
            var text = headers[i].textContent.trim();
            var lines = text.split('\\n').map(function(l) { return l.trim(); }).filter(function(l) { return l; });
            if (lines.length >= 2) {
                shows.push({date: lines[0], city: lines[1]});
            } else if (lines.length === 1) {
                shows.push({date: lines[0], city: ''});
            }
        }
        return shows;
    """)

    if not show_columns:
        logging.warning(f"No show dates found for {band_name}")
        return rows

    logging.info(f"  Found {len(show_columns)} upcoming shows")

    # Extract products: each div.merch-item-row on the LEFT side has product info
    # The right-side tables (class containing 'tour-forecast-product-numbers') have the SKU data
    products = driver.execute_script("""
        var dataTables = document.querySelectorAll('table.tour-forecast-product-numbers:not(.tour-forecast-product-numbers-header)');
        
        var leftTables = [];
        var rightTables = [];
        
        for (var i = 0; i < dataTables.length; i++) {
            var firstRow = dataTables[i].rows[0];
            if (firstRow && firstRow.cells.length <= 4) {
                leftTables.push(dataTables[i]);
            } else {
                rightTables.push(dataTables[i]);
            }
        }
        
        // Get SKUs from right-side tables (they have td.borderless.compact with SKU text)
        var products = [];
        for (var i = 0; i < rightTables.length; i++) {
            var rTable = rightTables[i];
            var skus = [];
            var rRows = rTable.querySelectorAll('tr');
            for (var j = 1; j < rRows.length; j++) {
                var firstCell = rRows[j].querySelector('td.compact');
                if (firstCell) {
                    var sku = firstCell.textContent.trim();
                    if (sku) skus.push(sku);
                }
            }
            products.push({skus: skus});
        }
        
        // Get product names and Type from merch-item-row divs
        var merchDivs = document.querySelectorAll('div.merch-item-row');
        var productNames = [];
        for (var i = 0; i < merchDivs.length; i++) {
            var nameEl = merchDivs[i].querySelector('h4, h3, strong');
            if (nameEl) {
                var name = nameEl.textContent.trim();
                // Extract the Type field directly from the label/value pairs
                var typeText = '';
                var labels = merchDivs[i].querySelectorAll('span, div, td, dt, dd, p, b');
                for (var j = 0; j < labels.length; j++) {
                    var lbl = labels[j].textContent.trim();
                    if (lbl === 'Type' && labels[j+1]) {
                        typeText = labels[j+1].textContent.trim();
                        break;
                    }
                }
                // Fallback: regex on full text
                if (!typeText) {
                    var allText = merchDivs[i].textContent;
                    var typeMatch = allText.match(/Type\\s+([A-Za-z][A-Za-z /-]*)/);
                    typeText = typeMatch ? typeMatch[1].trim() : '';
                }
                productNames.push({name: name, type: typeText});
            }
        }
        
        return {products: products, productNames: productNames};
    """)

    product_names = products.get('productNames', [])
    product_data = products.get('products', [])

    logging.info(f"  Found {len(product_names)} products, {len(product_data)} SKU groups")

    for prod_idx, prod in enumerate(product_data):
        prod_name = product_names[prod_idx]['name'] if prod_idx < len(product_names) else f'Unknown Product {prod_idx}'
        prod_type_raw = product_names[prod_idx].get('type', '') if prod_idx < len(product_names) else ''
        # Use the actual Type from the page, lowercased to match model encoder
        prod_type = prod_type_raw.lower().strip() if prod_type_raw else extract_product_type_from_name(prod_name).lower().strip()

        for sku in prod.get('skus', []):
            if not sku:
                continue

            size = extract_size_from_sku(sku)

            # Look up price
            price = sku_prices.get((artist_name, sku), '')

            for show in show_columns:
                show_date = show['date']
                city = show['city']

                # Convert date format from MM/DD/YY to M/D/YYYY
                try:
                    dt = datetime.strptime(show_date, '%m/%d/%y')
                    show_date_fmt = dt.strftime('%-m/%-d/%Y')
                except Exception:
                    show_date_fmt = show_date

                # Look up venue info: prefer API data, fall back to tour_data.csv
                api_key = (band_name, city.lower())
                api_info = api_venues.get(api_key, {})
                td_info = tour_data.get((band_name, city), {})

                venue_name = api_info.get('venue') or td_info.get('venue', '')
                venue_state = api_info.get('state') or td_info.get('state', '')
                attendance = api_info.get('attendance') or td_info.get('attendance', 0)
                venue_capacity = api_info.get('capacity') or td_info.get('capacity', 0)

                rows.append({
                    'artistName': artist_name,
                    'Genre': genre,
                    'showDate': show_date_fmt,
                    'venue name': venue_name,
                    'venue city': city,
                    'venue state': venue_state,
                    'attendance': attendance,
                    'venue capacity': venue_capacity,
                    'product size': size,
                    'productType': prod_type,
                    'product price': price,
                    'Item Name': prod_name
                })

    return rows


def main():
    genre_map = load_genre_map(GENRE_CSV)
    sku_prices = load_sku_prices(SKU_PRICE_CSV)
    tour_data = load_tour_data(TOUR_DATA_CSV)
    api_venues = load_venue_capacity_from_api()
    logging.info(f"Loaded {len(genre_map)} genre mappings, {len(sku_prices)} SKU prices, {len(tour_data)} tour data entries, {len(api_venues)} API venue entries")

    # Read bands with MerchIQ
    bands = []
    with open(BANDS_CSV, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row['Has MerchIQ'] == 'Yes' and row.get('MerchIQ Link'):
                bands.append(row)
    logging.info(f"Found {len(bands)} bands with MerchIQ links")

    service = Service(ChromeDriverManager().install())
    options = webdriver.ChromeOptions()
    options.add_argument('--no-first-run')
    options.add_argument('--no-default-browser-check')
    options.add_argument('--disable-search-engine-choice-screen')
    driver = webdriver.Chrome(service=service, options=options)

    all_rows = []

    try:
        # Login
        driver.get(login_url)
        time.sleep(3)
        driver.find_element(By.ID, 'userEmail').send_keys(email)
        driver.find_element(By.ID, 'userPassword').send_keys(password)
        time.sleep(2)
        driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]').click()
        time.sleep(5)
        logging.info("Logged in successfully")

        for i, band in enumerate(bands):
            band_name = band['Band Name']
            merchiq_link = band['MerchIQ Link']
            logging.info(f"Processing {i+1}/{len(bands)}: {band_name}")

            forecast_url = convert_to_forecast_url(merchiq_link)
            if not forecast_url:
                logging.warning(f"  Could not convert URL: {merchiq_link}")
                continue

            driver.get(forecast_url)
            time.sleep(5)

            genre_info = genre_map.get(band_name)
            if not genre_info:
                # Try without (MH) suffix
                for key in genre_map:
                    if band_name.startswith(key) or key.startswith(band_name.replace(' (MH)', '')):
                        genre_info = genre_map[key]
                        break

            if not genre_info:
                logging.warning(f"  No genre mapping found for {band_name}")
                genre_info = {'band_name': band_name.replace(' (MH)', ''), 'genre': ''}

            rows = scrape_forecast_page(driver, band_name, genre_info, sku_prices, tour_data, api_venues)
            all_rows.extend(rows)
            logging.info(f"  Extracted {len(rows)} rows")

            time.sleep(2)

        # Write output CSV
        fieldnames = ['artistName', 'Genre', 'showDate', 'venue name', 'venue city',
                      'venue state', 'attendance', 'venue capacity', 'product size',
                      'productType', 'product price', 'Item Name']

        with open(OUTPUT_CSV, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(all_rows)

        logging.info(f"Wrote {len(all_rows)} rows to {OUTPUT_CSV}")

    except Exception as e:
        logging.exception(f"An error occurred: {e}")
    finally:
        driver.quit()
        logging.info("Browser closed")


if __name__ == '__main__':
    main()
