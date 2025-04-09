import streamlit as st
import pandas as pd
import numpy as np
import datetime as dt
import os
import logging
import sys
import requests
from pathlib import Path
from io import BytesIO
from datetime import datetime
from io import StringIO

# Configure logging
timestamp = dt.datetime.now().strftime("%m_%d_%Y-%I_%M_%S_%p")
log_dir = "/tmp"
os.makedirs(log_dir, exist_ok=True)
logging.basicConfig(
    filename=f'{log_dir}/log_predict_merch_app_{timestamp}.log', 
    level=logging.DEBUG, 
    format='%(asctime)s - %(levelname)s - %(filename)s - %(lineno)d - %(message)s'
)

# API Configuration
API_BASE_URL = "https://fast-api-data-master-eugene59.replit.app"

# Define the list of included bands
INCLUDED_BANDS = [
    "Air Supply", "Alan Parsons Live", "All That Remains (MH)", "Apocalyptica",
    "BOYS LIKE GIRLS (MH)", "Bert Kreischer (MH)", "Billy Idol (Manhead)",
    "Billy Porter (MH)", "Black Pistol Fire", "Blindside (MH)", "Butch Walker",
    "Celtic Thunder (MH)", "Celtic Woman", "Clandestine", "Country Music Association (MH)",
    "Dean Lewis (MH)", "Deftones (MH)" "Emerald Cup Festival (MH)", "Fall Out Boy", "JXDN",
    "Jelly Roll (MH)", "Jerry Cantrell (MH)", "Jewel (Manhead)", "Joe Perry Project",
    "Joji (MH)", "Jukebox The Ghost (Manhead)", "Justin Hayward (Manhead)",
    "LIMP BIZKIT (MH)", "Lykke Li (MH)", "Machine Gun Kelly (MH)", "Macklemore (MH)",
    "Marina (MH)", "Marvelous 3", "Masiwei (MH)", "Matt And Kim", "Midnight Oil (MH)",
    "Midtown", "Morrissey", "NIKI", "Nessa Barrett (MH)", "New Edition",
    "Noel Gallagher HFB (MH)", "Panic! At the Disco", "Royal Blood (MH)",
    "Seal (MH)", "Sebastian Maniscalco (MH)", "Sexyy Red", "Shame", "Skegss (MH)",
    "Sonic Symphony", "Taylor Tomlinson (MH)", "The Buggles (MH)", "The Chats (MH)",
    "The Sisters Of Mercy (MH)", "The Smashing Pumpkins (MH)", "The Zombies (MH)",
    "Toto (MH)", "Trevor Noah (MH)", "Tyler Childers (MH)", "Warren Hue", "Willow (MH)",
    "YES (MH)"
]

