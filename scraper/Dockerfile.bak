# Use an official Python runtime as a parent image
FROM python:3.12-slim

# Install system dependencies (git is required for git-based python requirements)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file and install dependencies
COPY scraper/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers
RUN playwright install --with-deps
RUN python -m invisible_playwright fetch

# Copy the scraper app code
COPY scraper/ .

# Copy the shared database package
COPY database/ ./database

# Set environment variables for scraping
ENV SCRAPER_LOG_LEVEL=info
ENV SCRAPER_CONCURRENT_REQUESTS=16
ENV SCRAPER_DOWNLOAD_DELAY=1
ENV ENABLE_SCRAPER=true
ENV SCRAPY_SETTINGS_MODULE=settings

# Set the default command to run the worker script
CMD ["python", "worker.py", "--mode", "scheduled"]