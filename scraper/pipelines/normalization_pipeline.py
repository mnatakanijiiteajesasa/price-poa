"""
Refactored Normalization Pipeline for PricePoa Scraper.
Focuses solely on semantic normalization and product canonicalization.
Delegates validation to ValidationPipeline and persistence to MongoDBPipeline.
"""
import logging
import re
from typing import Dict, Any, Union, Optional
import scrapy
from datetime import datetime, timezone

# Import our new modular components
from .text_normalizer import TextNormalizer
from .attribute_extractor import AttributeExtractor
from .canonical_product_builder import CanonicalProductBuilder
from .alias_generator import AliasGenerator
from .embedding_text_builder import EmbeddingTextBuilder
from .models import ExtractedAttributes, CanonicalProduct, NormalizedProduct

# Import existing shared components
import sys
import os
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(current_dir, '..', 'database')))
sys.path.insert(0, os.path.abspath(os.path.join(current_dir, '..', '..', 'database')))
sys.path.insert(0, os.path.abspath(os.path.join(current_dir, '..', '..')))
from connection import get_database
from intelligence.outbox.outbox import EmbeddingOutboxService

logger = logging.getLogger(__name__)


class NormalizationPipeline:
    """
    Semantic normalization pipeline that extracts product attributes,
    builds canonical representations, and prepares data for validation and storage.

    Responsibilities:
    1. Text normalization (cleaning, standardization)
    2. Attribute extraction (brand, category, size, etc.)
    3. Canonical product construction
    4. Alias generation
    5. Embedding text creation
    6. Product matching/creation via outbox (transactional)

    Does NOT:
    - Validate data (handled by ValidationPipeline)
    - Directly write to MongoDB except through transactional outbox
    - Perform price validation or cleaning
    """

    def __init__(self):
        # Initialize our modular components
        self.text_normalizer = TextNormalizer()
        self.attribute_extractor = AttributeExtractor()
        self.canonical_builder = CanonicalProductBuilder()
        self.alias_generator = AliasGenerator()
        self.embedding_builder = EmbeddingTextBuilder()

        # Transactional product writer: keeps MongoDB and embedding outbox in sync
        self.outbox = EmbeddingOutboxService()

        # Database connection (initialized in open_spider)
        self.db = None

        logger.info("NormalizationPipeline (refactored) initialized")

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
        """Cleanup when spider closes."""
        logger.info(f"NormalizationPipeline closed for spider {spider.name}")

    async def process_item(self, item: Union[dict, Any], spider: scrapy.Spider) -> Union[Dict[Any, Any], Any]:
        """
        Process the scraped item, normalizing and canonicalizing product data.

        This method focuses ONLY on semantic normalization and product canonicalization.
        Validation and persistence are handled by separate pipelines.

        Args:
            item: Scraped item (dict or scrapy.Item)
            spider: Spider that scraped the item

        Returns:
            Item with normalized product data added
        """
        # Convert scrapy.Item to dict for uniform handling
        if hasattr(item, 'fields'):
            item_dict = dict(item)
        else:
            item_dict = item

        # Skip if missing essential fields (validation will catch these later)
        if not item_dict.get('product_name'):
            return item

        try:
            # Step 1: Extract and normalize attributes from product name
            raw_name = item_dict.get('product_name', '')
            attributes = self._extract_and_normalize_attributes(raw_name)

            # Step 2: Build canonical product representation
            canonical_product = self._build_canonical_product(attributes)

            # Step 3: Generate aliases
            canonical_product.aliases = self.alias_generator.generate_aliases(canonical_product)

            # Step 4: Generate embedding text
            canonical_product.embedding_text = self.embedding_builder.build_embedding_text(canonical_product)

            # Step 5: Find or create canonical product in database
            product_id = await self._get_or_create_canonical_product(canonical_product, item_dict)

            # Step 6: Create normalized product container
            normalized_product = NormalizedProduct(
                canonical_product=canonical_product,
                extracted_attributes=attributes,
                canonical_id=product_id,
                # Other fields will be filled by other pipelines:
                # - store_id: from store lookup (could be done here or in separate step)
                # - price: from price cleaning (should be done in validation or separate step)
                # - source, product_url, is_promotional, promotion_details: from item
            )

            # Add normalized data to item for downstream pipelines
            item['normalized_product'] = normalized_product
            item['product_id'] = str(product_id) if product_id else None

            # Note: Store ID lookup and price validation/cleaning should happen elsewhere
            # This pipeline focuses purely on product normalization

        except Exception as e:
            logger.error(f"Error normalizing product in NormalizationPipeline: {e}", exc_info=True)
            # Don't fail the item - let validation pipeline handle missing data

        # Return as same type as input
        if hasattr(item, 'fields'):
            for key, value in item_dict.items():
                item[key] = value
            return item
        else:
            return item_dict

    def _extract_and_normalize_attributes(self, raw_text: str) -> ExtractedAttributes:
        """Extract and normalize attributes from raw product text."""
        # Extract raw attributes
        attributes = self.attribute_extractor.extract_attributes(raw_text)

        # Normalize the text fields
        if attributes.raw_text:
            attributes.cleaned_text = self.text_normalizer.normalize_product(attributes.raw_text)

        # Normalize specific fields
        if attributes.brand:
            attributes.brand = self.text_normalizer.normalize_text(attributes.brand)
        if attributes.category:
            attributes.category = self.text_normalizer.normalize_text(attributes.category)
        if attributes.subcategory:
            attributes.subcategory = self.text_normalizer.normalize_text(attributes.subcategory)
        if attributes.unit:
            attributes.unit = self.text_normalizer.normalize_unit(attributes.unit)

        return attributes

    def _build_canonical_product(
    self,
    attributes: ExtractedAttributes
) -> CanonicalProduct:
    #Build a canonical product representation from extracted attribute.
        return self.canonical_builder.build_canonical_product(attributes)


    async def _get_or_create_canonical_product(self,
                                              canonical_product: CanonicalProduct,
                                              item_dict: dict) -> Optional[str]:
        """
        Find or create the canonical product in the database.
        Uses the transactional outbox service for consistency.

        Returns:
            Product ID if found/created, None otherwise
        """
        if self.db is None:
            logger.warning("Database not initialized")
            return None

        try:
            # Build search query based on canonical attributes
            query = {"name": {"$regex": f"^{re.escape(canonical_product.canonical_name)}$", "$options": "i"}}

            if canonical_product.brand:
                query["brand"] = canonical_product.brand

            # Look for existing product
            existing_product = await self.db.products.find_one(query)

            if existing_product:
                product_id = str(existing_product["_id"])

                # Update if we have new information to add
                update_fields = {}
                if canonical_product.size:
                    update_fields["$addToSet"] = {"sizes_variants": str(canonical_product.size)}
                # Note: We don't update store_links here - that's handled by price pipeline

                if update_fields:
                    await self.outbox.update_product_with_outbox(
                        product_id, update_fields, intent="update"
                    )

                return product_id
            else:
                # Create new product
                new_product_doc = {
                    "name": canonical_product.canonical_name,
                    "brand": canonical_product.brand,
                    "category": canonical_product.category,
                    # Note: subcategory would need to be stored somewhere -
                    # for now we might put it in a custom field or ignore
                    "sizes_variants": [str(canonical_product.size)] if canonical_product.size else [],
                    "store_links": {},  # Will be populated by price pipeline
                    # Add subcategory, variant, flavour fields to product schema if needed
                }

                product_id = await self.outbox.insert_product_with_outbox(
                    new_product_doc, intent="create"
                )

                logger.info(f"Created new canonical product: {canonical_product.canonical_name} (ID: {product_id})")
                return product_id

        except Exception as e:
            logger.error(f"Error in get_or_create_canonical_product: {e}", exc_info=True)
            return None