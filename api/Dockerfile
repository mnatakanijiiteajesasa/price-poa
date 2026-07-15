# Use an official Python runtime as a parent image
FROM python:3.12-slim

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file and install dependencies
COPY api/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code and shared folders
COPY api/ .
COPY database/ ./database
COPY infographics/ ./infographics

# Expose the port the app runs on
EXPOSE 8000

# Environment variables are set by docker-compose
# The command is overridden by docker-compose