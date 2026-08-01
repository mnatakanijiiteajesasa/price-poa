#!/bin/bash
set -e

echo "Intelligence service starting..."

# Run any initialization scripts if needed
if [ -f "/app/initialize_intelligence.py" ]; then
    echo "Running initialization script..."
    python /app/initialize_intelligence.py
fi

# Start the scheduler for periodic tasks
echo "Starting APScheduler for periodic intelligence tasks..."
python -m intelligence.scheduler &

# Keep the container running
# Run tests or keep alive
if [ "$1" = "test" ]; then
    echo "Running tests..."
    python -m pytest /app/test_imports.py -v
else
    echo "Intelligence service is running..."
    # Keep container alive
    tail -f /dev/null
fi