# Define functions for file processing
def process_inventory_file(inventory_df, band_name, genre_df, price_df):
    # Get genre for the band - Add error handling
    band_genre_match = genre_df[genre_df['MH band'] == band_name]
    if len(band_genre_match) == 0:
        st.error(f"No genre found for band: {band_name}")
        st.write("Available bands in genre mapping:")
        st.write(genre_df['MH band'].tolist())
        return None
    genre = band_genre_match['Genre'].iloc[0]
    
    # Get the corresponding Band Name for price lookups
    band_name_for_price = band_genre_match['Band Name'].iloc[0] if 'Band Name' in band_genre_match.columns else band_name
    
    # Debug: Show pricing data for this band
    st.write(f"Looking up prices for band: {band_name_for_price}")
    
    # Filter price data for this band, also checking for band name with "(MH)" suffix
    band_with_mh = f"{band_name_for_price} (MH)"
    band_prices = price_df[(price_df['Band Name'] == band_name_for_price) | (price_df['Band Name'] == band_with_mh)]
    
    if band_prices.empty:
        st.warning(f"No price data found for band: {band_name_for_price}")
        st.write("Available bands in price data:")
        st.write(price_df['Band Name'].unique())
    else:
        st.success(f"Found {len(band_prices)} price entries for {band_name_for_price}")
    
    # Extract show dates and cities from column headers
    show_columns = [col for col in inventory_df.columns if '-' in col]
    shows = []
    
    for col in show_columns:
        try:
            # Parse "City - MM/DD/YY ($7.00/head)" format
            parts = col.split(' - ')
            if len(parts) < 2:
                st.warning(f"Column '{col}' doesn't match expected format 'City - MM/DD/YY'")
                continue
                
            city = parts[0].strip()
            date_part = parts[1].split(' ')[0]  # Get just the date part before the price
            
            # Try to extract price if it's in the format
            price = None
            if '($' in col:
                try:
                    price_part = col.split('($')[1].split('/')[0]
                    price = float(price_part.replace('$', ''))
                except (ValueError, IndexError) as e:
                    price = None
            
            # Convert date to desired format
            try:
                date_obj = datetime.strptime(date_part, '%m/%d/%y')
                date_str = date_obj.strftime('%-m/%-d/%Y')
                
                shows.append({
                    'city': city,
                    'date': date_str,
                    'price': price
                })
            except Exception as e:
                st.error(f"Error parsing date '{date_part}': {str(e)}")
            
        except Exception as e:
            st.error(f"Error processing column '{col}': {str(e)}")
            continue
    
    if not shows:
        st.error("No valid show dates found in inventory file")
        return None
    
    # Create output rows
    output_rows = []
    
    for _, row in inventory_df.iterrows():
        if pd.isna(row['Item Name']):  # Skip empty rows
            continue
            
        # Handle size
        size = row['Size'] if pd.notna(row['Size']) else 'ONE SIZE'
        
        # Only look up price by SKU - no fallbacks
        item_price = ''
        if not band_prices.empty and 'SKU' in row and pd.notna(row['SKU']):
            sku = row['SKU']
            sku_match = band_prices[band_prices['SKU'] == sku]
            
            # Log SKU lookup process for every 10th item to avoid too much output
            if _ % 10 == 0:  
                logging.debug(f"Looking up SKU: {sku}")
                
            if not sku_match.empty:
                item_price = sku_match['Price'].iloc[0]
                # Log successful matches for every 10th item
                if _ % 10 == 0:
                    logging.debug(f"Found price {item_price} for SKU {sku}")
            else:
                # Log failed matches for every item to understand the issue
                logging.debug(f"No price match found for SKU: {sku}")
        
        # For each show
        for show in shows:
            # Use the price from the SKU lookup - no fallbacks to show price
            show_price = item_price
            
            output_rows.append({
                'artistName': band_name,
                'Genre': genre,
                'showDate': show['date'],
                'venue name': '',
                'venue city': show['city'],
                'venue state': '',
                'attendance': 0,
                'product size': size,
                'productType': row['Product Type'],
                'product price': show_price if show_price != '' else np.nan,
                'Item Name': row['Item Name']
            })

    # Create output DataFrame
    output_df = pd.DataFrame(output_rows)
    return output_df

