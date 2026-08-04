#!/bin/bash
set -e

echo "Intelligence service starting..."

# Run any initialization scripts if needed
if [ -f "/app/initialize_intelligence.py" ]; then
    echo "Running initialization script..."
    python /app/initialize_intelligence.py
fi

# Start the embedding outbox worker (Change Streams + reconciliation sweep).
# Keeps Qdrant consistent with MongoDB products; resumes safely after restarts.
echo "Starting embedding outbox worker..."
python -m outbox.worker &

# Start the scheduler for periodic tasks
echo "Starting APScheduler for periodic intelligence tasks..."
python -m scheduler &

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