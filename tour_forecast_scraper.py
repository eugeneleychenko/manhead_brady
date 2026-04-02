from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
import time
import logging
import csv
import re
from datetime import datetime

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
                    attendance = row[8] if len(row) > 8 else '0'
                    key = (band, city)
                    venues[key] = {
                        'venue': venue,
                        'state': state,
                        'attendance': attendance
                    }
    except FileNotFoundError:
        logging.warning(f"Tour data file not found: {filepath}")
    return venues


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


def scrape_forecast_page(driver, band_name, genre_info, sku_prices, tour_data):
    """Scrape the tour forecast products page for a band."""
    rows = []

    artist_name = genre_info['band_name'] if genre_info else band_name.replace(' (MH)', '')
    genre = genre_info['genre'] if genre_info else ''

    # Extract show dates and cities from header table (index 9 - the one with class containing 'header')
    show_columns = driver.execute_script("""
        var headers = document.querySelectorAll('th.borderless.med-date');
        if (headers.length === 0) {
            headers = document.querySelectorAll('th.borderless.med-date.lighter');
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
        var merchDivs = document.querySelectorAll('div.merch-item-row');
        var dataTables = document.querySelectorAll('table.tour-forecast-product-numbers:not(.tour-forecast-product-numbers-header)');
        
        // The page has two sets of tables: left summary (2 cols) and right numbers (16+ cols)
        // We need the left tables (first half) for SKU names and the right tables for per-show data
        // Left tables have 2 columns (size label + SKU), right tables have many columns
        
        var products = [];
        var leftTables = [];
        var rightTables = [];
        
        for (var i = 0; i < dataTables.length; i++) {
            var firstRow = dataTables[i].rows[0];
            if (firstRow && firstRow.cells.length <= 2) {
                leftTables.push(dataTables[i]);
            } else {
                rightTables.push(dataTables[i]);
            }
        }
        
        // Left tables have the product type info in the merch-item-row divs
        for (var i = 0; i < leftTables.length; i++) {
            var table = leftTables[i];
            var skus = [];
            var dataRows = table.querySelectorAll('tr');
            
            for (var j = 0; j < dataRows.length; j++) {
                var cells = dataRows[j].querySelectorAll('td');
                for (var k = 0; k < cells.length; k++) {
                    var cls = cells[k].className;
                    if (cls.indexOf('borderless') >= 0 && cls.indexOf('sm') >= 0 && cls.indexOf('right') >= 0) {
                        // This is a size label cell (S, M, L, etc.)
                    }
                }
            }
            
            // Get SKUs from the right table
            if (i < rightTables.length) {
                var rTable = rightTables[i];
                var rRows = rTable.querySelectorAll('tr');
                for (var j = 1; j < rRows.length; j++) {  // skip header row
                    var firstCell = rRows[j].querySelector('td.borderless.compact');
                    if (firstCell) {
                        var sku = firstCell.textContent.trim();
                        if (sku) {
                            skus.push(sku);
                        }
                    }
                }
            }
            
            products.push({skus: skus});
        }
        
        // Get product names from merch-item-row divs (only first set, not duplicated)
        var productNames = [];
        for (var i = 0; i < merchDivs.length; i++) {
            var nameEl = merchDivs[i].querySelector('h4, h3, strong');
            if (nameEl) {
                var name = nameEl.textContent.trim();
                // Also try to get product type from the div
                var typeEl = merchDivs[i].querySelector('.product-type, [class*="type"]');
                var typeText = '';
                var allText = merchDivs[i].textContent;
                var typeMatch = allText.match(/Type\\s*[:\\s]+(\\S[^\\n]*)/);
                if (typeMatch) {
                    typeText = typeMatch[1].trim();
                }
                productNames.push({name: name, type: typeText});
            }
        }
        
        return {products: products, productNames: productNames, leftCount: leftTables.length, rightCount: rightTables.length};
    """)

    product_names = products.get('productNames', [])
    product_data = products.get('products', [])

    logging.info(f"  Found {len(product_names)} products, {len(product_data)} SKU groups")

    for prod_idx, prod in enumerate(product_data):
        prod_name = product_names[prod_idx]['name'] if prod_idx < len(product_names) else f'Unknown Product {prod_idx}'
        prod_type_raw = product_names[prod_idx].get('type', '') if prod_idx < len(product_names) else ''
        prod_type = prod_type_raw if prod_type_raw else extract_product_type_from_name(prod_name)

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

                # Look up venue and attendance from tour data
                venue_info = tour_data.get((band_name, city), {})
                venue_name = venue_info.get('venue', '')
                venue_state = venue_info.get('state', '')
                attendance = venue_info.get('attendance', 0)

                rows.append({
                    'artistName': artist_name,
                    'Genre': genre,
                    'showDate': show_date_fmt,
                    'venue name': venue_name,
                    'venue city': city,
                    'venue state': venue_state,
                    'attendance': attendance,
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
    logging.info(f"Loaded {len(genre_map)} genre mappings, {len(sku_prices)} SKU prices, {len(tour_data)} venue entries")

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

            rows = scrape_forecast_page(driver, band_name, genre_info, sku_prices, tour_data)
            all_rows.extend(rows)
            logging.info(f"  Extracted {len(rows)} rows")

            time.sleep(2)

        # Write output CSV
        fieldnames = ['artistName', 'Genre', 'showDate', 'venue name', 'venue city',
                      'venue state', 'attendance', 'product size', 'productType',
                      'product price', 'Item Name']

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