def update_venue_details(output_df, tour_df, band_name, band_name_for_lookup):
    # Check for both exact band name and band name with "(MH)" suffix
    band_with_mh = f"{band_name_for_lookup} (MH)"
    band_shows = tour_df[(tour_df['Band'] == band_name_for_lookup) | (tour_df['Band'] == band_with_mh)]
    
    # Create lookup dictionary from tour data with flexible city matching
    venue_lookup = {}
    for _, row in band_shows.iterrows():
        if pd.notna(row['City']):
            # Handle cases where city includes state or other text
            city = row['City'].strip()
            
            # Handle NaN values with proper conversion
            attendance = 0
            if pd.notna(row['Attn']):
                attendance = row['Attn']
            
            # Store city name in lowercase for case-insensitive matching
            venue_lookup[city.lower()] = {
                'venue': row['Venue'] if pd.notna(row['Venue']) else '',
                'state': row['ST'] if pd.notna(row['ST']) else '',
                'attendance': attendance  # Use the safely converted attendance
            }
            
            # Also store shortened versions (before commas or spaces) for better matching
            if ',' in city:
                short_city = city.split(',')[0].strip()
                venue_lookup[short_city.lower()] = venue_lookup[city.lower()]
            if ' ' in city:
                first_word = city.split(' ')[0].strip()
                # Only use first word if it's reasonably long (avoid matching on "San", etc.)
                if len(first_word) > 3:
                    venue_lookup[first_word.lower()] = venue_lookup[city.lower()]
    
    # Add a fallback for "Indianapolis, IN" style city names
    for city_key in list(venue_lookup.keys()):
        if ',' not in city_key:
            continue
        base_city = city_key.split(',')[0].strip()
        if base_city not in venue_lookup:
            venue_lookup[base_city] = venue_lookup[city_key]
    
    # Update the output dataframe with venue details - using correct column names
    for i, row in output_df.iterrows():
        # Use 'venue city' instead of 'City'
        if 'venue city' not in row or pd.isna(row['venue city']):
            continue
            
        city = row['venue city'].lower()
        
        # Try direct match first
        if city in venue_lookup:
            output_df.at[i, 'venue name'] = venue_lookup[city]['venue']
            output_df.at[i, 'venue state'] = venue_lookup[city]['state']
            output_df.at[i, 'attendance'] = venue_lookup[city]['attendance']
        else:
            # Try match with only the part before a comma
            if ',' in city:
                base_city = city.split(',')[0].strip().lower()
                if base_city in venue_lookup:
                    output_df.at[i, 'venue name'] = venue_lookup[base_city]['venue']
                    output_df.at[i, 'venue state'] = venue_lookup[base_city]['state']
                    output_df.at[i, 'attendance'] = venue_lookup[base_city]['attendance']
            
            # Try partial match on any city
            else:
                matched = False
                for venue_city, details in venue_lookup.items():
                    if city in venue_city or venue_city in city:
                        output_df.at[i, 'venue name'] = details['venue']
                        output_df.at[i, 'venue state'] = details['state']
                        output_df.at[i, 'attendance'] = details['attendance']
                        matched = True
                        break
                
                if not matched:
                    st.warning(f"No venue match found for city: {row['venue city']}")
    
    return output_df

# Function to check API health
def check_api_health():
    try:
        response = requests.get(f"{API_BASE_URL}/health")
        if response.status_code == 200:
            health_data = response.json()
            return True, health_data
        else:
            return False, {"error": f"API returned status code {response.status_code}"}
    except Exception as e:
        return False, {"error": str(e)}

# Function to make size prediction API call
def predict_sales_by_size(data_df):
    try:
        # Create a copy of the dataframe to avoid modifying the original
        df_copy = data_df.copy()
        
        # Convert datetime columns to string format before JSON serialization
        if 'showDate' in df_copy.columns:
            df_copy['showDate'] = df_copy['showDate'].dt.strftime('%Y-%m-%d')
        
        # Replace NaN values with None for JSON serialization
        df_copy = df_copy.replace({np.nan: None})
        
        # Prepare the data for API - Convert DataFrame to dictionary list
        data_list = df_copy.to_dict(orient='records')
        
        # Make the API call
        response = requests.post(
            f"{API_BASE_URL}/predict/size",
            json={"data": data_list}
        )
        
        if response.status_code == 200:
            result = response.json()
            # Convert predictions back to DataFrame
            predictions_df = pd.DataFrame(result["predictions"])
            return True, predictions_df
        else:
            return False, {"error": f"API returned status code {response.status_code}: {response.text}"}
    except Exception as e:
        return False, {"error": str(e)}

# Function to make per head prediction API call
def predict_per_head(data_df):
    try:
        # Create a copy of the dataframe to avoid modifying the original
        df_copy = data_df.copy()
        
        # Convert datetime columns to string format before JSON serialization
        if 'showDate' in df_copy.columns:
            df_copy['showDate'] = df_copy['showDate'].dt.strftime('%Y-%m-%d')
        
        # Replace NaN values with None for JSON serialization
        df_copy = df_copy.replace({np.nan: None})
        
        # Prepare the data for API - Convert DataFrame to dictionary list
        data_list = df_copy.to_dict(orient='records')
        
        # Make the API call
        response = requests.post(
            f"{API_BASE_URL}/predict/perhead",
            json={"data": data_list}
        )
        
        if response.status_code == 200:
            result = response.json()
            # Convert predictions back to DataFrame
            predictions_df = pd.DataFrame(result["predictions"])
            return True, predictions_df
        else:
            return False, {"error": f"API returned status code {response.status_code}: {response.text}"}
    except Exception as e:
        return False, {"error": str(e)}

