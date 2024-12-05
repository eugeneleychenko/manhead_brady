import streamlit as st
import requests
import pandas as pd
from io import StringIO
from datetime import datetime

st.set_page_config(page_title="Upcoming Shows Per Head", page_icon=":bar_chart:", layout="wide")
st.title('Upcoming Shows Per Head')

# Load the tour data
def load_tour_data():
    url = "https://atvenu-forecast.votintsev.com/tour_data.csv"
    headers = {'User-Agent': 'Mozilla/5.0'}
    response = requests.get(url, headers=headers)
    
    if response.status_code == 200:
        data = StringIO(response.text)
        column_names = ['Band', 'Show Date', 'City', 'ST', 'Venue', 'Nights', 'Type', 'Capacity', 'Attn', '$/Head', 'Blank1', 'Gross', "Blank2", 'Show Costs', "Blank3", 'Net Receipts', "Blank4"]
        df = pd.read_csv(data, delimiter=',', header=None, names=column_names, skiprows=1)
        df = df.drop(columns=['Blank1', 'Blank2', 'Blank3', 'Blank4'])
        return df
    else:
        raise Exception("Failed to download the tour data CSV file")

# Load the genre mapping data
def load_genre_map():
    genre_df = pd.read_csv('band_genre_map.csv')
    # Create a dictionary mapping from MH band name to genre
    genre_map = dict(zip(genre_df['MH band'], genre_df['Genre']))
    return genre_map

# Load data
df = load_tour_data()
genre_map = load_genre_map()

# Add genre column based on mapping
df['Genre'] = df['Band'].map(genre_map)

# Create display dataframe with desired columns
display_df = df[['Band', 'Genre', 'Show Date', 'Venue', 'City', 'ST', 'Attn']].copy()
display_df.columns = ['Artist Name', 'Genre', 'Show Date', 'Venue Name', 'Venue City', 'Venue State', 'Attendance']

# Sidebar filters
st.sidebar.header('Filters')

# Date range filter
min_date = pd.to_datetime(df['Show Date'], infer_datetime_format=True).min().date()
max_date = pd.to_datetime(df['Show Date'], infer_datetime_format=True).max().date()
date_range = st.sidebar.date_input(
    'Select Date Range',
    value=[min_date, max_date],
    min_value=min_date,
    max_value=max_date,
    format="MM/DD/YYYY"
)

# Genre filter
# Replace NaN with 'Unknown' and then get unique values
all_genres = ['All'] + sorted(display_df['Genre'].fillna('Unknown').unique().tolist())
selected_genre = st.sidebar.selectbox('Select Genre', all_genres)

# Artist filter
all_artists = ['All'] + sorted(display_df['Artist Name'].unique().tolist())
selected_artist = st.sidebar.selectbox('Select Artist', all_artists)

# Apply filters when button is clicked
if st.sidebar.button('Apply Filters'):
    # Convert dates
    start_date = pd.to_datetime(date_range[0])
    end_date = pd.to_datetime(date_range[1])
    
    # Filter by date
    filtered_df = display_df[
        (pd.to_datetime(display_df['Show Date']) >= start_date) &
        (pd.to_datetime(display_df['Show Date']) <= end_date)
    ]
    
    # Filter by genre if not 'All'
    if selected_genre != 'All':
        filtered_df = filtered_df[filtered_df['Genre'] == selected_genre]
        
    # Filter by artist if not 'All'
    if selected_artist != 'All':
        filtered_df = filtered_df[filtered_df['Artist Name'] == selected_artist]
    
    # Display results
    st.write(f"Showing results from {date_range[0]} to {date_range[1]}")
    if selected_genre != 'All':
        st.write(f"Genre: {selected_genre}")
    if selected_artist != 'All':
        st.write(f"Artist: {selected_artist}")
        
    st.dataframe(filtered_df, use_container_width=True)
else:
    # Show unfiltered data initially
    st.dataframe(display_df, use_container_width=True)
