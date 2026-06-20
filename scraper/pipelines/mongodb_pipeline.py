"""
MongoDB pipeline for PricePoa scraping items.
Stores validated price data in MongoDB collections.
"""
import logging
from typing import Any, Dict, Union
import scrapy
from scrapy.exceptions import DropItem
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import UpdateOne
import asyncio
from datetime import datetime

logger = logging.getLogger(__name__)


class MongoDBPipeline:
    """
    Pipeline to store price scraping items in MongoDB.
    Handles connection management and batch operations for efficiency.
    """

    def __init__(self):
        self.db: AsyncIOMotorDatabase = None
        self.buffer = []  # Buffer items for batch insertion
        self.buffer_size = 100  # Flush buffer when this size is reached
        logger.info("MongoDBPipeline initialized")

    @classmethod
    def from_crawler(cls, crawler):
        """Create pipeline instance from crawler."""
        return cls()

    async def open_spider(self, spider: scrapy.Spider):
        """Initialize MongoDB connection when spider opens."""
        try:
            from ..database.connection import get_database
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
            self.buffer.clear()

            if not buffer_to_flush:
                return

            logger.debug(f"Flushing {len(buffer_to_flush)} items to MongoDB")

            # Prepare bulk operations
            operations = []

            for item in buffer_to_flush:
                try:
                    # Create document for prices collection
                    price_doc = {
                        'product_id': item.get('product_id'),
                        'store_id': item.get('store_id'),
                        'price_kes': item.get('price_kes'),
                        'source': item.get('source'),
                        'verified_at': item.get('verified_at', datetime.utcnow()),
                        'is_promotional': item.get('is_promotional', False),
                        'promotion_details': item.get('promotion_details'),
                        'created_at': item.get('processed_at', datetime.utcnow()),
                        # Store raw data for debugging/audit Trail
                        'raw_data': item.get('raw_data', {})
                    }

                    # Create update operation - upsert based on product+store+source+time window
                    # This allows updating recent prices or inserting new ones
                    filter_criteria = {
                        'product_id': item.get('product_id'),
                        'store_id': item.get('store_id'),
                        'source': item.get('source'),
                        # Group prices by day to avoid too many duplicates
                        'verified_at': {
                            '$gte': item.get('verified_at', datetime.utcnow()).replace(
                                hour=0, minute=0, second=0, microsecond=0
                            )
                        }
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
                    continue

            # Execute bulk operation if we have any
            if operations:
                result = await self.db.prices.bulk_write(operations, ordered=False)
                logger.debug(
                    f"MongoDB bulk write completed: "
                    f"{result.upserted_count} inserted, "
                    f"{result.modified_count} modified, "
                    f"{len(operations) - result.upserted_count - result.modified_count} duplicates"
                )

        except Exception as e:
            logger.error(f"Error flushing buffer to MongoDB: {e}")
            # Put items back in buffer for retry? Or drop them?
            # For now, we'll drop them to avoid infinite retry loops
            # In production, you might want to implement a dead letter queue
            self.buffer.clear()

    def get_buffer_size(self) -> int:
        """Get current buffer size for monitoring."""
        return len(self.buffer)