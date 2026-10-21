FROM python:3.11-slim

# eMudhra intermediate CA compromise (2026-10-20): need ca-certificates >= 20250419+deb13u1
RUN apt-get update && apt-get install -y --no-install-recommends --only-upgrade ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Build offline FoodData Central snapshot for FDC-based nutrition lookup
# Skip for now and use commited DB, change if DB will be increased in size
# RUN python scripts/build_fdc_sqlite.py --dest data/fdc.sqlite --include-sr-legacy

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info", "--proxy-headers", "--forwarded-allow-ips=*"]
