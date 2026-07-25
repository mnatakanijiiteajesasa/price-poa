#!/bin/bash
set -e

# Docker entrypoint for the intelligence service

echo "Starting PricePoa Intelligence Service..."

# Wait for MongoDB to be ready
echo "Waiting for MongoDB to be ready..."
until mongosh "$MONGODB_URI/$MONGODB_DB" --eval "db.runCommand({ ping: 1 })" --quiet; do
  echo "MongoDB is unavailable - sleeping"
  sleep 5
done

echo "MongoDB is up and running!"

# Run initialization
echo "Initializing intelligence models..."
python -c "
import asyncio
import logging
from intelligence import initialize_intelligence
from motor.motor_asyncio import AsyncIOMotorClient

async def init():
    client = AsyncIOMotorClient('$MONGODB_URI')
    db = client['$MONGODB_DB']
    try:
        result = await initialize_intelligence(db)
        print('Initialization results:', result)
    except Exception as e:
        print('Initialization error:', str(e))
        # Don't fail the container if initialization fails - models will train on first use
    finally:
        client.close()

asyncio.run(init())
"

# Start the background worker for periodic tasks
echo "Starting intelligence background worker..."

# This would normally run periodic tasks like model retraining, correlation updates, etc.
# For now, we'll run a simple loop that does periodic maintenance
python -c "
import asyncio
import logging
import time
from datetime import datetime, timedelta
from intelligence import intelligence_engine
from motor.motor_asyncio import AsyncIOMotorClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def background_worker():
    client = AsyncIOMotorClient('$MONGODB_URI')
    db = client['$MONGODB_DB']

    last_maintenance = None
    maintenance_interval = 6 * 60 * 60  # 6 hours in seconds

    try:
        while True:
            now = datetime.utcnow()

            # Run maintenance every 6 hours
            if last_maintenance is None or (now - last_maintenance).total_seconds() > maintenance_interval:
                logger.info('Running intelligence maintenance...')
                try:
                    result = await intelligence_engine.run_maintenance(db)
                    logger.info(f'Maintenance completed: {result}')
                    last_maintenance = now
                except Exception as e:
                    logger.error(f'Error during maintenance: {e}')

            # Sleep for 30 minutes before checking again
            await asyncio.sleep(30 * 60)

    except KeyboardInterrupt:
        logger.info('Shutting down intelligence worker...')
    finally:
        client.close()

if __name__ == '__main__':
    asyncio.run(background_worker())
"