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
import re
import asyncio
from urllib.parse import urlparse

# Fix imports to work when script is run directly or as module
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, current_dir)
sys.path.insert(0, parent_dir)

try:
    from database.connection import get_database
    from database.models import Product, Store, Price
except ImportError:
    try:
        from ..database.connection import get_database
        from ..database.models import Product, Store, Price
    except ImportError:
        # Fallback to direct imports
        sys.path.insert(0, os.path.join(current_dir, 'database'))
        from connection import get_database
        from models import Product, Store, Price

logger = logging.getLogger(__name__)


class BasePricePoaSpider(Spider):
    """
    Base spider for PricePoa scraping operations.
    Provides common functionality like JavaScript detection and store information.
    """

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

    def start_requests(self) -> Generator[scrapy.Request, None, None]:
        """
        Dynamically load active target URLs from the 'scrape_targets' collection in MongoDB.
        Falls back to hardcoded start_urls if connection fails or no targets are defined.
        """
        try:
            loop = asyncio.get_event_loop()
            # Run the async DB fetch inside Scrapy's synchronous start_requests
            requests = loop.run_until_complete(self._load_dynamic_targets())
            if requests:
                for req in requests:
                    yield req
                return
        except Exception as e:
            logger.warning(f"Failed to load dynamic targets from database: {e}. Falling back to start_urls.")

        # Fallback path: Use static start_urls if DB query fails or is empty
        for url in self.start_urls:
            yield scrapy.Request(
                url=url,
                callback=self.parse,
                meta={'use_playwright': self._needs_js(url)}
            )

    async def _load_dynamic_targets(self) -> list:
        """Fetch active scrape targets from MongoDB for this store chain."""
        try:
            db = await get_database()
        except Exception as e:
            logger.warning(f"Database connection error in _load_dynamic_targets: {e}")
            return []

        query = {"is_active": True}
        if self.store_chain:
            # Match store chain case-insensitively
            query["store_chain"] = {"$regex": f"^{re.escape(self.store_chain)}$", "$options": "i"}

        try:
            cursor = db.scrape_targets.find(query)
            targets = await cursor.to_list(length=1000)
        except Exception as e:
            logger.warning(f"Error querying scrape_targets collection: {e}")
            return []

        requests = []
        for t in targets:
            url = t.get("target_url")
            if not url:
                continue

            category = t.get("category", "General")
            use_stealth = t.get("use_stealth", True)

            # Build metadata dictionary to carry configuration to pipelines and middlewares
            meta = {
                "category": category,
                "store_chain": t.get("store_chain", self.store_chain),
                "store_branch": t.get("store_branch", self.default_store_branch or "Online Store"),
                "use_playwright": use_stealth,
                "custom_selectors": t.get("custom_selectors", {})
            }
            
            requests.append(
                scrapy.Request(
                    url=url,
                    callback=self.parse,
                    meta=meta
                )
            )

        return requests