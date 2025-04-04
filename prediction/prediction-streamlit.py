import streamlit as st
import pandas as pd
import numpy as np
from joblib import load
import datetime as dt
import os
import logging
import sys
import requests
from pathlib import Path
from io import BytesIO

# Configure logging
timestamp = dt.datetime.now().strftime("%m_%d_%Y-%I_%M_%S_%p")
logging.basicConfig(
    filename=f'log_predict_all_products_sales_by_size_app_{timestamp}.log', 
    level=logging.DEBUG, 
    format='%(asctime)s - %(levelname)s - %(filename)s - %(lineno)d - %(message)s'
)

# Set page title and header
st.set_page_config(page_title="All Products Sales By Size Predictor", layout="wide")
st.title("Predict Merch Sales Quantity By Size for Replit")

# Define paths for model files
MODEL_DIR = Path("persisted_models")
MODEL_DIR.mkdir(exist_ok=True)  # Create directory if it doesn't exist

MODEL_PATH = MODEL_DIR / "model.joblib"
SCALER_PATH = MODEL_DIR / "scaler.joblib"
ENCODER_PATH = MODEL_DIR / "encoder.joblib"

MODEL_URL = "https://mh-forecast.nyc3.cdn.digitaloceanspaces.com/model_retrained_compressed.joblib"
SCALER_URL = "https://mh-forecast.nyc3.cdn.digitaloceanspaces.com/robust_scaler_retrained_compressed.joblib"
ENCODER_URL = "https://mh-forecast.nyc3.cdn.digitaloceanspaces.com/label_encoder_retrained_compressed.joblib"

# Function to download models if not already present locally
def download_models():
    try:
        if not MODEL_PATH.exists():
            with st.spinner("Downloading model (one-time operation)..."):
                model_response = requests.get(MODEL_URL)
                MODEL_PATH.write_bytes(model_response.content)
                logging.info("Model downloaded and saved locally.")

        if not SCALER_PATH.exists():
            with st.spinner("Downloading scaler (one-time operation)..."):
                scaler_response = requests.get(SCALER_URL)
                SCALER_PATH.write_bytes(scaler_response.content)
                logging.info("Scaler downloaded and saved locally.")

        if not ENCODER_PATH.exists():
            with st.spinner("Downloading encoder (one-time operation)..."):
                encoder_response = requests.get(ENCODER_URL)
                ENCODER_PATH.write_bytes(encoder_response.content)
                logging.info("Encoder downloaded and saved locally.")
    except Exception as e:
        st.error(f"Error downloading model files: {e}")
        logging.error(f"Error downloading model files: {e}")
        raise

# Function to load models from local storage
@st.cache_resource(show_spinner=False)  # Cache loaded models in memory
def load_models():
    try:
        # Ensure models are downloaded before loading
        download_models()

        # Load models from local files
        model = load(MODEL_PATH)
        scaler = load(SCALER_PATH)
        encoder = load(ENCODER_PATH)
        
        logging.info("Models loaded successfully from local storage.")
        return model, scaler, encoder
    except Exception as e:
        st.error(f"Error loading model files: {e}")
        logging.error(f"Error loading model files: {e}")
        return None, None, None

# Load models
model, scaler, encoder = load_models()

if model is None or scaler is None or encoder is None:
    st.error("Failed to load model files. Please check if model files exist and are accessible.")
    st.stop()

# Define features
input_categorical_features = ['artistName', 'Genre', 'Show Day', 'Show Month', 'Day of Week Num', 'venue name', 'venue state', 'venue city', 'productType', 'product size']
input_numerical_features = ['attendance', 'product price']
output_features = ['artistName', 'Genre', 'showDate', 'venue name', 'venue state', 'venue city', 'productType', 'product size', 'attendance', 'product price', 'Item Name', 'predicted_sales_quantity', '%_item_sales_per_category']

# File uploader
st.subheader("Upload CSV")
uploaded_file = st.file_uploader("Choose a CSV file", type="csv")

