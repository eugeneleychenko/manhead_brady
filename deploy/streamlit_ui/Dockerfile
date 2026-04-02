FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p CSVs/add_sales_reports_files_here \
             CSVs/add_tour_summary_files_here \
             CSVs/merged_files \
             outputs \
             cache \
             /tmp/logs \
             /tmp/debug_info

EXPOSE 8501

ENV FLASK_API_URL=""

CMD ["streamlit", "run", "streamlit_app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true"]
