"""
Store resolution pipeline for PricePoa scraping items.
Resolves store_chain + store_branch into a persisted store_id.
Does NOT perform price validation or product normalization.
"""
import logging
import scrapy
from typing import Union, Dict, Any

logger = logging.getLogger(__name__)


class StoreResolutionPipeline:
    """
    Resolves or creates a store record and attaches store_id to the item.

    Responsibilities:
    - Look up store by chain + branch
    - Create the store record if it doesn't exist
    - Attach store_id to the item for downstream validation/persistence

    Does NOT:
    - Validate price or other fields (handled by PriceValidationPipeline)
    - Normalize product data (handled by NormalizationPipeline)
    """

    def __init__(self):
        self.db = None

    @classmethod
    def from_crawler(cls, crawler):
        return cls()

    async def open_spider(self, spider: scrapy.Spider):
        from connection import get_database
        self.db = await get_database()
        logger.info(f"StoreResolutionPipeline connected to MongoDB for spider {spider.name}")

    async def close_spider(self, spider: scrapy.Spider):
        logger.info(f"StoreResolutionPipeline closed for spider {spider.name}")

    async def process_item(self, item: Union[Dict, Any], spider: scrapy.Spider) -> Union[Dict, Any]:
        item_dict = dict(item) if hasattr(item, 'fields') else item

        chain = item_dict.get('store_chain')
        branch = item_dict.get('store_branch')

        if not chain:
            logger.warning("Missing store_chain on item — skipping store resolution")
            return item

        try:
            store = await self.db.stores.find_one({"chain": chain, "branch": branch})
            if store:
                store_id = str(store["_id"])
            else:
                result = await self.db.stores.insert_one({"chain": chain, "branch": branch})
                store_id = str(result.inserted_id)
                logger.info(f"Created new store: {chain} - {branch} (ID: {store_id})")

            item_dict['store_id'] = store_id

        except Exception as e:
            logger.error(f"Error resolving store for item: {e}", exc_info=True)
            # Don't fail the item — let validation pipeline drop it if store_id is genuinely missing

        if hasattr(item, 'fields'):
            for k, v in item_dict.items():
                item[k] = v
            return item
        return item_dict