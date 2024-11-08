import pandas as pd
from datetime import datetime

def process_inventory_file(inventory_path, tour_data_path, genre_df):
    # Get base filename for output
    base_filename = inventory_path.split('/')[-1].split('.')[0]
    
    # Read input files
    inventory_df = pd.read_csv(inventory_path)
    
    # Get band name from filename
    band_name = ' '.join([word.capitalize() for word in base_filename.split('_')])
    
    # Get genre for the band
    genre = genre_df[genre_df['Band Name'] == band_name]['Genre'].iloc[0]
    
    # Extract show dates and cities from column headers
    show_columns = [col for col in inventory_df.columns if '-' in col]
    shows = []
    
    print("\nProcessing inventory shows:")
    for col in show_columns:
        # Parse "City - MM/DD/YY ($7.00/head)" format
        parts = col.split(' - ')
        city = parts[0].strip()
        date = parts[1].split(' ')[0]
        
        # Convert date to desired format
        date_obj = datetime.strptime(date, '%m/%d/%y')
        date_str = date_obj.strftime('%-m/%-d/%Y')
        
        shows.append({
            'city': city,
            'date': date_str
        })
        print(f"City: {city}, Date: {date_str}")

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
    
    # Generate output filename
    output_path = f'{base_filename}_for_upcoming_shows.csv'
    
    # Write to CSV
    output_df.to_csv(output_path, index=False)
    
    return output_path

def update_venue_details(output_path, tour_data_path):
    print("\nUpdating venue details...")
    
    # Read the files
    output_df = pd.read_csv(output_path)
    tour_df = pd.read_csv(tour_data_path, names=['Band', 'Show Date', 'City', 'ST', 'Venue', 'Nights', 'Type', 'Capacity', 'Attn'])
    
    # Filter for Air Supply shows
    air_supply_shows = tour_df[tour_df['Band'] == 'Air Supply']
    print(f"\nFound {len(air_supply_shows)} Air Supply shows")
    
    # Create lookup dictionary from tour data using just city
    venue_lookup = {}
    for _, row in air_supply_shows.iterrows():
        if pd.notna(row['City']):
            city = row['City'].strip()
            venue_lookup[city] = {
                'venue': row['Venue'] if pd.notna(row['Venue']) else '',
                'state': row['ST'] if pd.notna(row['ST']) else '',
                'attendance': row['Attn'] if pd.notna(row['Attn']) else 0
            }
    
    print("\nVenue lookup created for cities:")
    for city, details in venue_lookup.items():
        print(f"{city}: {details}")
    
    # Update venue details in output
    updates = 0
    for idx, row in output_df.iterrows():
        city = row['venue city']
        if city in venue_lookup:
            output_df.at[idx, 'venue name'] = venue_lookup[city]['venue']
            output_df.at[idx, 'venue state'] = venue_lookup[city]['state']
            output_df.at[idx, 'attendance'] = venue_lookup[city]['attendance']
            updates += 1
    
    # Write updated file
    output_df.to_csv(output_path, index=False)
    print(f"\nUpdated {updates} rows with venue details")

if __name__ == "__main__":
    # File paths
    inventory_path = "Air Supply.csv"  # Replace with your inventory file path
    tour_data_path = "tour_data.csv"  # Replace with your tour data file path
    genre_map_path = "band_genre_map.csv"  # Replace with your genre mapping file path
    
    try:
        # Read genre mapping
        genre_df = pd.read_csv(genre_map_path)
        
        # Process files
        output_path = process_inventory_file(inventory_path, tour_data_path, genre_df)
        update_venue_details(output_path, tour_data_path)
        
        print("\nProcessing completed successfully!")
        
    except Exception as e:
        print(f"\nAn error occurred: {str(e)}")
