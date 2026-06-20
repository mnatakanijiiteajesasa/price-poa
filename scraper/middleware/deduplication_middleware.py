"""
Deduplication middleware for PricePoa scraping pipeline.
Prevents duplicate price items from being processed multiple times.
"""
import hashlib
import logging
from typing import Set
import scrapy

logger = logging.getLogger(__name__)


class PriceDeduplicationMiddleware:
    """
    Middleware to filter out duplicate price items based on
    product, store, price, and source combination.
    """

    def __init__(self):
        self.seen_prices: Set[str] = set()
        logger.info("PriceDeduplicationMiddleware initialized")

    @classmethod
    def from_crawler(cls, crawler):
        """Create middleware instance from crawler."""
        return cls()

    def process_spider_output(self, response, result, spider):
        """
        Process spider output and filter duplicates.
        """
        def process_item(item):
            # Only process item-like objects (dicts or scrapy.Item)
            if isinstance(item, dict) or hasattr(item, 'fields'):
                if self.is_duplicate(item):
                    logger.debug(f"Filtering duplicate price item: {self._get_item_key(item)}")
                    return None  # Filter out duplicate
            return item

        # Handle both iterables and single items
        if hasattr(result, '__iter__') and not isinstance(result, (str, bytes, dict)):
            for item in result:
                processed = process_item(item)
                if processed is not None:
                    yield processed
        else:
            processed = process_item(result)
            if processed is not None:
                yield processed

    def is_duplicate(self, item) -> bool:
        """
        Check if item is a duplicate based on price signature.
        """
        try:
            key = self._get_item_key(item)
            if key in self.seen_prices:
                return True
            self.seen_prices.add(key)
            return False
        except Exception as e:
            logger.warning(f"Error checking duplicate for item {item}: {e}")
            # If we can't determine, let it through to avoid losing data
            return False

    def _get_item_key(self, item) -> str:
        """
        Generate a unique key for price deduplication.
        Based on product_id, store_id, price, and source.
        """
        # Extract key fields - handle both dict and Item objects
        if isinstance(item, dict):
            product_id = item.get('product_id', '')
            store_id = item.get('store_id', '')
            price = item.get('price_kes', 0)
            source = item.get('source', '')
        else:
            # Assume scrapy.Item
            product_id = item.get('product_id', '')
            store_id = item.get('store_id', '')
            price = item.get('price_kes', 0)
            source = item.get('source', '')

        # Normalize price to 2 decimal places for consistency
        try:
            price_norm = round(float(price), 2)
        except (ValueError, TypeError):
            price_norm = 0

        # Create hash from key components
        key_string = f"{product_id}|{store_id}|{price_norm:.2f}|{source.strip().lower()}"
        return hashlib.md5(key_string.encode()).hexdigest()

    def close_spider(self, spider):
        """Clean up when spider closes."""
        logger.info(f"PriceDeduplicationMiddleware processed {len(self.seen_prices)} unique price items")
        self.seen_prices.clear()