#!/usr/bin/env python3
"""
APScheduler configuration for periodic intelligence tasks.
Includes product embedding indexing that runs when scrapers run.
"""

import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
import asyncio
import sys
import os

# Add the app directory to path
sys.path.insert(0, '/app')

from intelligence.index_product_embeddings import index_product_embeddings
from intelligence.intelligence_engine import run_intelligence_maintenance

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global scheduler
scheduler = BackgroundScheduler()


async def run_embedding_indexing():
    """Run product embedding indexing."""
    try:
        logger.info("Starting product embedding indexing...")
        count = await index_product_embeddings()
        logger.info(f"Completed product embedding indexing. Indexed {count} vectors.")
    except Exception as e:
        logger.error(f"Error during product embedding indexing: {e}")


async def run_intelligence_maintenance_job():
    """Run intelligence maintenance tasks."""
    try:
        logger.info("Starting intelligence maintenance...")
        # We need to get a database connection - this would typically come from the app
        # For now, we'll log that this would run
        logger.info("Intelligence maintenance would run here (requires DB connection)")
    except Exception as e:
        logger.error(f"Error during intelligence maintenance: {e}")


def start_scheduler():
    """Start the background scheduler with intelligence tasks."""
    try:
        # Add job for product embedding indexing - runs every 6 hours
        # This can be adjusted to run when scrapers finish
        scheduler.add_job(
            func=lambda: asyncio.create_task(run_embedding_indexing()),
            trigger=IntervalTrigger(hours=6),
            id='product_embedding_indexing',
            name='Index product embeddings in Qdrant',
            replace_existing=True
        )

        # Add job for intelligence maintenance - runs every 12 hours
        scheduler.add_job(
            func=lambda: asyncio.create_task(run_intelligence_maintenance_job()),
            trigger=IntervalTrigger(hours=12),
            id='intelligence_maintenance',
            name='Run intelligence maintenance tasks',
            replace_existing=True
        )

        # Start the scheduler
        scheduler.start()
        logger.info("APScheduler started for intelligence tasks")

        # Keep the script running
        try:
            # Keep the main thread alive
            import time
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