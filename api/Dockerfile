# Use an official Python runtime as a parent image
FROM python:3.12-slim

# Set the working directory in the container
WORKDIR /app

# fonts-dejavu-core provides DejaVuSans.ttf / DejaVuSans-Bold.ttf at
# /usr/share/fonts/truetype/dejavu/ — used by infographic/generator.py's
# get_font(). Without this, Pillow silently falls back to its tiny bitmap
# default font and every FONT_SIZE_* constant in generator.py is ignored.
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Copy the requirements file and install dependencies
COPY api/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code and shared folders
COPY api/ .
COPY database/ ./database


# Expose the port the app runs on
EXPOSE 8000

# Environment variables are set by docker-compose
# The command is overridden by docker-compose