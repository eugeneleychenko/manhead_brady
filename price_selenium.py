from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
import time
import logging
import csv
import os
import re
from datetime import datetime

# Setup basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Login URL and credentials
login_url = 'https://artist.atvenu.com/users/sign_in'
email = 'chriswithmanhead@gmail.com'
password = 'cali2580'

# Function to convert forecast URL to tour plan merch items URL
def convert_to_merch_items_url(forecast_url):
    # Extract talent_id and tour_id from the forecast URL
    match = re.search(r'talents/(\d+)/tours/(\d+)', forecast_url)
    if match:
        talent_id = match.group(1)
        tour_id = match.group(2)
        return f'https://artist.atvenu.com/as/talents/{talent_id}/tour_plan_merch_items?tour_id={tour_id}'
    return None

# Setup WebDriver
service = Service(ChromeDriverManager().install())
driver = webdriver.Chrome(service=service)

# Create a CSV file to store the data with timestamp
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
output_csv_filename = f'band_product_data_{timestamp}.csv'
csv_exists = False  # Always create a new file with headers

# Read the bands CSV file
bands_csv_filename = 'bandsTableWithMerchIQ.csv'

try:
    # Navigate to the login page
    driver.get(login_url)
    logging.info("Opened login page.")

    # Enter login credentials and submit form
    driver.find_element(By.ID, 'userEmail').send_keys(email)
    driver.find_element(By.ID, 'userPassword').send_keys(password)
    
    time.sleep(3)  # Wait before clicking submit
    driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]').click()
    logging.info("Login submitted.")

    # Wait for navigation to complete
    time.sleep(5)  # Adjust sleep time as necessary

    # Open the output CSV file
    with open(output_csv_filename, 'a', newline='') as output_csvfile:
        fieldnames = ['Band Name', 'SKU', 'Price']
        writer = csv.DictWriter(output_csvfile, fieldnames=fieldnames)
        
        # Write header only if file doesn't exist
        if not csv_exists:
            writer.writeheader()
        
        # Read the bands CSV file
        with open(bands_csv_filename, 'r', newline='') as bands_csvfile:
            bands_reader = csv.DictReader(bands_csvfile)
            bands_list = list(bands_reader)
            
            total_bands = len(bands_list)
            bands_with_merchiq = sum(1 for band in bands_list if band['Has MerchIQ'] == 'Yes' and band['MerchIQ Link'])
            
            logging.info(f"Found {total_bands} total bands, {bands_with_merchiq} with MerchIQ links")
            
            for index, band in enumerate(bands_list):
                band_name = band['Band Name']
                has_merchiq = band['Has MerchIQ']
                merchiq_link = band['MerchIQ Link']
                
                # Skip bands without MerchIQ
                if has_merchiq != 'Yes' or not merchiq_link:
                    continue
                
                logging.info(f"Processing band {index+1}/{total_bands}: {band_name}")
                
                # Convert the MerchIQ link to tour plan merch items URL
                tour_plan_url = convert_to_merch_items_url(merchiq_link)
                if not tour_plan_url:
                    logging.warning(f"Could not convert URL for {band_name}: {merchiq_link}")
                    # Write a record for the band with URL conversion error
                    writer.writerow({
                        'Band Name': band_name,
                        'SKU': 'URL conversion error',
                        'Price': merchiq_link
                    })
                    continue
                
                logging.info(f"Navigating to: {tour_plan_url}")
                driver.get(tour_plan_url)
                
                # Wait for the page to load
                time.sleep(5)  # Adjust sleep time as necessary
                
                try:
                    # Find all merch item rows
                    merch_item_rows = driver.find_elements(By.CSS_SELECTOR, 'div.merch-item-row')
                    logging.info(f"Found {len(merch_item_rows)} merchandise items for {band_name}.")
                    
                    # If no merchandise items found, still write a record for the band
                    if len(merch_item_rows) == 0:
                        writer.writerow({
                            'Band Name': band_name,
                            'SKU': 'No items found',
                            'Price': 'N/A'
                        })
                        logging.info(f"No merchandise items found for {band_name}")
                    
                    # Process each merch item
                    for row in merch_item_rows:
                        # Find all size/SKU rows for this product
                        merch_types = row.find_elements(By.CSS_SELECTOR, 'tr[data-tour-plan-merch-type-index]')
                        
                        for merch_type in merch_types:
                            try:
                                # Extract SKU
                                sku = merch_type.find_element(By.CSS_SELECTOR, 'td.compact').text
                                
                                # Extract price
                                price_input = merch_type.find_element(By.CSS_SELECTOR, 'input[data-qa="sale-price"]')
                                price = price_input.get_attribute('value')
                                
                                # Write to CSV
                                writer.writerow({
                                    'Band Name': band_name,
                                    'SKU': sku,
                                    'Price': price
                                })
                                
                                logging.info(f"Saved data for {band_name} - {sku} - ${price}")
                            except Exception as e:
                                logging.warning(f"Error processing merch type for {band_name}: {str(e)}")
                except Exception as e:
                    logging.warning(f"Error processing band {band_name}: {str(e)}")
                    # Write a record for the band that encountered an error
                    writer.writerow({
                        'Band Name': band_name,
                        'SKU': 'Error processing band',
                        'Price': str(e)[:100]  # Truncate error message if too long
                    })

                # Add a small delay between processing bands to avoid overloading the server
                time.sleep(2)

    logging.info(f"Data successfully exported to {output_csv_filename}")

except Exception as e:
    logging.exception("An error occurred: " + str(e))
finally:
    driver.quit()
    logging.info("Browser closed.")
