"""
Enhanced worker script for PricePoa scraping service.
Coordinates spider execution, scheduling, and data processing.
"""
import asyncio
import logging
import signal
import sys
import os
from typing import Optional
import argparse
import time

# Add the current directory to Python path to enable imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('SCRAPY_SETTINGS_MODULE', 'settings')

# Now we can import from the scraper package
from scheduler import scrape_scheduler, setup_default_schedules
from base_spider import BasePricePoaSpider

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('scraping.log')
    ]
)

# Silence verbose PyMongo internal topology/connection debug heartbeats
logging.getLogger('pymongo').setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# Single source of truth for available spiders. Referenced by run_once_mode,
# run_test_mode, and the --spider argparse choices below, so adding a new
# spider only means updating this one list.
SPIDER_NAMES = [
    'naivas_spider',
    'carrefour_spider',
    'quickmart_spider',
    'chandarana_spider',
    # Add more spiders as they are created
]


def run_scheduled_mode():
    """Run the scraper in scheduled mode using APScheduler."""
    logger.info("Starting PricePoa scraper in scheduled mode")
    # Setup default schedules (daily scraping, hourly promos, etc.)
    setup_default_schedules()
    # Start the scheduler
    scrape_scheduler.start()
    logger.info("Scheduler started. Press Ctrl+C to exit.")
    try:
        # Keep the main thread alive
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, shutting down...")
        scrape_scheduler.shutdown(wait=True)
        logger.info("Shutdown complete.")


def run_once_mode(spider_name: Optional[str] = None):
    """Run spiders once immediately.

    If spider_name is given, only that spider is scheduled. Otherwise every
    spider in SPIDER_NAMES runs.
    """
    # Import here to avoid circular imports
    from scrapy.crawler import CrawlerProcess
    from scrapy.utils.project import get_project_settings

    settings = get_project_settings()
    settings.set('LOG_LEVEL', 'INFO')

    process = CrawlerProcess(settings)

    if spider_name:
        spiders_to_run = [spider_name]
        logger.info(f"Running single spider: {spider_name}")
    else:
        spiders_to_run = SPIDER_NAMES
        logger.info("Running all spiders")

    for name in spiders_to_run:
        logger.info(f"Scheduling spider: {name}")
        process.crawl(name)

    logger.info("Starting crawl process...")
    process.start()  # blocks until all crawling is finished
    logger.info("All spiders completed.")


def run_test_mode(spider_name: Optional[str] = None):
    """Run a single spider for testing. Defaults to naivas_spider if none given."""
    target = spider_name or 'naivas_spider'
    logger.info(f"Running test spider: {target}")
    run_once_mode(target)


def main():
    parser = argparse.ArgumentParser(description='PricePoa Scraper Worker')
    parser.add_argument(
        '--mode',
        choices=['scheduled', 'once', 'test'],
        default='scheduled',
        help='Operation mode: scheduled (default), once, or test'
    )
    parser.add_argument(
        '--spider',
        choices=SPIDER_NAMES,
        default=None,
        help=(
            'Limit --mode once/test to a single spider. '
            'Omit to run all spiders. Ignored in scheduled mode.'
        )
    )
    args = parser.parse_args()

    if args.mode == 'scheduled':
        if args.spider:
            logger.warning("--spider is ignored in scheduled mode; all schedules run as configured.")
        run_scheduled_mode()
    elif args.mode == 'once':
        run_once_mode(args.spider)
    elif args.mode == 'test':
        run_test_mode(args.spider)
    else:
        logger.error(f"Unknown mode: {args.mode}")
        sys.exit(1)


if __name__ == '__main__':
    main()