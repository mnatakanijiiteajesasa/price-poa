"""
MongoDB pipeline for PricePoa scraping items.
Focuses solely on persistence: buffering, bulk writes, and basic error handling.
Does NOT perform validation, normalization, or any business logic.
"""
import logging
from typing import Any, Dict, Union
import scrapy
from scrapy.exceptions import DropItem
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import UpdateOne
import asyncio
from datetime import datetime

# Import Redis cache for invalidation
try:
    import sys
    import os
    current_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, os.path.abspath(os.path.join(current_dir, '..', '..', 'api')))
    from redis_cache import redis_cache, make_prices_key, make_product_key
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    # Create a mock redis_cache that does nothing
    class MockRedisCache:
        async def delete(self, key): pass
    redis_cache = MockRedisCache()

logger = logging.getLogger(__name__)


class MongoDBPipeline:
    """
    Pipeline to store price scraping items in MongoDB.
    Handles connection management and batch operations for efficiency.

    Responsibilities:
    - Buffer items for bulk insertion
    - Perform bulk upserts to prices collection
    - Handle connection lifecycle
    - Basic error handling and retry logic
    - Logging and monitoring

    Does NOT:
    - Validate data (handled by ValidationPipeline)
    - Normalize or clean data (handled by NormalizationPipeline)
    - Perform lookups or enrichment
    - Modify item data
    """

    def __init__(self, buffer_size: int = 100):
        self.db: AsyncIOMotorDatabase = None
        self.buffer = []  # Buffer items for batch insertion
        self.buffer_size = buffer_size  # Flush buffer when this size is reached
        logger.info("MongoDBPipeline initialized")

    @classmethod
    def from_crawler(cls, crawler):
        """Create pipeline instance from crawler."""
        # Optional: get buffer size from settings
        buffer_size = crawler.settings.getint('MONGODB_BUFFER_SIZE', 100)
        return cls(buffer_size=buffer_size)

    async def open_spider(self, spider: scrapy.Spider):
        """Initialize MongoDB connection when spider opens."""
        try:
            # Fix import to work when run from scraper context
            import sys
            import os
            current_dir = os.path.dirname(os.path.abspath(__file__))
            sys.path.insert(0, os.path.abspath(os.path.join(current_dir, '..', 'database')))
            sys.path.insert(0, os.path.abspath(os.path.join(current_dir, '..', '..', 'database')))
            sys.path.insert(0, os.path.abspath(os.path.join(current_dir, '..', '..')))
            from connection import get_database
            self.db = await get_database()
            logger.info(f"MongoDBPipeline connected to database for spider {spider.name}")
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            raise

    async def close_spider(self, spider: scrapy.Spider):
        """Flush remaining items and close connection when spider closes."""
        try:
            if self.buffer:
                await self._flush_buffer()
            logger.info(f"MongoDBPipeline closed for spider {spider.name}")
        except Exception as e:
            logger.error(f"Error closing MongoDBPipeline: {e}")

    def process_item(self, item: Union[Dict, Any], spider: scrapy.Spider) -> Union[Dict, Any]:
        """
        Process item by adding it to buffer for batch insertion.

        Args:
            item: Scraped item (dict or scrapy.Item)
            spider: Spider that scraped the item

        Returns:
            The item (unchanged)
        """
        # Convert scrapy.Item to dict for uniform handling
        if hasattr(item, 'fields'):
            item_dict = dict(item)
        else:
            item_dict = item

        # Add to buffer
        self.buffer.append(item_dict)

        # Flush buffer if it reaches maximum size
        if len(self.buffer) >= self.buffer_size:
            # Schedule buffer flush (don't block item processing)
            asyncio.create_task(self._flush_buffer())

        return item

    async def _flush_buffer(self):
        """Flush buffered items to MongoDB using bulk operations."""
        if not self.buffer:
            return

        try:
            buffer_to_flush = self.buffer.copy()
            self.buffer.copy()
            self.buffer.clear()

            if not buffer_to_flush:
                return

            logger.debug(f"Flushing {len(buffer_to_flush)} items to MongoDB")

            # Prepare bulk operations for prices collection
            operations = []

            for item in buffer_to_flush:
                try:
                    # Expect item to have: product_id, store_id, price_kes, source, verified_at,
                    # is_promotional, promotion_details (already validated/normalized)
                    # We do not modify the item; we trust validation pipeline.

                    # Create document for prices collection
                    price_doc = {
                        'product_id': item.get('product_id'),
                        'store_id': item.get('store_id'),
                        'price_kes': item.get('price_kes'),
                        'source': item.get('source'),
                        'verified_at': item.get('verified_at', datetime.utcnow()),
                        'is_promotional': item.get('is_promotional', False),
                        'promotion_details': item.get('promotion_details'),
                        # Optional: store raw data for debugging if present
                        # 'raw_data': item.get('raw_data', {})
                    }

                    # Create update operation - upsert based on product+store+source+day
                    # This avoids duplicate prices for same product/store/source/day
                    verified_at = item.get('verified_at')
                    if isinstance(verified_at, datetime):
                        day_start = verified_at.replace(hour=0, minute=0, second=0, microsecond=0)
                    else:
                        # If it's a string or missing, use today
                        day_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

                    filter_criteria = {
                        'product_id': item.get('product_id'),
                        'store_id': item.get('store_id'),
                        'source': item.get('source'),
                        'verified_at': {'$gte': day_start}
                    }

                    update_operation = UpdateOne(
                        filter_criteria,
                        {'$set': price_doc, '$setOnInsert': {'created_at': datetime.utcnow()}},
                        upsert=True
                    )
                    operations.append(update_operation)

                except Exception as e:
                    logger.warning(f"Error preparing item for MongoDB: {e}")
                    logger.debug(f"Problematic item: {item}")
                    continue  # Skip this item but continue with others

            # Execute bulk operation if we have any
            if operations:
                # Try with retries for transient errors
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        result = await self.db.prices.bulk_write(operations, ordered=False)
                        logger.debug(
                            f"MongoDB bulk write completed (attempt {attempt + 1}): "
                            f"{result.upserted_count} inserted, "
                            f"{result.modified_count} modified, "
                            f"{len(operations) - result.upserted_count - result.modified_count} duplicates"
                        )

                        # Invalidate Redis cache for updated products
                        if REDIS_AVAILABLE and (result.upserted_count > 0 or result.modified_count > 0):
                            await self._invalidate_price_cache(buffer_to_flush)

                        break  # Success, exit retry loop
                    except Exception as e:
                        if attempt == max_retries - 1:
                            logger.error(f"Failed to flush buffer after {max_retries} attempts: {e}")
                            # Optionally, we could put items back in buffer for retry?
                            # For now, we drop them to avoid infinite loops.
                        else:
                            wait_time = 2 ** attempt  # Exponential backoff
                            logger.warning(f"Bulk write failed (attempt {attempt + 1}), retrying in {wait_time}s: {e}")
                            await asyncio.sleep(wait_time)

        except Exception as e:
            logger.error(f"Error flushing buffer to MongoDB: {e}")
            # In case of catastrophic error, we clear buffer to avoid infinite retry loop
            # Putting items back could cause repeated failures
            self.buffer.clear()

    async def _invalidate_price_cache(self, items: list):
        """
        invalidate Redis cache for products whose prices have been updated.

        Args:
            items: List of items that were inserted/updated
        """
        try:
            # Extract unique product IDs from the items
            product_ids = set()
            for item in items:
                product_id = item.get('product_id')
                if product_id:
                    product_ids.add(str(product_id))  # Ensure it's a string

            # Invalidate price cache for each product
            for product_id in product_ids:
                # Invalidate product prices cache
                prices_key = make_prices_key(product_id)
                await redis_cache.delete(prices_key)

                # Invalidate product cache (optional, but good practice)
                product_key = make_product_key(product_id)
                await redis_cache.delete(product_key)

                logger.debug(f"Invalidated Redis cache for product {product_id}")

            if product_ids:
                logger.info(f"Invalidated Redis price cache for {len(product_ids)} products: {list(product_ids)}")

        except Exception as e:
            logger.warning(f"Error invalidating Redis cache: {e}")

    def get_buffer_size(self) -> int:
        """Get current buffer size for monitoring."""
        return len(self.buffer)