# Function to load static data for file formatting
@st.cache_data
def load_static_data():
    # Set the data directory
    DATA_DIR = Path(".")  # Current directory where app.py and CSV files are located
    
    # Load genre mapping
    try:
        genre_df = pd.read_csv(DATA_DIR / "band_genre_map.csv")
        st.success("Successfully loaded genre mapping data ✅")
    except Exception as e:
        st.error(f"Error loading genre mapping data: {str(e)}")
        genre_df = pd.DataFrame(columns=['MH band', 'Genre', 'Band Name'])
    
    # Load tour data from external URL
    try:
        tour_data_url = "https://atvenu-forecast.votintsev.com/tour_data.csv"
        response = requests.get(tour_data_url)
        response.raise_for_status()  # Raise an exception for HTTP errors
        
        # Define the column names for the CSV without headers
        column_names = [
            'Band', 'Show Date', 'City', 'State', 'Venue', 'Nights', 'Type', 
            'Capacity', 'Attn', 'PPH', 'Col10', 'Merch', 'Col12', 'Expenses', 
            'Col14', 'Net', 'Col16'
        ]
        
        # Parse the CSV data with explicit column names and handling for no header
        tour_df = pd.read_csv(
            StringIO(response.text),
            sep=',',
            header=None,  # No header in the file
            names=column_names,  # Use our defined column names
            engine='python',  # More flexible parsing engine
            on_bad_lines='warn'  # Log warnings for problematic lines but don't fail
        )
        
        # Convert numeric columns to appropriate types
        numeric_columns = ['Capacity', 'Attn']
        for col in numeric_columns:
            tour_df[col] = pd.to_numeric(tour_df[col], errors='coerce')
        
        # In case the file actually has headers, check if the first row looks like headers
        if isinstance(tour_df['Band'].iloc[0], str) and tour_df['Band'].iloc[0] == 'Band':
            tour_df = tour_df.iloc[1:].reset_index(drop=True)
        
        # Map 'State' to 'ST' for compatibility
        tour_df['ST'] = tour_df['State']
        
        st.success("Successfully loaded tour data from external source ✅")
    except Exception as e:
        st.error(f"Error loading tour data from URL: {str(e)}. Please check the URL or file format.")
        # Initialize an empty DataFrame with required columns
        tour_df = pd.DataFrame(columns=['Band', 'Show Date', 'City', 'ST', 'Venue', 'Nights', 'Type', 'Capacity', 'Attn'])
    
    # Load product pricing data
    try:
        price_df = pd.read_csv(DATA_DIR / "band_sku_price_data.csv")
        st.success("Successfully loaded product pricing data ✅")
    except Exception as e:
        st.error(f"Error loading product pricing data: {str(e)}")
        price_df = pd.DataFrame(columns=['Band Name', 'SKU', 'Price'])
    
    return genre_df, tour_df, price_df

