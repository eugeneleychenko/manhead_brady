# Merch Sales Quantity Predictor - API-Based Approach

This is an improved version of the Merch Sales Quantity Predictor that uses a Flask API backend to handle model loading and predictions, with a Streamlit frontend for the user interface.

## Architecture

- **Flask API Backend**: Loads ML models once at startup and provides prediction endpoints
- **Streamlit Frontend**: Provides a user-friendly interface and communicates with the API

This separation improves performance by eliminating the need to download models for each prediction request.

## Setup

### Local Development

1. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

2. Start the Flask API:
   ```
   python app.py
   ```

3. In a separate terminal, start the Streamlit frontend:
   ```
   streamlit run streamlit_app.py
   ```

4. The Streamlit app will automatically connect to the Flask API running on http://localhost:8080

### Environment Variables

- `PORT`: Port for the Flask API (default: 8080)
- `FLASK_API_URL`: URL of the Flask API for the Streamlit app to connect to (default: http://localhost:8080)

## Deployment on Render

### Deploying the Flask API

1. Create a new Web Service in Render:
   - Connect your repository
   - Set the build command: `pip install -r requirements.txt`
   - Set the start command: `gunicorn app:app`
   - Select an appropriate instance type (at least 512MB RAM)
   - Set environment variables as needed

2. Once deployed, note the URL of your Flask API

### Deploying the Streamlit Frontend

1. Create a new Web Service in Render:
   - Connect your repository
   - Set the build command: `pip install -r requirements.txt`
   - Set the start command: `streamlit run streamlit_app.py`
   - Set the environment variable `FLASK_API_URL` to the URL of your Flask API

## Project Structure

```
flask_approach/
├── app.py                # Flask API backend
├── streamlit_app.py      # Streamlit frontend
├── requirements.txt      # Dependencies for both applications
└── downloads/            # Created automatically to store CSV outputs
```

## How It Works

1. The Flask API downloads and loads ML models only once at startup
2. The Streamlit frontend allows users to upload CSV files
3. When a user processes data, the frontend sends it to the API
4. The API processes the data and returns predictions
5. The frontend displays the results and provides a download option

## Benefits

- Faster predictions since models are already loaded
- Improved user experience with no waiting for model downloads
- More efficient resource usage
- Better error handling and retry capabilities 