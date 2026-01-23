FROM python:3.10-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# Set working directory
WORKDIR /app

# Install system dependencies required for Playwright
# We need to install the browser drivers later, but some system deps might be needed first
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
# We create a minimal requirements file for the migration tool specifically
# to avoid the huge/conflicting main requirements.txt
COPY requirements-docker.txt .
RUN pip install --upgrade pip && \
    pip install -r requirements-docker.txt

# Install Playwright browsers (Chromium only to save space/time)
RUN playwright install --with-deps chromium

# Copy the rest of the application
COPY . .

# Default command (can be overridden)
CMD ["python", "production_migration_engine_new.py"]
