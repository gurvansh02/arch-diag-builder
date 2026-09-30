FROM python:3.12-slim

WORKDIR /app

# tesseract-ocr backs the last-resort vision fallback.
# curl is used by the healthcheck.
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# One directory per line. The previous version used shell brace expansion,
# which /bin/sh (dash) does not support - it created a single literal
# directory named "user_data/{conversations,diagrams,...}".
# config/settings.py also creates these at import time; this just makes the
# layout explicit for volume mounts.
RUN mkdir -p \
        user_data/conversations \
        user_data/diagrams \
        user_data/uploads \
        user_data/activity_logs \
        user_data/backups \
        user_data/config

EXPOSE 8501

ENV PYTHONUNBUFFERED=1 \
    STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_HEADLESS=true

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:8501/_stcore/health || exit 1

CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
