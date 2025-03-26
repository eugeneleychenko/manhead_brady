from flask import Flask, request, jsonify
from joblib import load
import pandas as pd
import numpy as np
import requests
import tempfile
import os
import logging
import datetime as dt
import time

# Configure logging
timestamp = dt.datetime.now().strftime("%m_%d_%Y-%I_%M_%S_%p")
logging.basicConfig(
    filename=f'flask_api_log_{timestamp}.log', 
    level=logging.DEBUG, 
    format='%(asctime)s - %(levelname)s - %(filename)s - %(lineno)d - %(message)s'
)

app = Flask(__name__)

# Global variables for models
model = None
scaler = None
encoder = None

# Model URLs
MODEL_URL = "https://mh-forecast.nyc3.cdn.digitaloceanspaces.com/model_retrained.joblib"
SCALER_URL = "https://mh-forecast.nyc3.cdn.digitaloceanspaces.com/robust_scaler_retrained.joblib"
ENCODER_URL = "https://mh-forecast.nyc3.cdn.digitaloceanspaces.com/label_encoder_retrained.joblib"

# Input feature lists
input_categorical_features = ['artistName', 'Genre', 'Show Day', 'Show Month', 'Day of Week Num', 'venue name', 'venue state', 'venue city', 'productType', 'product size']
input_numerical_features = ['attendance', 'product price']
output_features = ['artistName', 'Genre', 'showDate', 'venue name', 'venue state', 'venue city', 'productType', 'product size', 'attendance', 'product price', 'Item Name', 'predicted_sales_quantity', '%_item_sales_per_category']

# Load models at startup
def load_models():
    global model, scaler, encoder
    print("Loading models at startup...")
    logging.info("Starting to load models at startup")
    
    start_time = time.time()
    
    # Download and load models
    try:
        # Model
        with tempfile.NamedTemporaryFile(delete=False) as temp:
            print(f"Downloading model from {MODEL_URL}...")
            response = requests.get(MODEL_URL)
            temp.write(response.content)
            temp_path = temp.name
        model = load(temp_path)
        os.unlink(temp_path)
        print("Model loaded successfully")
        logging.info("Model loaded successfully")
        
        # Scaler
        with tempfile.NamedTemporaryFile(delete=False) as temp:
            print(f"Downloading scaler from {SCALER_URL}...")
            response = requests.get(SCALER_URL)
            temp.write(response.content)
            temp_path = temp.name
        scaler = load(temp_path)
        os.unlink(temp_path)
        print("Scaler loaded successfully")
        logging.info("Scaler loaded successfully")
        
        # Encoder
        with tempfile.NamedTemporaryFile(delete=False) as temp:
            print(f"Downloading encoder from {ENCODER_URL}...")
            response = requests.get(ENCODER_URL)
            temp.write(response.content)
            temp_path = temp.name
        encoder = load(temp_path)
        os.unlink(temp_path)
        print("Encoder loaded successfully")
        logging.info("Encoder loaded successfully")
        
        elapsed_time = time.time() - start_time
        print(f"All models loaded successfully in {elapsed_time:.2f} seconds!")
        logging.info(f"All models loaded successfully in {elapsed_time:.2f} seconds")
        return True
    except Exception as e:
        print(f"Error loading models: {e}")
        logging.error(f"Error loading models: {e}")
        return False

@app.route('/health', methods=['GET'])
def health_check():
    if model is None or scaler is None or encoder is None:
        return jsonify({"status": "error", "message": "Models not loaded"}), 500
    return jsonify({"status": "ok", "message": "API is healthy, models are loaded"}), 200

@app.route('/predict', methods=['POST'])
def predict():
    if model is None or scaler is None or encoder is None:
        return jsonify({"status": "error", "message": "Models not loaded"}), 500
    
    try:
        # Get data from request
        data = request.json
        if not data:
            return jsonify({"status": "error", "message": "No data provided"}), 400
        
        logging.info(f"Received prediction request with {len(data)} records")
        
        # Convert to DataFrame
        df = pd.DataFrame(data)
        
        # Process data for prediction
        # Convert 'showDate' to datetime and extract features
        df['showDate'] = pd.to_datetime(df['showDate'])
        df['Show Day'] = df['showDate'].dt.day
        df['Show Month'] = df['showDate'].dt.month
        df['Day of Week Num'] = df['showDate'].dt.weekday
        
        # Split numerical and categorical features
        df_num = df[input_numerical_features].copy()
        df_cat = df[input_categorical_features].copy()
        
        # Scale numerical features
        for feature in input_numerical_features:
            if feature in df_num.columns:
                df_num[[feature]] = scaler[feature].transform(df_num[[feature]])
            else:
                logging.warning(f"Feature {feature} not found in inference data")
        
        # Encode categorical features
        for feature in input_categorical_features:
            df_cat[feature] = df_cat[feature].astype(str).str.strip().str.replace('\xa0', ' ').str.lower()
            df_cat[feature] = df_cat[feature].apply(lambda x: x if x in encoder[feature].classes_ else 'unknown_category')
            df_cat[feature] = encoder[feature].transform(df_cat[feature])
        
        # Combine features
        df_scaled_encoded = pd.concat([df_num, df_cat], axis=1)
        
        # Drop rows with NA values
        df_scaled_encoded.dropna(inplace=True)
        
        # Make predictions
        predictions = model.predict(df_scaled_encoded)
        
        # Add predictions to original dataframe
        df['predicted_sales_quantity'] = np.round(predictions).astype(int)
        
        # Calculate '% sales per product' and round to 2 decimal places
        df['%_item_sales_per_category'] = df.groupby(['artistName', 'showDate', 'productType'])['predicted_sales_quantity'].transform(lambda x: round((x / x.sum()) * 100, 2))
        
        # Create output dataframe
        output_df = df[output_features].copy()
        
        # Convert datetime to string format for JSON serialization
        output_df['showDate'] = output_df['showDate'].dt.strftime('%Y-%m-%d')
        
        # Return results
        return jsonify({
            "status": "success",
            "data": output_df.to_dict(orient='records'),
            "record_count": len(output_df)
        }), 200
        
    except Exception as e:
        logging.error(f"Prediction error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/model-info', methods=['GET'])
def model_info():
    """Return information about the loaded models."""
    if model is None or scaler is None or encoder is None:
        return jsonify({"status": "error", "message": "Models not loaded"}), 500
    
    try:
        # Get model type
        model_type = type(model).__name__
        
        # Get model features
        categorical_features = list(encoder.keys()) if hasattr(encoder, 'keys') else []
        numerical_features = list(scaler.keys()) if hasattr(scaler, 'keys') else []
        
        return jsonify({
            "status": "success",
            "model_type": model_type,
            "categorical_features": categorical_features,
            "numerical_features": numerical_features,
            "input_categorical_features": input_categorical_features,
            "input_numerical_features": input_numerical_features,
        }), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# Load models when app starts
print("Starting Flask API...")
load_status = load_models()

if __name__ == '__main__':
    if load_status:
        # Run the Flask API
        app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
    else:
        print("Failed to load models. API cannot start.")
        exit(1) 