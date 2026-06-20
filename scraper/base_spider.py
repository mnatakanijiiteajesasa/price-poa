"""
Base spider class for PricePoa scraping operations.
Provides common functionality for all store-specific spiders.
"""
import scrapy
from scrapy.spiders import Spider
from scrapy.http import Request, Response
from typing import Generator, Any, Optional
import logging
from datetime import datetime
import hashlib
import json

from ..database.connection import get_database
from ..database.models import Product, Store, Price

logger = logging.getLogger(__name__)


class BasePricePoaSpider(Spider):
    """
    Base spider for PricePoa scraping operations.
    Handles common functionality: database connection, deduplication, error handling.
    """

    name = 'base_pricepoa'
    allowed_domains = []  # Override in subclasses
    start_urls = []       # Override in subclasses

    # Custom settings for this spider
    custom_settings = {
        'DOWNLOAD_DELAY': 1,  # Be respectful to target sites
        'RANDOMIZE_DOWNLOAD_DELAY': True,
        'CONCURRENT_REQUESTS': 16,
        'CONCURRENT_REQUESTS_PER_DOMAIN': 8,
        'RETRY_TIMES': 3,
        'RETRY_HTTP_CODES': [500, 502, 503, 504, 408, 429],
        'COOKIES_ENABLED': True,
        'USER_AGENT': 'PricePoa Scraper (+https://pricepoa.co.ke)',
        'ROBOTSTXT_OBEY': True,
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.db = None
        self.products_cache = {}  # Cache product lookups by name/category
        self.stores_cache = {}    # Cache store lookups by chain/branch
        self.seen_prices = set()  # Track seen price combinations for deduplication

    async def setup_database(self):
        """Initialize database connection."""
        if self.db is None:
            self.db = await get_database()
            logger.info(f"Spider {self.name} connected to database")

    def get_product_id(self, product_name: str, category: str = None) -> Optional[str]:
        """
        Get or create product ID from database.
        Uses caching to reduce database queries.
        """
        cache_key = f"{product_name}:{category or 'unknown'}"
        if cache_key in self.products_cache:
            return self.products_cache[cache_key]

        # This would normally query the database
        # For now, return a placeholder - in practice, you'd query the products collection
        product_id = hashlib.md5(f"{product_name}_{category}".encode()).hexdigest()[:24]
        self.products_cache[cache_key] = product_id
        return product_id

    def get_store_id(self, chain_name: str, branch_name: str) -> Optional[str]:
        """
        Get or create store ID from database.
        Uses caching to reduce database queries.
        """
        cache_key = f"{chain_name}:{branch_name}"
        if cache_key in self.stores_cache:
            return self.stores_cache[cache_key]

        # This would normally query the database
        # For now, return a placeholder
        store_id = hashlib.md5(f"{chain_name}_{branch_name}".encode()).hexdigest()[:24]
        self.stores_cache[cache_key] = store_id
        return store_id

    def generate_price_hash(self, product_id: str, store_id: str, price: float, source: str) -> str:
        """
        Generate a hash for price deduplication.
        Same product/store/price/source combination will produce same hash.
        """
        price_string = f"{product_id}_{store_id}_{price:.2f}_{source}"
        return hashlib.md5(price_string.encode()).hexdigest()

    def is_duplicate_price(self, product_id: str, store_id: str, price: float, source: str) -> bool:
        """
        Check if this price is a duplicate of a recently seen price.
        Returns True if duplicate, False otherwise.
        """
        price_hash = self.generate_price_hash(product_id, store_id, price, source)
        if price_hash in self.seen_prices:
            return True
        self.seen_prices.add(price_hash)
        return False

    async def process_price_item(self, item: dict) -> bool:
        """
        Process a price item: validate, check for duplicates, prepare for storage.

        Args:
            item: Dictionary containing price data

        Returns:
            True if item should be processed, False if duplicate or invalid
        """
        try:
            # Validate required fields
            required_fields = ['product_name', 'store_chain', 'store_branch',
                             'price_kes', 'source']
            for field in required_fields:
                if field not in item or not item[field]:
                    logger.warning(f"Missing required field {field} in item: {item}")
                    return False

            # Get product and store IDs
            product_id = self.get_product_id(item['product_name'], item.get('category'))
            store_id = self.get_store_id(item['store_chain'], item['store_branch'])

            if not product_id or not store_id:
                logger.warning(f"Could not resolve product/store IDs for item: {item}")
                return False

            # Validate price
            price = float(item['price_kes'])
            if price <= 0:
                logger.warning(f"Invalid price {price} in item: {item}")
                return False

            # Check for duplicates
            if self.is_duplicate_price(product_id, store_id, price, item['source']):
                logger.debug(f"Duplicate price skipped: {item['product_name']} at {item['store_chain']}")
                return False

            # Prepare final item for pipeline
            processed_item = {
                'product_id': product_id,
                'store_id': store_id,
                'price_kes': round(price, 2),
                'source': item['source'].strip(),
                'verified_at': datetime.utcnow(),
                'is_promotional': item.get('is_promotional', False),
                'promotion_details': item.get('promotion_details'),
                'raw_data': item  # Keep original data for debugging
            }

            # Update item with processed data
            item.update(processed_item)
            return True

        except (ValueError, TypeError) as e:
            logger.warning(f"Invalid data type in item {item}: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error processing price item {item}: {e}")
            return False

    async def close(self, reason):
        """Cleanup when spider closes."""
        logger.info(f"Spider {self.name} closed: {reason}")
        # Clear caches to free memory
        self.products_cache.clear()
        self.stores_cache.clear()
        self.seen_prices.clear()
        await super().close(reason)


class PricePoaCSVSpider(BasePricePoaSpider):
    """
    Base spider for scraping from CSV/data feeds.
    Useful for stores that provide price data in structured formats.
    """

    def parse(self, response) -> Generator[dict, None, None]:
        """
        Parse CSV or structured data response.
        Override in subclasses for specific format handling.
        """
        # This is a placeholder - implement specific parsing in subclasses
        logger.warning(f"CSV parsing not implemented for {self.name}")
        return

        # Example implementation would be:
        # if response.headers.get('Content-Type', b'').startswith(b'text/csv'):
        #     import csv
        #     import io
        #     csv_data = csv.DictReader(io.StringIO(response.text))
        #     for row in csv_data:
        #         yield self.parse_csv_row(row)
        # else:
        #     # Handle JSON or other formats
        #     pass

    def parse_csv_row(self, row: dict) -> dict:
        """Parse a single CSV row into price item format."""
        # Override in subclasses
        return row