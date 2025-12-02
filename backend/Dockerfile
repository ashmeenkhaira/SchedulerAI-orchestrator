FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY . .

# Environment defaults
ENV PORT=8000
ENV DATABASE_URL="sqlite+aiosqlite:///simulation.db"

# CMD
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]