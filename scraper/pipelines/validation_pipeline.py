"""
Validation pipeline for PricePoa scraping items.
Cleans, validates, and prepares price data for storage.
"""
import logging
from typing import Any, Dict, Union
import scrapy
from scrapy.exceptions import DropItem
from datetime import datetime

logger = logging.getLogger(__name__)


class PriceValidationPipeline:
    """
    Pipeline to validate and clean price scraping items.
    Ensures data quality before storage in MongoDB.
    """

    def process_item(self, item: Union[Dict, Any], spider: scrapy.Spider) -> Union[Dict, Any]:
        """
        Process and validate a price item.

        Args:
            item: Scraped item (dict or scrapy.Item)
            spider: Spider that scraped the item

        Returns:
            Validated and cleaned item

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

            # Clean and normalize data
            cleaned_item = self._clean_item(item_dict)

            # Additional business logic validation
            self._validate_business_rules(cleaned_item)

            # Add processing metadata
            cleaned_item['processed_at'] = datetime.utcnow()
            cleaned_item['processor'] = 'PriceValidationPipeline'

            # Return as same type as input
            if hasattr(item, 'fields'):
                # Return as scrapy.Item
                for key, value in cleaned_item.items():
                    item[key] = value
                return item
            else:
                return cleaned_item

        except DropItem:
            raise  # Re-raise DropItem exceptions
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

            # Special validation for price
            if field == 'price_kes':
                try:
                    price_val = float(value)
                    if price_val <= 0:
                        raise DropItem(f"Price must be positive, got: {price_val}")
                    # Ensure 2 decimal places
                    item[field] = round(price_val, 2)
                except (ValueError, TypeError):
                    raise DropItem(f"Invalid price value: {value}")

    def _clean_item(self, item: Dict) -> Dict:
        """Clean and normalize item data."""
        cleaned = item.copy()

        # Clean string fields
        string_fields = ['source', 'promotion_details']
        for field in string_fields:
            if field in cleaned and isinstance(cleaned[field], str):
                cleaned[field] = cleaned[field].strip()
                # Convert empty strings to None for optional fields
                if not cleaned[field] and field in ['promotion_details']:
                    cleaned[field] = None

        # Ensure boolean fields are proper booleans
        if 'is_promotional' in cleaned:
            promo_val = cleaned['is_promotional']
            if isinstance(promo_val, str):
                cleaned[is_promotional] = promo_val.lower() in ('true', 'yes', '1', 'on')
            elif not isinstance(promo_val, bool):
                cleaned['is_promotional'] = bool(promo_val)

        # Ensure timestamps are datetime objects
        if 'verified_at' in cleaned and isinstance(cleaned['verified_at'], str):
            try:
                from dateutil.parser import parse
                cleaned['verified_at'] = parse(cleaned['verified_at'])
            except ImportError:
                # Fallback if dateutil not available
                cleaned['verified_at'] = datetime.utcnow()
                logger.warning("dateutil not available, using current time for verified_at")
            except Exception as e:
                logger.warning(f"Could not parse verified_at '{cleaned['verified_at']}': {e}")
                cleaned['verified_at'] = datetime.utcnow()

        return cleaned

    def _validate_business_rules(self, item: Dict) -> None:
        """Apply business logic validation rules."""
        # Price sanity checks
        price = item.get('price_kes', 0)
        if price > 100000:  # More than 100,000 KSH seems unreasonable for groceries
            logger.warning(f"Unusually high price {price} for item {item.get('product_id')}")
            # Don't drop, just log - might be legitimate for bulk items

        # Source validation
        valid_sources = [
            'naivas_online', 'carrefour_online', 'quickmart_online',
            'chandarana_online', 'manual', 'api'
        ]
        source = item.get('source', '').lower()
        if source and source not in valid_sources:
            logger.warning(f"Unrecognized source '{source}', accepting anyway")

        # Promotional price validation
        if item.get('is_promotional', False) and not item.get('promotion_details'):
            logger.info(f"Promotional price without details: {item.get('product_id')}")

        # Timestamp reasonableness
        verified_at = item.get('verified_at')
        if hasattr(verified_at, 'year'):
            from datetime import datetime, timedelta
            now = datetime.utcnow()
            # Price shouldn't be from more than 1 year in future or 2 years in past
            if verified_at > now + timedelta(days=365):
                logger.warning(f"Price timestamp far in future: {verified_at}")
            if verified_at < now - timedelta(days=730):
                logger.warning(f"Price timestamp very old: {verified_at}")
