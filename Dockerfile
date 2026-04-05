FROM python:3.12-slim

WORKDIR /app

# Install deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Railway mounts persistent volume at /data if configured
# STORE_PATH defaults to /data/seen_urls.json (set in store.py)
ENV PYTHONUNBUFFERED=1

CMD ["python", "bot.py"]
