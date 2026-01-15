# Trading System Dockerfile
FROM python:3.11-slim

WORKDIR /app

# 安裝系統依賴
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 複製並安裝 Python 套件
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 複製程式碼
COPY src/ ./src/

# 建立資料目錄
RUN mkdir -p /app/data /app/logs

# 環境變數
ENV PYTHONUNBUFFERED=1

CMD ["python", "src/main.py"]
