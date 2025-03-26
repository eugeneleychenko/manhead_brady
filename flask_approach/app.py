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
import gc  # Add garbage collection module

# Configure aggressive garbage collection
gc.set_threshold(100, 5, 5)  # More aggressive garbage collection

# Configure logging
timestamp = dt.datetime.now().strftime("%m_%d_%Y-%I_%M_%S_%p")
logging.basicConfig(
    filename=f'flask_api_log_{timestamp}.log', 
    level=logging.DEBUG, 
    format='%(asctime)s - %(levelname)s - %(filename)s - %(lineno)d - %(message)s'
)

# Enable memory efficient mode for pandas
pd.options.mode.chained_assignment = None  # default='warn'

app = Flask(__name__)

# Global variables for models
model = None
scaler = None
encoder = None
model_loaded = False

# Environment variables for model loading
LAZY_LOAD = os.environ.get('LAZY_LOAD', 'False').lower() == 'true'
MEMORY_OPTIMIZED = os.environ.get('MEMORY_OPTIMIZED', 'True').lower() == 'true'

# Model URLs
MODEL_URL = "https://mh-forecast.nyc3.cdn.digitaloceanspaces.com/model_retrained.joblib"
SCALER_URL = "https://mh-forecast.nyc3.cdn.digitaloceanspaces.com/robust_scaler_retrained.joblib"
ENCODER_URL = "https://mh-forecast.nyc3.cdn.digitaloceanspaces.com/label_encoder_retrained.joblib"

# Input feature lists
input_categorical_features = ['artistName', 'Genre', 'Show Day', 'Show Month', 'Day of Week Num', 'venue name', 'venue state', 'venue city', 'productType', 'product size']
input_numerical_features = ['attendance', 'product price']
output_features = ['artistName', 'Genre', 'showDate', 'venue name', 'venue state', 'venue city', 'productType', 'product size', 'attendance', 'product price', 'Item Name', 'predicted_sales_quantity', '%_item_sales_per_category']

# Memory-optimized function to download and load a model
def download_and_load_model(url, model_type="model"):
    logging.info(f"Downloading {model_type} from {url}...")
    print(f"Downloading {model_type} from {url}...")
    
    try:
        with tempfile.NamedTemporaryFile(delete=False) as temp:
            response = requests.get(url, stream=True)
            # Read and write in chunks to avoid loading entire file in memory
            for chunk in response.iter_content(chunk_size=1024*1024):  # 1MB chunks
                temp.write(chunk)
            temp_path = temp.name
        
        loaded_model = load(temp_path)
        os.unlink(temp_path)
        print(f"{model_type.capitalize()} loaded successfully")
        logging.info(f"{model_type.capitalize()} loaded successfully")
        return loaded_model
    except Exception as e:
        print(f"Error loading {model_type}: {e}")
        logging.error(f"Error loading {model_type}: {e}")
        return None

# Load models at startup or on-demand
def load_models():
    global model, scaler, encoder, model_loaded
    
    if model_loaded:
        return True
        
    print("Loading models...")
    logging.info("Starting to load models")
    
    start_time = time.time()
    
    # If we're in lazy load mode and this isn't a direct call, defer loading
    if LAZY_LOAD and not model_loaded:
        print("Lazy loading enabled - models will be loaded on first prediction")
        logging.info("Lazy loading enabled - models will be loaded on first prediction")
        return True
    
    try:
        # Load smaller models first (scaler and encoder)
        scaler = download_and_load_model(SCALER_URL, "scaler")
        gc.collect()
        
        encoder = download_and_load_model(ENCODER_URL, "encoder")
        gc.collect()
        
        # Load the large model last
        model = download_and_load_model(MODEL_URL, "model")
        gc.collect()
        
        if model is not None and scaler is not None and encoder is not None:
            elapsed_time = time.time() - start_time
            print(f"All models loaded successfully in {elapsed_time:.2f} seconds!")
            logging.info(f"All models loaded successfully in {elapsed_time:.2f} seconds")
            model_loaded = True
            return True
        else:
            return False
            
    except Exception as e:
        print(f"Error loading models: {e}")
        logging.error(f"Error loading models: {e}")
        return False

