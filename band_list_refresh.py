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

OUTPUT_CSV = 'bandsTableWithMerchIQ.csv'
BACKUP_CSV = f'bandsTableWithMerchIQ_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'


def read_existing_bands(filepath):
    """Read existing band data from CSV."""
    bands = {}
    try:
        with open(filepath, 'r', newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                bands[row['Band Name']] = row
    except FileNotFoundError:
        pass
    return bands


def get_all_band_names(driver):
    """Open the account dropdown and extract all band names."""
    dropdown = driver.find_element(By.CSS_SELECTOR, '[id*="mainNavAccountSelect"]')
    dropdown.click()
    time.sleep(2)

    listbox = driver.find_element(By.ID, 'react-select-mainNavAccountSelect-listbox')
    options = listbox.find_elements(By.CSS_SELECTOR, '[id*="option"]')
    band_names = [opt.text.strip() for opt in options if opt.text.strip()]
    logging.info(f"Found {len(band_names)} bands in dropdown")

    # Close dropdown
    from selenium.webdriver.common.keys import Keys
    driver.find_element(By.TAG_NAME, 'body').send_keys(Keys.ESCAPE)
    time.sleep(1)

    return band_names


def select_band_and_get_links(driver, band_name):
    """Select a band from dropdown and extract talent_id, tour_id, and links from sidebar."""
    # Open dropdown
    dropdown = driver.find_element(By.CSS_SELECTOR, '[id*="mainNavAccountSelect"]')
    dropdown.click()
    time.sleep(1)

    # Type to filter
    input_el = driver.find_element(By.ID, 'react-select-mainNavAccountSelect-input')
    input_el.send_keys(band_name[:20])
    time.sleep(1)

    # Click the matching option
    try:
        listbox = driver.find_element(By.ID, 'react-select-mainNavAccountSelect-listbox')
        options = listbox.find_elements(By.CSS_SELECTOR, '[id*="option"]')
        matched = None
        for opt in options:
            if opt.text.strip() == band_name:
                matched = opt
                break
        if not matched and options:
            matched = options[0]
        if matched:
            matched.click()
            time.sleep(4)
        else:
            logging.warning(f"Could not find option for {band_name}")
            return None
    except Exception as e:
        logging.warning(f"Error selecting {band_name}: {e}")
        from selenium.webdriver.common.keys import Keys
        driver.find_element(By.TAG_NAME, 'body').send_keys(Keys.ESCAPE)
        time.sleep(1)
        return None

    result = {
        'Band Name': band_name,
        'Band Link': driver.current_url,
        'Has MerchIQ': 'No',
        'MerchIQ Link': ''
    }

    try:
        sidebar_links = driver.find_elements(By.CSS_SELECTOR, 'a[href]')
        for link in sidebar_links:
            href = link.get_attribute('href') or ''
            text = link.text.strip()

            # Look for MerchIQ or Tour Forecast link
            if text in ('MerchIQ', 'Tour Forecast') and 'tour_forecast' in href:
                result['Has MerchIQ'] = 'Yes'
                # Convert to the tour_forecast_merch_items URL
                match = re.search(r'talents/(\d+)/tours/(\d+)', href)
                if match:
                    talent_id = match.group(1)
                    tour_id = match.group(2)
                    result['MerchIQ Link'] = f'https://artist.atvenu.com/as/talents/{talent_id}/tour_forecast_merch_items?tour_id={tour_id}'
                    break

        # Fallback: check for talent_id in any sidebar link
        if not result['MerchIQ Link']:
            for link in sidebar_links:
                href = link.get_attribute('href') or ''
                match = re.search(r'talents/(\d+)/tour_forecast_merch_items\?tour_id=(\d+)', href)
                if match:
                    result['Has MerchIQ'] = 'Yes'
                    result['MerchIQ Link'] = href
                    break

    except Exception as e:
        logging.warning(f"Error extracting links for {band_name}: {e}")

    return result


def main():
    existing_bands = read_existing_bands(OUTPUT_CSV)
    logging.info(f"Existing bands in CSV: {len(existing_bands)}")

    # Backup existing file
    if existing_bands:
        import shutil
        try:
            shutil.copy2(OUTPUT_CSV, BACKUP_CSV)
            logging.info(f"Backed up existing CSV to {BACKUP_CSV}")
        except Exception:
            pass

    service = Service(ChromeDriverManager().install())
    options = webdriver.ChromeOptions()
    options.add_argument('--no-first-run')
    options.add_argument('--no-default-browser-check')
    options.add_argument('--disable-search-engine-choice-screen')
    driver = webdriver.Chrome(service=service, options=options)

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

        # Get all band names from dropdown
        all_band_names = get_all_band_names(driver)

        # Find new bands
        new_bands = [b for b in all_band_names if b not in existing_bands]
        if new_bands:
            logging.info(f"Found {len(new_bands)} NEW bands: {new_bands}")
        else:
            logging.info("No new bands found")

        # Find removed bands
        removed = [b for b in existing_bands if b not in all_band_names and b]
        if removed:
            logging.info(f"Bands no longer in dropdown: {removed}")

        # Process new bands to get their links
        updated_bands = dict(existing_bands)
        for i, band_name in enumerate(new_bands):
            logging.info(f"Processing new band {i+1}/{len(new_bands)}: {band_name}")
            band_data = select_band_and_get_links(driver, band_name)
            if band_data:
                updated_bands[band_name] = band_data
                logging.info(f"  MerchIQ: {band_data['Has MerchIQ']}, Link: {band_data['MerchIQ Link'][:80]}")
            time.sleep(2)

        # Also re-check existing bands that had no MerchIQ (they might have it now)
        no_merchiq = [b for b, data in existing_bands.items()
                      if data.get('Has MerchIQ') == 'No' and b in all_band_names and b]
        if no_merchiq:
            logging.info(f"Re-checking {len(no_merchiq)} bands without MerchIQ...")
            for i, band_name in enumerate(no_merchiq):
                logging.info(f"Re-checking {i+1}/{len(no_merchiq)}: {band_name}")
                band_data = select_band_and_get_links(driver, band_name)
                if band_data and band_data['Has MerchIQ'] == 'Yes':
                    updated_bands[band_name] = band_data
                    logging.info(f"  NOW HAS MerchIQ: {band_data['MerchIQ Link'][:80]}")
                time.sleep(2)

        # Write updated CSV preserving dropdown order
        with open(OUTPUT_CSV, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['Band Name', 'Band Link', 'Has MerchIQ', 'MerchIQ Link'])
            writer.writeheader()
            for band_name in all_band_names:
                if band_name in updated_bands:
                    writer.writerow(updated_bands[band_name])
                else:
                    writer.writerow({
                        'Band Name': band_name,
                        'Band Link': 'null',
                        'Has MerchIQ': 'No',
                        'MerchIQ Link': ''
                    })

        logging.info(f"Updated {OUTPUT_CSV} with {len(all_band_names)} bands")
        logging.info(f"New bands added: {len(new_bands)}")
        logging.info(f"Bands removed from dropdown: {len(removed)}")

    except Exception as e:
        logging.exception(f"An error occurred: {e}")
    finally:
        driver.quit()
        logging.info("Browser closed")


if __name__ == '__main__':
    main()
