import pandas as pd
import streamlit as st
from datetime import datetime
import requests
from io import StringIO

# Load the static data files
@st.cache_data
def load_static_data():
    # Load genre mapping
    genre_df = pd.read_csv("band_genre_map.csv")
    
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
        
        st.success("Successfully loaded tour data from external source")
    except Exception as e:
        st.error(f"Error loading tour data from URL: {str(e)}. Please check the URL or file format.")
        # Initialize an empty DataFrame with required columns
        tour_df = pd.DataFrame(columns=['Band', 'Show Date', 'City', 'ST', 'Venue', 'Nights', 'Type', 'Capacity', 'Attn'])
    
    # Load product pricing data
    try:
        price_df = pd.read_csv("band_sku_price_data.csv")
        st.success("Successfully loaded product pricing data")
    except Exception as e:
        st.error(f"Error loading product pricing data: {str(e)}")
        price_df = pd.DataFrame(columns=['Band Name', 'SKU', 'Price'])
    
    return genre_df, tour_df, price_df

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
    
    # Extract show dates and cities from column headers
    show_columns = [col for col in inventory_df.columns if '-' in col]
    shows = []
    
    st.write("Processing inventory shows:")
    for col in show_columns:
        try:
            # Parse "City - MM/DD/YY ($7.00/head)" format
            parts = col.split(' - ')
            if len(parts) < 2:
                st.warning(f"Column '{col}' doesn't match expected format 'City - MM/DD/YY'")
                continue
                
            city = parts[0].strip()
            date_part = parts[1].split(' ')[0]  # Get just the date part before the price
            
            # Convert date to desired format
            date_obj = datetime.strptime(date_part, '%m/%d/%y')
            date_str = date_obj.strftime('%-m/%-d/%Y')
            
            shows.append({
                'city': city,
                'date': date_str
            })
            st.write(f"Successfully processed - City: {city}, Date: {date_str}")
            
        except Exception as e:
            st.error(f"Error processing column '{col}': {str(e)}")
            continue
    
    if not shows:
        st.error("No valid show dates found in inventory file")
        return None
    
    # Create output rows
    output_rows = []
    
    # Filter price data for this band, also checking for band name with "(MH)" suffix
    band_with_mh = f"{band_name} (MH)"
    band_prices = price_df[(price_df['Band Name'] == band_name_for_price) | (price_df['Band Name'] == band_with_mh)]
    
    for _, row in inventory_df.iterrows():
        if pd.isna(row['Item Name']):  # Skip empty rows
            continue
            
        # Handle size
        size = row['Size'] if pd.notna(row['Size']) else 'ONE SIZE'
        
        # Try to find price for this item
        item_price = ''
        if not band_prices.empty:
            # Try to match by SKU if available
            if 'SKU' in row and pd.notna(row['SKU']):
                sku_match = band_prices[band_prices['SKU'] == row['SKU']]
                if not sku_match.empty:
                    item_price = sku_match['Price'].iloc[0]
            
            # If no price found by SKU, try to find by item name and size
            if item_price == '' and 'Item Name' in row:
                # This is a simplified approach - in reality, you might need more complex matching logic
                for _, price_row in band_prices.iterrows():
                    if pd.notna(price_row['SKU']) and row['Item Name'] in price_row['SKU'] and size in price_row['SKU']:
                        item_price = price_row['Price']
                        break
        
        # For each show
        for show in shows:
            output_rows.append({
                'artistName': band_name_for_price,
                'Genre': genre,
                'showDate': show['date'],
                'venue name': '',
                'venue city': show['city'],
                'venue state': '',
                'attendance': 0,
                'product size': size,
                'productType': row['Product Type'],
                'product price': item_price,
                'Item Name': row['Item Name']
            })

    # Create output DataFrame
    output_df = pd.DataFrame(output_rows)
    return output_df

def update_venue_details(output_df, tour_df, band_name, band_name_for_lookup):
    st.write("Updating venue details...")
    
    # Check for both exact band name and band name with "(MH)" suffix
    band_with_mh = f"{band_name_for_lookup} (MH)"
    band_shows = tour_df[(tour_df['Band'] == band_name_for_lookup) | (tour_df['Band'] == band_with_mh)]
    
    st.write(f"Found {len(band_shows)} {band_name_for_lookup} shows")
    
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
    
    st.write("Venue lookup created for cities:")
    st.write(venue_lookup)
    
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

def main():
    st.title("Product Inventory Processor")
    
    # Load static data
    genre_df, tour_df, price_df = load_static_data()
    
    # Get list of bands for dropdown
    bands = sorted(genre_df['MH band'].unique())
    
    # Band selection dropdown
    selected_band = st.selectbox("Select Band", bands)
    
    # Get the corresponding Band Name for additional lookups
    selected_band_info = genre_df[genre_df['MH band'] == selected_band]
    band_name_for_lookup = ""
    if len(selected_band_info) > 0 and 'Band Name' in selected_band_info.columns:
        band_name_for_lookup = selected_band_info['Band Name'].iloc[0]
    else:
        band_name_for_lookup = selected_band
    
    # File uploader - now accepts both CSV and Excel files
    uploaded_file = st.file_uploader("Upload inventory file", type=['csv', 'xlsx', 'xls'])
    
    if uploaded_file is not None:
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
                    return
            
            # Auto-process when file is uploaded
            output_df = process_inventory_file(inventory_df, selected_band, genre_df, price_df)
            
            if output_df is not None:
                # Update venue details
                final_df = update_venue_details(output_df, tour_df, selected_band, band_name_for_lookup)
                
                # Add toggle to hide rows with missing data
                show_all_data = st.checkbox("Show all data (including rows with missing attendance or price)", value=True)
                
                # Filter the data if the toggle is off
                display_df = final_df
                if not show_all_data:
                    # Add debug information to check the columns and data
                    st.write("Columns in dataframe:", final_df.columns.tolist())
                    
                    # First, check if both columns actually exist in the dataframe
                    has_attendance = 'attendance' in final_df.columns
                    has_price = 'product price' in final_df.columns
                    
                    if has_attendance and has_price:
                        # Convert columns to numeric to handle any string values
                        final_df['attendance'] = pd.to_numeric(final_df['attendance'], errors='coerce')
                        final_df['product price'] = pd.to_numeric(final_df['product price'], errors='coerce')
                        
                        # Show counts of non-null values to help diagnose the issue
                        st.write(f"Rows with attendance data: {final_df['attendance'].notna().sum()}")
                        st.write(f"Rows with product price data: {final_df['product price'].notna().sum()}")
                        
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
                
                # Download button
                csv = final_df.to_csv(index=False)  # Always download the full dataset
                st.download_button(
                    label="Download processed data",
                    data=csv,
                    file_name=f'{selected_band}_for_upcoming_shows.csv',
                    mime='text/csv'
                )
        
        except Exception as e:
            st.error(f"Error processing file: {str(e)}")
            st.info("Please check the file format and try again.")

if __name__ == "__main__":
    main()