# Function to display the File Formatting page
def show_file_formatting_page():
    st.header("File Formatting")
    
    # Load static data for file formatting
    genre_df, tour_df, price_df = load_static_data()
    
    # Band selection dropdown - using the predefined list
    selected_band = st.selectbox("Select Band", INCLUDED_BANDS)
    
    # Get the corresponding Band Name for additional lookups
    selected_band_info = genre_df[genre_df['MH band'] == selected_band]
    band_name_for_lookup = ""
    if len(selected_band_info) > 0 and 'Band Name' in selected_band_info.columns:
        band_name_for_lookup = selected_band_info['Band Name'].iloc[0]
    else:
        band_name_for_lookup = selected_band
    
    # File uploader - accepts both CSV and Excel files
    uploaded_file = st.file_uploader("Upload inventory file", type=['csv', 'xlsx', 'xls'])
    
    if uploaded_file is not None:
        # Process file and show results
        st.info("File uploaded. Processing...")
        
        # Read the file based on its type
        file_type = uploaded_file.name.split('.')[-1].lower()
        
        try:
            if file_type == 'csv':
                inventory_df = pd.read_csv(uploaded_file)
            else:  # xlsx or xls
                try:
                    # Check if openpyxl is available
                    import importlib
                    importlib.import_module('openpyxl')
                    inventory_df = pd.read_excel(uploaded_file)
                except ImportError:
                    st.error("Missing required dependency 'openpyxl' for reading Excel files.")
                    st.info("Please install it using: pip install openpyxl")
                    st.warning("You can still use CSV files. Please convert your Excel file to CSV and upload again.")
                    st.stop()

            # Process inventory file
            output_df = process_inventory_file(inventory_df, selected_band, genre_df, price_df)
            
            if output_df is not None:
                # Update venue details
                final_df = update_venue_details(output_df, tour_df, selected_band, band_name_for_lookup)
                
                # Ensure product price is numeric for display
                if 'product price' in final_df.columns:
                    final_df['product price'] = pd.to_numeric(final_df['product price'], errors='coerce')
                
                # Add toggle to hide rows with missing data
                show_all_data = st.checkbox("Show all data (including rows with missing attendance or price)", value=False)
                
                # Filter the data if the toggle is off
                display_df = final_df
                if not show_all_data:
                    # First, check if both columns actually exist in the dataframe
                    has_attendance = 'attendance' in final_df.columns
                    has_price = 'product price' in final_df.columns
                    
                    if has_attendance and has_price:
                        # Convert columns to numeric to handle any string values
                        final_df['attendance'] = pd.to_numeric(final_df['attendance'], errors='coerce')
                        final_df['product price'] = pd.to_numeric(final_df['product price'], errors='coerce')
                        
                        # Filter out rows with missing attendance OR price (using AND for the filter)
                        display_df = final_df[(final_df['attendance'].notna() & (final_df['attendance'] > 0)) & 
                                             (final_df['product price'].notna() & (final_df['product price'] > 0))]
                    else:
                        st.warning(f"Missing required columns. Has attendance column: {has_attendance}, Has price column: {has_price}")
                        display_df = final_df  # Show all data if columns are missing
                        
                    st.write(f"Showing {len(display_df)} rows with both attendance and price data (filtered from {len(final_df)} total rows)")
                
                # Display results
                st.write("Processed Data:")
                st.dataframe(display_df)
                
                # Add option to continue to prediction
                st.success("Data formatting complete! You can download the formatted data or continue to prediction. ✅")
                
                col1, col2 = st.columns(2)
                
                # Download button
                with col1:
                    csv = final_df.to_csv(index=False)
                    st.download_button(
                        label="Download formatted data",
                        data=csv,
                        file_name=f'{selected_band}_formatted_data.csv',
                        mime='text/csv'
                    )
                
                # Go to Prediction button
                with col2:
                    if st.button("Continue to Prediction"):
                        # Store the dataframe in session state to use in prediction page
                        st.session_state.formatted_data = final_df
                        st.session_state.page = "Prediction"
                        # Force rerun to switch page
                        st.experimental_rerun()
        except Exception as e:
            st.error(f"Error processing file: {str(e)}")
            st.info("Please check the file format and try again.")
            logging.error(f"Error processing file: {str(e)}")

