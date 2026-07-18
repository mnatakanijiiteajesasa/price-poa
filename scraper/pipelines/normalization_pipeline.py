"""
Data Normalization and Product Matching Pipeline for PricePoa Scraper.
Standardizes scraped prices, categories, and attributes, matches items to canonical products, 
and persists clean records to MongoDB collections.
"""
import logging
import re
import sys
import os
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple, Union
import scrapy
from bson import ObjectId

# Adjust import path to load shared database connection
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(current_dir, '..', 'database')))
sys.path.insert(0, os.path.abspath(os.path.join(current_dir, '..', '..', 'database')))
from connection import get_database

logger = logging.getLogger(__name__)


class NormalizationPipeline:
    """
    Standardization pipeline that extracts product properties, standardizes categories,
    matches items to canonical products, and records price histories.
    """

    def __init__(self):
        self.db = None
        self.buffer = []
        logger.info("NormalizationPipeline initialized")

    @classmethod
    def from_crawler(cls, crawler):
        """Create pipeline instance from crawler."""
        return cls()

    async def open_spider(self, spider: scrapy.Spider):
        """Initialize MongoDB connection when spider opens."""
        try:
            self.db = await get_database()
            logger.info(f"NormalizationPipeline connected to MongoDB for spider {spider.name}")
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB in NormalizationPipeline: {e}")
            raise

    async def close_spider(self, spider: scrapy.Spider):
        """Flush remaining items when spider closes."""
        logger.info(f"NormalizationPipeline closed for spider {spider.name}")

    async def process_item(self, item: Union[Dict, Any], spider: scrapy.Spider) -> Union[Dict, Any]:
        """
        Process the scraped item, matching it against canonical models and saving it to MongoDB.
        """
        if self.db is None:
            return item

        # Convert scrapy.Item to python dict
        item_dict = dict(item) if hasattr(item, 'fields') else item

        try:
            # 1. Clean and normalize price
            price_text = item_dict.get('price_kes')
            if price_text is None:
                logger.warning(f"Drop item: missing price inside {item_dict.get('response_url')}")
                return item

            price = self._clean_price(price_text)
            if price is None:
                logger.warning(f"Drop item: invalid price string '{price_text}'")
                return item

            # 2. Extract brand, size, and clean title from raw name
            raw_name = item_dict.get('product_name', '')
            if not raw_name:
                logger.warning(f"Drop item: missing product name inside {item_dict.get('response_url')}")
                return item

            clean_name, brand, size = self._parse_product_attributes(raw_name)

            # 3. Translate category dynamically from category_mappings collection
            raw_category = item_dict.get('category', 'General')
            canonical_category = await self._get_canonical_category(raw_category)

            # 4. Find or create the Store ID mapping
            store_chain = item_dict.get('store_chain', 'General')
            store_branch = item_dict.get('store_branch', 'Online Store')
            store_id = await self._get_or_create_store(store_chain, store_branch)

            # 5. Lookup or create the Canonical Product in database
            product_id = await self._get_or_create_canonical_product(
                clean_name=clean_name,
                brand=brand,
                size=size,
                category=canonical_category,
                store_id=store_id,
                product_url=item_dict.get('response_url', '')
            )

            # 6. Insert / Update the Daily Price snapshot (Deduplicated daily)
            await self._save_price_record(
                product_id=product_id,
                store_id=store_id,
                price=price,
                source=item_dict.get('source', 'unknown'),
                product_url=item_dict.get('response_url', ''),
                is_promotional=item_dict.get('is_promotional', False),
                promotion_details=item_dict.get('promotion_details')
            )

            # Write resolved values back to original item object for subsequent pipelines (e.g. Validation)
            item['product_id'] = str(product_id)
            item['store_id'] = str(store_id)
            item['price_kes'] = price
            item['verified_at'] = datetime.utcnow()

        except Exception as e:
            logger.error(f"Error processing item inside NormalizationPipeline: {e}", exc_info=True)

        return item

    def _clean_price(self, price_val: Union[str, float, int]) -> Optional[float]:
        """Convert raw price strings (e.g. 'KES 1,200.50') into clean float values."""
        if isinstance(price_val, (int, float)):
            return float(price_val)
        if not price_val:
            return None
        try:
            # Remove currency, commas, and other non-digit values except dots
            cleaned = re.sub(r'[^\d\.]', '', str(price_val))
            return float(cleaned)
        except ValueError:
            # Fallback regex extraction of first matching number
            numbers = re.findall(r'\d+(?:\.\d+)?', str(price_val))
            if numbers:
                try:
                    return float(numbers[0])
                except ValueError:
                    pass
        return None

    def _parse_product_attributes(self, raw_title: str) -> Tuple[str, Optional[str], Optional[str]]:
        """
        Parse raw product titles to isolate Clean Name, Brand, and Size/Volume variant.
        Example: "Broadways White Bread - 400g" -> ("White Bread", "Broadways", "400g")
        """
        # 1. Normalize spaces
        title = re.sub(r'\s+', ' ', raw_title).strip()

        # 2. Extract Size (e.g., 400g, 500ml, 1 L, 2 Litres, 10 Pcs)
        size_pattern = r'(\d+(?:\.\d+)?\s*(?:g|kg|ml|l|litre|litres|pcs|packs|pc|pieces))\b'
        size_match = re.search(size_pattern, title, re.IGNORECASE)
        size = size_match.group(1).replace(" ", "").lower() if size_match else None

        if size_match:
            title = title.replace(size_match.group(0), "")

        # 3. Match Brand against common Kenyan brands
        known_brands = [
            "broadways", "bidco", "brookside", "naivas", "carrefour", "quickmart", 
            "daisy", "kelloggs", "nestle", "pampers", "huggies", "unilever", "cadbury",
            "kapa", "soko", "jogoo", "pembe", "exe", "chapa mandashi", "ketepa", "kericho gold"
        ]
        brand = None
        for b in known_brands:
            if re.search(r'\b' + re.escape(b) + r'\b', title, re.IGNORECASE):
                brand = b.capitalize()
                title = re.sub(r'\b' + re.escape(b) + r'\b', "", title, flags=re.IGNORECASE)
                break

        # Clean trailing and leading punctuation
        clean_title = re.sub(r'[-\s,]+$', '', re.sub(r'^[-\s,]+', '', title)).strip()
        return clean_title, brand, size

    async def _get_canonical_category(self, raw_category: str) -> str:
        """
        Queries the database mappings table dynamically.
        Creates a new mapped category placeholder if none exists.
        """
        category_key = raw_category.strip().lower()
        if not category_key:
            return "General"

        # Query MongoDB mapping
        mapping = await self.db.category_mappings.find_one({"raw_category": category_key})
        if mapping:
            return mapping.get("canonical_category", "General")

        # Create unmapped placeholder entry so admin can configure it later
        new_mapping = {
            "raw_category": category_key,
            "canonical_category": "Unmapped",  # Needs admin manual mapping
            "suggested_category": raw_category.strip(),
            "created_at": datetime.now(timezone.utc)
        }
        await self.db.category_mappings.insert_one(new_mapping)
        logger.info(f"Registered new unmapped category: '{raw_category}'")
        return "Unmapped"

    async def _get_or_create_store(self, chain_name: str, branch_name: str) -> str:
        """Fetch or create store record in database."""
        store = await self.db.stores.find_one({
            "chain_name": {"$regex": f"^{re.escape(chain_name)}$", "$options": "i"},
            "branch_name": {"$regex": f"^{re.escape(branch_name)}$", "$options": "i"}
        })
        if store:
            return str(store["_id"])

        # Insert placeholder store
        new_store = {
            "chain_name": chain_name,
            "branch_name": branch_name,
            "town": "Nairobi",  # Default values
            "county": "Nairobi",
            "is_active": True,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc)
        }
        res = await self.db.stores.insert_one(new_store)
        return str(res.inserted_id)

    async def _get_or_create_canonical_product(
        self, clean_name: str, brand: Optional[str], size: Optional[str], category: str, store_id: str, product_url: str
    ) -> str:
        """
        Matches standard title against products collection.
        Saves store specific link to product document to avoid duplicate crawl entities.
        """
        query = {"name": {"$regex": f"^{re.escape(clean_name)}$", "$options": "i"}}
        if brand:
            query["brand"] = brand

        product = await self.db.products.find_one(query)
        
        # Build updates
        update_fields = {}
        if size:
            update_fields["$addToSet"] = {"sizes_variants": size}
        if product_url:
            update_fields["$set"] = {f"store_links.{store_id}": product_url}

        if product:
            product_id = product["_id"]
            if update_fields:
                await self.db.products.update_one({"_id": product_id}, update_fields)
            return str(product_id)

        # Create new product record
        new_product = {
            "name": clean_name,
            "brand": brand,
            "category": category,
            "sizes_variants": [size] if size else [],
            "swahili_aliases": [],
            "sheng_aliases": [],
            "store_links": {store_id: product_url} if product_url else {},
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc)
        }
        res = await self.db.products.insert_one(new_product)
        return str(res.inserted_id)

    async def _save_price_record(
        self, product_id: str, store_id: str, price: float, source: str, product_url: str, is_promotional: bool, promotion_details: Optional[str]
    ):
        """Save price point, grouping prices daily to prevent duplicates on same date."""
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

        price_doc = {
            "product_id": product_id,
            "store_id": store_id,
            "price_kes": price,
            "source": source,
            "product_url": product_url,
            "is_promotional": is_promotional,
            "promotion_details": promotion_details,
            "verified_at": datetime.now(timezone.utc),
            "created_at": datetime.now(timezone.utc)
        }

        # Query if price is already written today
        filter_criteria = {
            "product_id": product_id,
            "store_id": store_id,
            "source": source,
            "created_at": {"$gte": today_start}
        }

        # Update if exists, else insert
        res = await self.db.prices.update_one(
            filter_criteria,
            {
                "$set": {
                    "price_kes": price,
                    "product_url": product_url,
                    "is_promotional": is_promotional,
                    "promotion_details": promotion_details,
                    "verified_at": datetime.now(timezone.utc)
                },
                "$setOnInsert": {"created_at": datetime.now(timezone.utc)}
            },
            upsert=True
        )
        logger.debug(f"Saved price record to MongoDB (upsert={res.upserted_id is not None})")
