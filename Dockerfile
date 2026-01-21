FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Build offline FoodData Central snapshot for FDC-based nutrition lookup
# Skip for now and use commited DB, change if DB will be increased in size
# RUN python scripts/build_fdc_sqlite.py --dest data/fdc.sqlite --include-sr-legacy

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info", "--proxy-headers", "--forwarded-allow-ips=*"]
