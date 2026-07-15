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

def run_once_mode():
    """Run all spiders once immediately."""
    logger.info("Running all spiders once")
    # Import here to avoid circular imports
    from scrapy.crawler import CrawlerProcess
    from scrapy.utils.project import get_project_settings

    settings = get_project_settings()
    settings.set('LOG_LEVEL', 'INFO')

    process = CrawlerProcess(settings)

    # List of spider names to run
    spider_names = [
        'naivas_spider',
        'carrefour_spider',
        'quickmart_spider',
        'chandarana_spider'
        # Add more spiders as they are created
    ]

    for spider_name in spider_names:
        logger.info(f"Scheduling spider: {spider_name}")
        process.crawl(spider_name)

    logger.info("Starting crawl process...")
    process.start()  # blocks until all crawling is finished
    logger.info("All spiders completed.")

def run_test_mode():
    """Run a single spider for testing."""
    logger.info("Running test spider")
    # For now, run naivas spider once
    run_once_mode()  # Could be modified to run only one spider

def main():
    parser = argparse.ArgumentParser(description='PricePoa Scraper Worker')
    parser.add_argument(
        '--mode',
        choices=['scheduled', 'once', 'test'],
        default='scheduled',
        help='Operation mode: scheduled (default), once, or test'
    )
    args = parser.parse_args()

    if args.mode == 'scheduled':
        run_scheduled_mode()
    elif args.mode == 'once':
        run_once_mode()
    elif args.mode == 'test':
        run_test_mode()
    else:
        logger.error(f"Unknown mode: {args.mode}")
        sys.exit(1)

if __name__ == '__main__':
    main()