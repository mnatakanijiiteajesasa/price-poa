#!/usr/bin/env python3
"""
APScheduler configuration for periodic intelligence tasks.
Keeps product embeddings indexed through the transactional outbox so Qdrant
stays consistent with MongoDB (the outbox worker performs the actual writes).
"""

import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
import asyncio
import time
import sys
import os

# Add the app directory to path
sys.path.insert(0, '/app')

# Import the outbox service with a path fallback so this runs both from the
# container (/app = intelligence package contents) and from the repo root.
try:
    from intelligence.outbox.outbox import EmbeddingOutboxService
except ImportError:
    from outbox.outbox import EmbeddingOutboxService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global scheduler
scheduler = BackgroundScheduler()


async def run_embedding_indexing():
    """
    Routine backfill: enqueue any product that isn't already indexed into the
    outbox. This complements the event-driven path (products written by the
    scraper enqueue themselves transactionally) by catching anything written
    outside the outbox writers (e.g. seeding, manual admin edits).
    """
    try:
        logger.info("Starting embedding outbox backfill...")
        svc = EmbeddingOutboxService()
        count = await svc.backfill_products(force=False)
        logger.info(f"Enqueued {count} product(s) for embedding via outbox")
    except Exception as e:
        logger.error(f"Error during embedding outbox backfill: {e}")


def start_scheduler():
    """Start the background scheduler with intelligence tasks."""
    try:
        # Add job for product embedding indexing - runs every 6 hours.
        scheduler.add_job(
            func=lambda: asyncio.create_task(run_embedding_indexing()),
            trigger=IntervalTrigger(hours=6),
            id='product_embedding_indexing',
            name='Backfill product embeddings through the outbox',
            replace_existing=True
        )

        # Start the scheduler
        scheduler.start()
        logger.info("APScheduler started for intelligence tasks")

        # Keep the script running
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Shutting down scheduler...")
            scheduler.shutdown()

    except Exception as e:
        logger.error(f"Error starting scheduler: {e}")
        raise


if __name__ == "__main__":
    start_scheduler()
