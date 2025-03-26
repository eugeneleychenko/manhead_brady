import streamlit as st
import pandas as pd
import numpy as np
import requests
import datetime as dt
import os
import json
import logging
import time

# Configure logging
timestamp = dt.datetime.now().strftime("%m_%d_%Y-%I_%M_%S_%p")
logging.basicConfig(
    filename=f'streamlit_client_log_{timestamp}.log', 
    level=logging.DEBUG, 
    format='%(asctime)s - %(levelname)s - %(filename)s - %(lineno)d - %(message)s'
)

# Set page config
st.set_page_config(page_title="All Products Sales By Size Predictor", layout="wide")
st.title("Predict Merch Sales Quantity By Size")

# Define API endpoint - can be changed via environment variable
API_URL = os.environ.get("FLASK_API_URL", "http://localhost:8080")

# Check API health
def check_api_health():
    try:
        response = requests.get(f"{API_URL}/health", timeout=5)
        if response.status_code == 200:
            return True, response.json().get("message", "API is healthy")
        else:
            return False, response.json().get("message", "API is not responding correctly")
    except requests.exceptions.RequestException as e:
        return False, f"Cannot connect to API: {str(e)}"

# Show API status
st.sidebar.title("API Status")
api_status, api_message = check_api_health()
if api_status:
    st.sidebar.success(api_message)
else:
    st.sidebar.error(api_message)
    st.sidebar.info(f"Using API at: {API_URL}")
    if st.sidebar.button("Retry Connection"):
        st.experimental_rerun()

# Show model information
if api_status:
    try:
        model_info_response = requests.get(f"{API_URL}/model-info")
        if model_info_response.status_code == 200:
            model_info = model_info_response.json()
            st.sidebar.subheader("Model Information")
            st.sidebar.write(f"Model Type: {model_info.get('model_type', 'Unknown')}")
            st.sidebar.write(f"Input Features: {len(model_info.get('categorical_features', [])) + len(model_info.get('numerical_features', []))}")
    except:
        st.sidebar.warning("Could not fetch model information")

# File uploader
st.subheader("Upload CSV File")
uploaded_file = st.file_uploader("Drag and drop or click to upload a CSV file", type="csv")

# Create a downloads directory if it doesn't exist
downloads_dir = os.path.join(os.path.dirname(__file__), 'downloads')
if not os.path.exists(downloads_dir):
    os.makedirs(downloads_dir)
    logging.info(f"Downloads directory created at: {downloads_dir}")

if uploaded_file is not None:
    try:
        logging.info("CSV file received")
        df = pd.read_csv(uploaded_file, encoding='utf-8-sig')
        logging.info(f"CSV file read successfully with {len(df)} rows")
        
        # Show data preview
        st.subheader("Data Preview")
        st.dataframe(df.head())
        
        # Process button
        if st.button("Process Data and Make Predictions"):
            if not api_status:
                st.error("Cannot connect to API. Please check API status.")
            else:
                with st.spinner("Processing data and making predictions..."):
                    start_time = time.time()
                    logging.info(f"Sending {len(df)} rows to API for prediction")
                    
                    # Create a progress bar
                    progress_text = st.empty()
                    progress_bar = st.progress(0)
                    
                    progress_text.text("Sending data to API...")
                    progress_bar.progress(0.1)
                    
                    try:
                        # Send data to API
                        response = requests.post(
                            f"{API_URL}/predict",
                            json=df.to_dict(orient='records'),
                            timeout=120  # Longer timeout for large datasets
                        )
                        
                        progress_bar.progress(0.7)
                        progress_text.text("Processing response...")
                        
                        if response.status_code == 200:
                            result = response.json()
                            
                            # Get predictions
                            predictions_data = result.get("data", [])
                            record_count = result.get("record_count", 0)
                            
                            if predictions_data:
                                # Convert to DataFrame
                                output_df = pd.DataFrame(predictions_data)
                                
                                progress_bar.progress(0.9)
                                progress_text.text("Preparing results...")
                                
                                # Calculate elapsed time
                                elapsed_time = time.time() - start_time
                                
                                # Display results
                                st.subheader("Prediction Results")
                                st.write(f"Processed {record_count} records in {elapsed_time:.2f} seconds")
                                st.dataframe(output_df)
                                
                                # Save to CSV
                                timestamp = dt.datetime.now().strftime("%m_%d_%Y-%I_%M_%S_%p")
                                csv_filename = f'predicted_sales_by_size_all_products_{timestamp}.csv'
                                csv_path = os.path.join(downloads_dir, csv_filename)
                                output_df.to_csv(csv_path, index=False)
                                logging.info(f"CSV file saved to {csv_path}")
                                
                                # Provide download button
                                with open(csv_path, 'rb') as f:
                                    st.download_button(
                                        label="Download Predictions as CSV",
                                        data=f,
                                        file_name=csv_filename,
                                        mime="text/csv"
                                    )
                                
                                progress_bar.progress(1.0)
                                progress_text.text("Completed!")
                            else:
                                st.error("No predictions returned from API")
                        else:
                            st.error(f"API Error: {response.text}")
                            logging.error(f"API returned error: {response.text}")
                    
                    except requests.exceptions.Timeout:
                        st.error("API request timed out. Your dataset might be too large.")
                        logging.error("API request timed out")
                    except requests.exceptions.RequestException as e:
                        st.error(f"Error communicating with API: {str(e)}")
                        logging.error(f"Request exception: {str(e)}")
                    except Exception as e:
                        st.error(f"An unexpected error occurred: {str(e)}")
                        logging.error(f"Unexpected error: {str(e)}")
        
    except Exception as e:
        logging.error(f"Error during file processing: {e}")
        st.error(f"An error occurred during file processing: {e}. Please check your input data.")

# Add information about the API-based approach
st.sidebar.markdown("---")
st.sidebar.subheader("About")
st.sidebar.info(
    "This application uses a Flask API backend for predictions. "
    "The ML models are loaded once when the API starts, eliminating "
    "the need to download them for each prediction."
)

# Run the app
if __name__ == '__main__':
    # Streamlit runs this script directly
    pass 