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
import sys
import os
from urllib.parse import urlparse

# Fix imports to work when script is run directly or as module
if __package__ is None or __package__ == '':
    # When run as a script, adjust the import path
    current_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(current_dir)
    sys.path.insert(0, parent_dir)
    from database.connection import get_database
    from database.models import Product, Store, Price
else:
    # When imported as a module
    from ..database.connection import get_database
    from ..database.models import Product, Store, Price

logger = logging.getLogger(__name__)


class BasePricePoaSpider(Spider):
    """
    Base spider for PricePoa scraping operations.
    Provides common functionality like JavaScript detection and store information.
    """
    name = 'base_pricepoa_spider'  # Abstract base spider, not meant to be run directly

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # These attributes are expected to be defined by child classes
        self.store_chain = getattr(self, 'store_chain', None)
        self.default_store_branch = getattr(self, 'default_store_branch', None)
        self.js_domains = getattr(self, 'js_domains', [])

    def _needs_js(self, url: str) -> bool:
        """
        Determine if a URL requires JavaScript rendering based on domain.

        Args:
            url: The URL to check

        Returns:
            True if the URL's domain is in js_domains, False otherwise
        """
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            # Remove port if present
            if ':' in domain:
                domain = domain.split(':')[0]
            return domain in self.js_domains
        except Exception as e:
            logger.warning(f"Error parsing URL {url} for JS detection: {e}")
            return False