if uploaded_file is not None:
    try:
        # Read CSV
        df = pd.read_csv(uploaded_file, encoding='utf-8-sig')
        logging.info("CSV file read successfully")
        
        # Show raw data
        st.subheader("Raw Data")
        st.dataframe(df.head())
        
        # Process Data
        with st.spinner("Processing data and making predictions..."):
            # Convert 'show_date' to datetime and extract features
            df['showDate'] = pd.to_datetime(df['showDate'])
            logging.info("showDate column converted to datetime")
            df['Show Day'] = df['showDate'].dt.day
            logging.info("Show Day feature extracted")
            df['Show Month'] = df['showDate'].dt.month
            logging.info("Show Month feature extracted")
            df['Day of Week Num'] = df['showDate'].dt.weekday
            logging.info("Day of Week Num feature extracted")

            df_num = df[input_numerical_features].copy()
            df_cat = df[input_categorical_features].copy()
            logging.info("Separated numerical and categorical features")

            # Scale numerical features
            for feature in input_numerical_features:
                # Handle potential missing columns
                if feature in df_num.columns:
                    df_num[[feature]] = scaler[feature].transform(df_num[[feature]])
                else:
                    logging.warning(f"Feature {feature} not found in inference data")
            
            logging.info("Scaled all numerical features")

            # Encode categorical features
            for feature in input_categorical_features:
                # Standardize the text data
                df_cat[feature] = df_cat[feature].astype(str).str.strip().str.replace('\xa0', ' ').str.lower()
                
                # Check if each value is in the list of classes using 'isin'
                df_cat[feature] = df_cat[feature].apply(lambda x: x if x in encoder[feature].classes_ else 'unknown_category')

                # Transform the test data
                df_cat[feature] = encoder[feature].transform(df_cat[feature])
            
            logging.info("Encoded all categorical features")

            # Combine features
            df_scaled_encoded = pd.concat([df_num, df_cat], axis=1)
            logging.info("Combined all scaled and encoded features to pass as model input")

            # Drop rows with NA values
            df_scaled_encoded.dropna(inplace=True)
            logging.info("Rows with NA values dropped")

            # Make predictions
            predictions = model.predict(df_scaled_encoded)
            logging.info("Predictions made")

            # Reverse log transformation and round to nearest integer
            df['predicted_sales_quantity'] = np.round(predictions).astype(int)

            # Calculate '% sales per product' and round to 2 decimal places
            df['%_item_sales_per_category'] = df.groupby(['artistName', 'showDate', 'productType'])['predicted_sales_quantity'].transform(lambda x: round((x / x.sum()) * 100, 2))
            logging.info("percentage item sales per product category calculated")

            # Prepare output
            output_df = df[output_features]
            logging.info("Output dataframe created")

        # Display results
        st.subheader("Prediction Results")
        st.dataframe(output_df)
        
        # Create download button
        csv = output_df.to_csv(index=False)
        timestamp = dt.datetime.now().strftime("%m_%d_%Y-%I_%M_%S_%p")
        st.download_button(
            label="Download Predictions as CSV",
            data=csv,
            file_name=f"predicted_sales_by_size_all_products_{timestamp}.csv",
            mime="text/csv"
        )
        logging.info(f"CSV download button created")
        
    except Exception as e:
        st.error(f"An error occurred during prediction: {e}")
        logging.error(f"Error during prediction process: {e}")

# # Add instructions
# st.sidebar.header("Instructions")
# st.sidebar.markdown("""
# 1. Upload a CSV file with the following columns:
#    - artistName
#    - Genre
#    - showDate (in YYYY-MM-DD format)
#    - venue name
#    - venue state
#    - venue city
#    - productType
#    - product size
#    - attendance
#    - product price
#    - Item Name

# 2. Wait for the predictions to be generated.

# 3. Download the results as a CSV file.
# """)

# # Add some additional info
# st.sidebar.header("About")
# st.sidebar.info(
#     "This application predicts sales quantity by size for all products "
#     "based on various features related to artists, venues, and product details."
# )
