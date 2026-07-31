FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY intelligence/requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --default-timeout=1000 --retries 50 -r requirements.txt
COPY intelligence/ .
COPY database/ ./database

#create directories for models and logs
RUN mkdir -p /app/models /app/logs

# set environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

#expose port (EXPOSED INTERNALLY)
EXPOSE 8000

# Copy entrypoint script
COPY intelligence/docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Entrypoint
ENTRYPOINT ["docker-entrypoint.sh"]