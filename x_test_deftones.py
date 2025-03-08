import pandas as pd
from datetime import datetime

def extract_city_names(csv_path):
    """
    Extract city names from column headings in the CSV file
    """
    # Load the CSV file
    df = pd.read_csv(csv_path)
    
    # Extract show columns (ones with a dash)
    show_columns = [col for col in df.columns if ' - ' in col]
    
    # Extract city names from the show columns
    cities = []
    for col in show_columns:
        try:
            # Parse "City - MM/DD/YY ($7.00/head)" format
            parts = col.split(' - ')
            if len(parts) < 2:
                print(f"Column '{col}' doesn't match expected format 'City - MM/DD/YY'")
                continue
                
            city = parts[0].strip()
            date_part = parts[1].split(' ')[0]  # Get just the date part before the price
            
            # Get price per head if available
            price_per_head = None
            if '($' in col:
                price_part = col.split('($')[1].split('/head)')[0]
                price_per_head = price_part
            
            # Convert date to desired format for display
            date_obj = datetime.strptime(date_part, '%m/%d/%y')
            date_str = date_obj.strftime('%m/%d/%Y')
            
            cities.append({
                'city': city,
                'date': date_str,
                'price_per_head': price_per_head,
                'original_column': col
            })
            
        except Exception as e:
            print(f"Error processing column '{col}': {str(e)}")
            continue
    
    return cities

def get_attendance_data(cities, tour_data_path):
    """
    Get attendance data for each city from the tour data CSV
    """
    # Load the tour data with explicit column names
    column_names = [
        'Band', 'Show Date', 'City', 'State', 'Venue', 'Nights', 'Type', 
        'Capacity', 'Attn', 'PPH', 'Col10', 'Merch', 'Col12', 'Expenses', 
        'Col14', 'Net', 'Col16'
    ]
    
    tour_df = pd.read_csv(tour_data_path, header=None, names=column_names)
    
    # Convert numeric columns to appropriate types
    numeric_columns = ['Capacity', 'Attn']
    for col in numeric_columns:
        tour_df[col] = pd.to_numeric(tour_df[col], errors='coerce')
    
    # Filter for Deftones shows
    deftones_shows = tour_df[tour_df['Band'] == 'Deftones (MH)']
    
    print(f"Found {len(deftones_shows)} Deftones shows in tour data.")
    
    # Create a list to store attendance data
    attendance_data = []
    
    # For each city, find matching attendance
    for city_info in cities:
        city = city_info['city']
        date = city_info['date']
        price_per_head = city_info['price_per_head']
        
        # Find matching rows (case insensitive)
        matches = deftones_shows[deftones_shows['City'].str.lower() == city.lower()]
        
        if not matches.empty:
            # Get the attendance value
            attendance = matches['Attn'].iloc[0]
            venue = matches['Venue'].iloc[0] if 'Venue' in matches.columns else 'N/A'
            capacity = matches['Capacity'].iloc[0] if 'Capacity' in matches.columns else 0
            
            # Check for NaN values
            attendance = 0 if pd.isna(attendance) else attendance
            capacity = 0 if pd.isna(capacity) else capacity
            
            # Calculate utilization if capacity is available
            utilization = 0
            if capacity > 0:
                utilization = (float(attendance) / float(capacity)) * 100
            
            attendance_data.append({
                'city': city,
                'date': date,
                'attendance': attendance,
                'venue': venue,
                'capacity': capacity,
                'utilization': utilization,
                'price_per_head': price_per_head
            })
        else:
            # Handle cases like 'Indianapolis, IN' where the city column might contain the state
            city_base = city.split(',')[0]
            alternative_matches = deftones_shows[deftones_shows['City'].str.contains(city_base, case=False, na=False)]
            
            if not alternative_matches.empty:
                attendance = alternative_matches['Attn'].iloc[0]
                venue = alternative_matches['Venue'].iloc[0] if 'Venue' in alternative_matches.columns else 'N/A'
                capacity = alternative_matches['Capacity'].iloc[0] if 'Capacity' in alternative_matches.columns else 0
                
                # Check for NaN values
                attendance = 0 if pd.isna(attendance) else attendance
                capacity = 0 if pd.isna(capacity) else capacity
                
                # Calculate utilization if capacity is available
                utilization = 0
                if capacity > 0:
                    utilization = (float(attendance) / float(capacity)) * 100
                
                attendance_data.append({
                    'city': city,
                    'date': date,
                    'attendance': attendance,
                    'venue': venue,
                    'capacity': capacity,
                    'utilization': utilization,
                    'price_per_head': price_per_head
                })
            else:
                attendance_data.append({
                    'city': city,
                    'date': date,
                    'attendance': 'Not found',
                    'venue': 'Not found',
                    'capacity': 'N/A',
                    'utilization': 'N/A',
                    'price_per_head': price_per_head
                })
    
    return attendance_data

def main():
    # File paths
    inventory_path = '/Users/eugeneleychenko/Downloads/atVenu-Forcasting/Brady Project/Tour-Forecast-Products-deftones-mh-us-2025.csv'
    tour_data_path = 'tour_data.csv'
    
    # Extract city names from inventory file
    print("Extracting city names from inventory file...")
    cities = extract_city_names(inventory_path)
    
    print("\nFound the following cities:")
    for city_info in cities:
        price_info = f" (${city_info['price_per_head']})" if city_info['price_per_head'] else ""
        print(f"- {city_info['city']} ({city_info['date']}){price_info}")
    
    # Get attendance data
    print("\nLooking up attendance data...")
    attendance_data = get_attendance_data(cities, tour_data_path)
    
    # Calculate total attendance and average attendance
    total_attendance = 0
    valid_shows = 0
    
    for data in attendance_data:
        if data['attendance'] != 'Not found':
            total_attendance += int(data['attendance'])
            valid_shows += 1
    
    avg_attendance = total_attendance / valid_shows if valid_shows > 0 else 0
    
    print(f"\nTotal attendance across all shows: {total_attendance}")
    print(f"Average attendance per show: {avg_attendance:.2f}")
    
    print("\nDetailed attendance data for Deftones shows:")
    print(f"{'City':<20} {'Date':<12} {'Attendance':<15} {'Capacity':<15} {'Util %':<10} {'PPH':<10} {'Venue':<25}")
    print("-" * 100)
    
    for data in attendance_data:
        city = data['city']
        date = data['date']
        attendance = data['attendance']
        venue = data['venue']
        capacity = data['capacity']
        price_per_head = data['price_per_head'] if data['price_per_head'] else 'N/A'
        
        # Format utilization as percentage
        if data['utilization'] != 'N/A':
            utilization = f"{data['utilization']:.1f}%"
        else:
            utilization = 'N/A'
        
        print(f"{city:<20} {date:<12} {attendance:<15} {capacity:<15} {utilization:<10} ${price_per_head:<8} {venue:<25}")

if __name__ == "__main__":
    main()
