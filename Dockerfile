# Trading System Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies (build tools for futu-api)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY src/ ./src/

# Create data directories
RUN mkdir -p /app/data /app/logs

# Volumes for persistence
VOLUME ["/app/data", "/app/logs"]

# Environment
ENV PYTHONUNBUFFERED=1
ENV TZ=Asia/Hong_Kong

# Health check
HEALTHCHECK --interval=60s --timeout=10s --start-period=120s --retries=3 \
    CMD python -c "print('ok')" || exit 1

CMD ["python", "src/main.py"]