# Function to display the Prediction page
def show_prediction_page():
    st.header("Merchandise Sales Prediction")
    
    # Check API health
    api_healthy, health_data = check_api_health()
    
    if not api_healthy:
        st.error(f"API is not available. Error: {health_data.get('error', 'Unknown error')}")
        st.warning("You can still proceed with file upload, but predictions will not work until the API is available.")
    else:
        st.success("API is available ✅")
        # Display available prediction methods based on API health
        available_methods = []
        if health_data.get("models", {}).get("size_model", False):
            available_methods.append("Sales Quantity By Size")
        if health_data.get("models", {}).get("per_head_model", False):
            available_methods.append("Per Head Revenue")
        
        if not available_methods:
            st.warning("No prediction methods are currently available from the API.")
            return
    
    # Select prediction type
    prediction_type = st.radio("Select Prediction Type", ["Sales Quantity By Size", "Per Head Revenue"])
    
    # Check if we have data from the File Formatting page
    formatted_data = None
    if 'formatted_data' in st.session_state:
        formatted_data = st.session_state.formatted_data
        st.success("Using data from File Formatting page ✅")
    
    # File uploader
    uploaded_file = st.file_uploader("Choose a CSV file for prediction", type="csv")
    
    # Process file or use formatted data
    if uploaded_file is not None or formatted_data is not None:
        try:
            # Get data from either source
            if uploaded_file is not None:
                df = pd.read_csv(uploaded_file, encoding='utf-8-sig')
                logging.info("CSV file read successfully for prediction")
            else:
                df = formatted_data
                logging.info("Using data from File Formatting page for prediction")
            
            # Show raw data
            st.subheader("Input Data for Prediction")
            st.dataframe(df.head())
            
            if not api_healthy:
                st.error("Cannot make predictions because the API is not available.")
                return
            
            if prediction_type == "Sales Quantity By Size":
                # Process Data for Size prediction
                with st.spinner("Processing data and making Sales by Size predictions..."):
                    # Prepare DataFrame for prediction
                    # Convert 'showDate' to datetime format if needed
                    if isinstance(df['showDate'].iloc[0], str):
                        # Try more flexible date parsing to handle different formats (2-digit or 4-digit years)
                        try:
                            df['showDate'] = pd.to_datetime(df['showDate'], format='%m/%d/%y')
                        except ValueError:
                            try:
                                df['showDate'] = pd.to_datetime(df['showDate'], format='%m/%d/%Y')
                            except ValueError:
                                # If specific formats fail, use the more flexible parser
                                df['showDate'] = pd.to_datetime(df['showDate'], dayfirst=False, errors='coerce')
                    
                    # Make API call for predictions
                    success, result = predict_sales_by_size(df)
                    
                    if success:
                        output_df = result
                        st.success("Predictions completed successfully! ✅")
                    else:
                        st.error(f"Error making predictions: {result.get('error', 'Unknown error')}")
                        return
                
                # Display results
                st.subheader("Sales Quantity By Size Prediction Results")
                st.dataframe(output_df)
                
                # Create download button
                csv = output_df.to_csv(index=False)
                timestamp = dt.datetime.now().strftime("%m_%d_%Y-%I_%M_%S_%p")
                st.download_button(
                    label="Download Predictions as CSV",
                    data=csv,
                    file_name=f"predicted_sales_by_size_{timestamp}.csv",
                    mime="text/csv"
                )
                logging.info(f"CSV download button created")
                
                # Add summary statistics
                st.subheader("Summary Statistics")
                total_sales = output_df['predicted_sales_quantity'].sum()
                avg_sales_per_product = output_df.groupby('Item Name')['predicted_sales_quantity'].mean().mean()
                
                summary_stats = pd.DataFrame({
                    'Total Predicted Sales': [total_sales],
                    'Average Sales Per Product': [round(avg_sales_per_product, 2)],
                    'Product Types': [output_df['productType'].nunique()],
                    'Shows': [output_df['showDate'].nunique()]
                })
                st.dataframe(summary_stats)
                
            else:  # Per Head Revenue prediction
                # Process data for Per Head prediction
                with st.spinner("Processing data and making Per Head Revenue predictions..."):
                    # Prepare DataFrame for prediction
                    # Convert 'showDate' to datetime format if needed
                    if isinstance(df['showDate'].iloc[0], str):
                        # Try more flexible date parsing to handle different formats (2-digit or 4-digit years)
                        try:
                            df['showDate'] = pd.to_datetime(df['showDate'], format='%m/%d/%y')
                        except ValueError:
                            try:
                                df['showDate'] = pd.to_datetime(df['showDate'], format='%m/%d/%Y')
                            except ValueError:
                                # If specific formats fail, use the more flexible parser
                                df['showDate'] = pd.to_datetime(df['showDate'], dayfirst=False, errors='coerce')
                    
                    # Make API call for predictions
                    success, result = predict_per_head(df)
                    
                    if success:
                        output_df = result
                        st.success("Predictions completed successfully! ✅")
                    else:
                        st.error(f"Error making predictions: {result.get('error', 'Unknown error')}")
                        return
                
                # Display results
                st.subheader("Per Head Revenue Prediction Results")
                st.dataframe(output_df)
                
                # Create download button
                csv = output_df.to_csv(index=False)
                timestamp = dt.datetime.now().strftime("%m_%d_%Y-%I_%M_%S_%p")
                st.download_button(
                    label="Download Predictions as CSV",
                    data=csv,
                    file_name=f"predicted_per_head_revenue_{timestamp}.csv",
                    mime="text/csv"
                )
                logging.info(f"CSV download button created")
                
                # Show a summary of the predictions
                st.subheader("Summary Statistics")
                summary_stats = pd.DataFrame({
                    'Average Predicted $ Per Head': [output_df['predicted_$_per_head'].mean()],
                    'Median Predicted $ Per Head': [output_df['predicted_$_per_head'].median()],
                    'Min Predicted $ Per Head': [output_df['predicted_$_per_head'].min()],
                    'Max Predicted $ Per Head': [output_df['predicted_$_per_head'].max()],
                    'Venues': [output_df['venue name'].nunique()],
                    'Shows': [output_df['showDate'].nunique()]
                })
                st.dataframe(summary_stats)
            
        except Exception as e:
            st.error(f"An error occurred during prediction: {e}")
            logging.error(f"Error during prediction process: {e}")
            st.info("Please make sure your file has the required columns for the selected prediction type.")
    
    else:
        st.info("Please upload a CSV file or complete the File Formatting step first")

