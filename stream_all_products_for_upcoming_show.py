import pandas as pd
import streamlit as st
from datetime import datetime

# Load the static data files
@st.cache_data
def load_static_data():
    genre_df = pd.read_csv("band_genre_map.csv")
    tour_df = pd.read_csv("temp_tour.csv", names=['Band', 'Show Date', 'City', 'ST', 'Venue', 'Nights', 'Type', 'Capacity', 'Attn'])
    return genre_df, tour_df

def process_inventory_file(inventory_df, band_name, genre_df):
    # Get genre for the band - Add error handling
    band_genre_match = genre_df[genre_df['Band Name'] == band_name]
    if len(band_genre_match) == 0:
        st.error(f"No genre found for band: {band_name}")
        st.write("Available bands in genre mapping:")
        st.write(genre_df['Band Name'].tolist())
        return None
    genre = band_genre_match['Genre'].iloc[0]
    
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
    
    for _, row in inventory_df.iterrows():
        if pd.isna(row['Item Name']):  # Skip empty rows
            continue
            
        # Handle size
        size = row['Size'] if pd.notna(row['Size']) else 'ONE SIZE'
        
        # For each show
        for show in shows:
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
                'product price': '',
                'Item Name': row['Item Name']
            })

    # Create output DataFrame
    output_df = pd.DataFrame(output_rows)
    return output_df

def update_venue_details(output_df, tour_df, band_name):
    st.write("Updating venue details...")
    
    # Filter for selected band's shows
    band_shows = tour_df[tour_df['Band'] == band_name]
    st.write(f"Found {len(band_shows)} {band_name} shows")
    
    # Create lookup dictionary from tour data using just city
    venue_lookup = {}
    for _, row in band_shows.iterrows():
        if pd.notna(row['City']):
            city = row['City'].strip()
            venue_lookup[city] = {
                'venue': row['Venue'] if pd.notna(row['Venue']) else '',
                'state': row['ST'] if pd.notna(row['ST']) else '',
                'attendance': row['Attn'] if pd.notna(row['Attn']) else 0
            }
    
    st.write("Venue lookup created for cities:")
    st.write(venue_lookup)
    
    # Update venue details in output
    updates = 0
    for idx, row in output_df.iterrows():
        city = row['venue city']
        if city in venue_lookup:
            output_df.at[idx, 'venue name'] = venue_lookup[city]['venue']
            output_df.at[idx, 'venue state'] = venue_lookup[city]['state']
            output_df.at[idx, 'attendance'] = venue_lookup[city]['attendance']
            updates += 1
    
    st.write(f"Updated {updates} rows with venue details")
    return output_df

def main():
    st.title("Product Inventory Processor")
    
    # Load static data
    genre_df, tour_df = load_static_data()
    
    # Get list of bands for dropdown
    bands = sorted(genre_df['Band Name'].unique())
    
    # Band selection dropdown
    selected_band = st.selectbox("Select Band", bands)
    
    # File uploader - now accepts both CSV and Excel files
    uploaded_file = st.file_uploader("Upload inventory file", type=['csv', 'xlsx', 'xls'])
    
    if uploaded_file is not None:
        # Read the file based on its type
        file_type = uploaded_file.name.split('.')[-1].lower()
        if file_type == 'csv':
            inventory_df = pd.read_csv(uploaded_file)
        else:  # xlsx or xls
            inventory_df = pd.read_excel(uploaded_file)
        
        # Auto-process when file is uploaded
        output_df = process_inventory_file(inventory_df, selected_band, genre_df)
        
        if output_df is not None:
            # Update venue details
            final_df = update_venue_details(output_df, tour_df, selected_band)
            
            # Display results
            st.write("Processed Data:")
            st.dataframe(final_df)
            
            # Download button
            csv = final_df.to_csv(index=False)
            st.download_button(
                label="Download processed data",
                data=csv,
                file_name=f'{selected_band}_for_upcoming_shows.csv',
                mime='text/csv'
            )

if __name__ == "__main__":
    main()
