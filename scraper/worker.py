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

# Add the current directory to Python path to enable imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

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

logger = logging.getLogger(__name__)