@app.route('/health', methods=['GET'])
def health_check():
    global model_loaded
    
    if LAZY_LOAD:
        return jsonify({
            "status": "ok", 
            "message": "API is healthy, lazy loading enabled",
            "model_loaded": model_loaded
        }), 200
    
    if model is None or scaler is None or encoder is None:
        return jsonify({"status": "error", "message": "Models not loaded"}), 500
        
    return jsonify({"status": "ok", "message": "API is healthy, models are loaded"}), 200

@app.route('/predict', methods=['POST'])
def predict():
    global model, scaler, encoder, model_loaded
    
    # Load models if not already loaded (for lazy loading)
    if LAZY_LOAD and not model_loaded:
        success = load_models()
        if not success:
            return jsonify({"status": "error", "message": "Failed to load models"}), 500
    
    if model is None or scaler is None or encoder is None:
        return jsonify({"status": "error", "message": "Models not loaded"}), 500
    
    try:
        # Get data from request
        data = request.json
        if not data:
            return jsonify({"status": "error", "message": "No data provided"}), 400
        
        data_size = len(data)
        logging.info(f"Received prediction request with {data_size} records")
        
        # Process data in batches if memory optimization is enabled
        if MEMORY_OPTIMIZED and data_size > 100:
            batch_size = 100
            results = []
            
            for i in range(0, data_size, batch_size):
                batch = data[i:i+batch_size]
                batch_results = process_batch(batch)
                results.extend(batch_results)
                gc.collect()  # Force collection after each batch
                
            return jsonify({
                "status": "success",
                "data": results,
                "record_count": len(results)
            }), 200
        else:
            # Process all data at once for small datasets
            results = process_batch(data)
            return jsonify({
                "status": "success",
                "data": results,
                "record_count": len(results)
            }), 200
            
    except Exception as e:
        logging.error(f"Prediction error: {e}")
        gc.collect()  # Force garbage collection after error
        return jsonify({"status": "error", "message": str(e)}), 500

def process_batch(batch_data):
    try:
        # Convert to DataFrame
        df = pd.DataFrame(batch_data)
        df = df.copy()  # This can help with memory usage
        
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
        gc.collect()  # Force garbage collection after large DataFrame operations
        
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
        
        # Convert to list of dicts for serialization
        result = output_df.to_dict(orient='records')
        
        # Clean up to free memory
        del df_num, df_cat, df_scaled_encoded, predictions, df, output_df
        gc.collect()  # Force garbage collection before returning
        
        return result
        
    except Exception as e:
        logging.error(f"Batch processing error: {e}")
        gc.collect()
        raise

@app.route('/model-info', methods=['GET'])
def model_info():
    """Return information about the loaded models."""
    global model_loaded
    
    if LAZY_LOAD:
        return jsonify({
            "status": "success",
            "lazy_loading": True,
            "model_loaded": model_loaded,
            "memory_optimized": MEMORY_OPTIMIZED,
            "input_categorical_features": input_categorical_features,
            "input_numerical_features": input_numerical_features,
        }), 200
    
    if model is None or scaler is None or encoder is None:
        return jsonify({"status": "error", "message": "Models not loaded"}), 500
    
    try:
        # Get model type
        model_type = type(model).__name__
        
        # Get model features
        categorical_features = list(encoder.keys()) if hasattr(encoder, 'keys') else []
        numerical_features = list(scaler.keys()) if hasattr(scaler, 'keys') else []
        
        result = {
            "status": "success",
            "model_type": model_type,
            "categorical_features": categorical_features,
            "numerical_features": numerical_features,
            "input_categorical_features": input_categorical_features,
            "input_numerical_features": input_numerical_features,
            "memory_optimized": MEMORY_OPTIMIZED,
            "lazy_loading": LAZY_LOAD
        }
        
        gc.collect()  # Force garbage collection after generating response
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# Load models at startup if not in lazy load mode
print("Starting Flask API...")
if not LAZY_LOAD:
    load_status = load_models()
    if not load_status and not LAZY_LOAD:
        print("Failed to load models. API cannot start.")
        exit(1)
else:
    print("Lazy loading enabled. Models will be loaded on first prediction.")

if __name__ == '__main__':
    # Run the Flask API
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 8080))) 