# Function to display the About page
def show_about_page():
    st.header("About the Merchandise Prediction Platform")
    
    st.markdown("""
    ## Overview ✅
    This application helps predict merchandise sales for concerts and events. It provides two key predictions:
    
    1. **Sales Quantity By Size** - Predicts how many items of each product size will sell at an event
    2. **Per Head Revenue** - Predicts the expected merchandise revenue per attendee
    
    ## How to Use ✅
    1. Start with the File Formatting page to convert your inventory files into the right format
    2. Go to the Prediction page to generate sales predictions
    3. Download your results for analysis and planning
    
    ## Data Requirements ✅
    For the most accurate predictions, please ensure your input data includes:
    - Artist name and genre
    - Show date and venue details
    - Product types and sizes
    - Expected attendance (when available)
    - Product pricing
    
    ## API Integration ✅
    This frontend application connects to the prediction API at:
    `https://fast-api-data-master-eugene59.replit.app/`
    
    The API provides the machine learning models that power the predictions.
    """)
    
    # Check API status and show it
    api_healthy, health_data = check_api_health()
    
    if api_healthy:
        st.success("API is currently available and healthy ✅")
        
        # Show model status
        st.subheader("API Status")
        models_status = health_data.get("models", {})
        
        status_df = pd.DataFrame({
            "Model": list(models_status.keys()),
            "Available": list(models_status.values())
        })
        
        st.dataframe(status_df)
    else:
        st.error(f"API is currently unavailable. Error: {health_data.get('error', 'Unknown error')}")

# Set page title and header
st.set_page_config(page_title="Merchandise Prediction Platform", layout="wide")
st.title("Merchandise Prediction Platform")

# Create sidebar navigation
st.sidebar.header("Navigation")

# Initialize session state for page if not exists
if 'page' not in st.session_state:
    st.session_state.page = "File Formatting"

# Page selection in sidebar
page = st.sidebar.radio("Go to", ["File Formatting", "Prediction", "About"], index=["File Formatting", "Prediction", "About"].index(st.session_state.page))

# Update session state
st.session_state.page = page

# Display the selected page
if page == "File Formatting":
    show_file_formatting_page()
elif page == "Prediction":
    show_prediction_page()
else:  # About page
    show_about_page()

# Function to clean up temporary files
def cleanup_temp_files():
    try:
        # Remove old log files
        log_files = list(Path(log_dir).glob('log_predict_merch_app_*.log'))
        for log_file in log_files[:-5]:  # Keep the 5 most recent logs
            log_file.unlink()
        logging.info(f"Cleaned up old log files")
    except Exception as e:
        logging.error(f"Error cleaning up temporary files: {e}")

# Call cleanup periodically
import atexit
atexit.register(cleanup_temp_files)
