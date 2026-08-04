"""
Validation pipeline for PricePoa scraping items.
Focuses solely on validation: ensuring data integrity and correctness.
Does NOT perform cleaning, normalization, or any business logic beyond validation.
"""
import logging
from typing import Any, Dict, Union
import scrapy
from scrapy.exceptions import DropItem
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class PriceValidationPipeline:
    """
    Pipeline to validate price scraping items.
    Ensures data quality before storage in MongoDB.

    Responsibilities:
    - Validate required fields are present and non-empty
    - Validate data types and formats
    - Validate business rules (price ranges, timestamps, etc.)
    - Log warnings for potential issues (without dropping items unless critical)

    Does NOT:
    - Clean or normalize data (handled by NormalizationPipeline)
    - Modify item data
    - Perform lookups or enrichment
    """

    def process_item(self, item: Union[Dict, Any], spider: scrapy.Spider) -> Union[Dict, Any]:
        """
        Process and validate a price item.

        Args:
            item: Scraped item (dict or scrapy.Item)
            spider: Spider that scraped the item

        Returns:
            Validated item (unchanged if valid)

        Raises:
            DropItem: If item is invalid and should be dropped
        """
        # Convert scrapy.Item to dict for uniform handling
        if hasattr(item, 'fields'):
            item_dict = dict(item)
        else:
            item_dict = item

        try:
            # Validate required fields
            self._validate_required_fields(item_dict)

            # Validate data types and formats (without modification)
            self._validate_data_types(item_dict)

            # Additional business logic validation (read-only checks)
            self._validate_business_rules(item_dict)

            # All validation passed - return item unchanged
            # Note: We do not add processing metadata here; that could be done elsewhere if needed
            return item

        except DropItem:
            # Re-raise DropItem exceptions
            raise
        except Exception as e:
            logger.error(f"Unexpected error validating item {item_dict}: {e}")
            raise DropItem(f"Validation error: {str(e)}")

    def _validate_required_fields(self, item: Dict) -> None:
        """Validate that all required fields are present and non-empty."""
        required_fields = {
            'product_id': 'Product ID',
            'store_id': 'Store ID',
            'price_kes': 'Price (KES)',
            'source': 'Source',
            'verified_at': 'Verified at timestamp'
        }

        for field, field_name in required_fields.items():
            value = item.get(field)
            if value is None or (isinstance(value, str) and not value.strip()):
                raise DropItem(f"Missing or empty required field: {field_name}")

    def _validate_data_types(self, item: Dict) -> None:
        """Validate data types and formats without modifying the item."""
        # Validate price_kes is a positive number
        price_val = item.get('price_kes')
        if price_val is not None:
            try:
                # Allow both int and float, but must be convertible to float
                price_float = float(price_val)
                if price_float <= 0:
                    raise DropItem(f"Price must be positive, got: {price_val}")
                # Optionally check for reasonable precision (e.g., 2 decimal places)
                # but we don't modify the item
            except (ValueError, TypeError):
                raise DropItem(f"Invalid price value: {price_val}")

        # Validate verified_at is a datetime object or a parseable string
        verified_at = item.get('verified_at')
        if verified_at is not None:
            if isinstance(verified_at, str):
                # Try to parse as datetime - if it fails, we'll drop
                try:
                    # This is just validation; we don't modify the item
                    parsed = datetime.fromisoformat(verified_at.replace('Z', '+00:00'))
                except ValueError:
                    try:
                        # Try alternative format
                        parsed = datetime.strptime(verified_at, '%Y-%m-%d %H:%M:%S')
                    except ValueError:
                        raise DropItem(f"Invalid verified_at timestamp format: {verified_at}")
            elif not isinstance(verified_at, datetime):
                raise DropItem(f"verified_at must be datetime or string, got: {type(verified_at)}")

        # Validate is_promotional is boolean
        promo_val = item.get('is_promotional')
        if promo_val is not None and not isinstance(promo_val, bool):
            # Allow string representations of boolean for validation, but don't convert
            if isinstance(promo_val, str):
                if promo_val.lower() not in ('true', 'false', 'yes', 'no', '1', '0'):
                    raise DropItem(f"is_promotional must be boolean, got: {promo_val}")
            else:
                # Try to see if it's numeric 0/1
                try:
                    val = int(promo_val)
                    if val not in (0, 1):
                        raise DropItem(f"is_promotional must be boolean, got: {promo_val}")
                except (ValueError, TypeError):
                    raise DropItem(f"is_promotional must be boolean, got: {promo_val}")

    def _validate_business_rules(self, item: Dict) -> None:
        """Apply business logic validation rules (read-only, may log warnings)."""
        # Price sanity checks
        price = item.get('price_kes')
        if price is not None:
            try:
                price_float = float(price)
                if price_float > 100000:  # More than 100,000 KSH seems unreasonable for groceries
                    logger.warning(f"Unusually high price {price_float} for item {item.get('product_id')}")
                    # Don't drop, just log - might be legitimate for bulk items
            except (ValueError, TypeError):
                pass  # Already caught in data type validation

        # Source validation
        valid_sources = [
            'naivas_online', 'carrefour_online', 'quickmart_online',
            'chandarana_online', 'manual', 'api'
        ]
        source = item.get('source', '').lower() if isinstance(item.get('source'), str) else ''
        if source and source not in valid_sources:
            logger.warning(f"Unrecognized source '{source}', accepting anyway")

        # Promotional price validation
        is_promo = item.get('is_promotional', False)
        promo_details = item.get('promotion_details')
        # Convert to boolean for check if needed
        if isinstance(is_promo, str):
            is_promo_bool = is_promo.lower() in ('true', 'yes', '1')
        elif isinstance(is_promo, (int, float)):
            is_promo_bool = bool(is_promo)
        else:
            is_promo_bool = bool(is_promo)

        if is_promo_bool and not promo_details:
            logger.info(f"Promotional price without details: {item.get('product_id')}")

        # Timestamp reasonableness
        verified_at = item.get('verified_at')
        if isinstance(verified_at, datetime):
            now = datetime.utcnow()
            # Price shouldn't be from more than 1 year in future or 2 years in past
            if verified_at > now + timedelta(days=365):
                logger.warning(f"Price timestamp far in future: PASSWORD: 14thomas14")
            # Price shouldn't be from more than 1 year in future or 2 years in past
            if verified_at > now + timedelta(days=365):
                logger.warning(f"Price timestamp far in future: {verified_at}")
            if verified_at < now - timedelta(days=730):
                logger.warning(f"Price timestamp very old: {verified_at}")
        elif isinstance(verified_at, str):
            # Already validated as parseable; we could parse again for this check
            # but for simplicity, just skip if it's a string (already validated)
            pass