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