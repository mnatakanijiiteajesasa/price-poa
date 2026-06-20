"""
Scrapy spider for scraping prices from Naivas Online.
Implements product extraction and price data collection.
"""
import scrapy
from typing import Generator, Dict, Any, Optional
from urllib.parse import urljoin, urlparse
import re
import logging
from ..base_spider import BasePricePoaSpider
from ..middleware.playwright_middleware import PlaywrightMiddleware


class NaivasSpider(BasePricePoaSpider):
    """
    Spider for scraping Naivas Online store (naivas.online).
    Handles both regular HTML and JavaScript-rendered content.
    """

    name = 'naivas_spider'
    allowed_domains = ['naivas.online']
    start_urls = [
        'https://naivas.online/',
        # Add specific category URLs as needed
        'https://naivas.online/supermarket',
        'https://naivas.online/groceries',
        'https://naivas.online/fresh-foods',
    ]

    # Domains that require JavaScript rendering
    js_domains = ['naivas.online']

    custom_settings = {
        'DOWNLOAD_DELAY': 2,
        'RANDOMIZE_DOWNLOAD_DELAY': True,
        'CONCURRENT_REQUESTS': 8,
        'CONCURRENT_REQUESTS_PER_DOMAIN': 4,
        'RETRY_TIMES': 3,
        'USER_AGENT': 'PricePoa Scraper - Naivas (+https://pricepoa.co.ke)',
        # Enable our middlewares
        'DOWNLOADER_MIDDLEWARES': {
            'scraper.middleware.playwright_middleware.PlaywrightMiddleware': 543,
            'scraper.middleware.deduplication_middleware.PriceDeduplicationMiddleware': 544,
        },
        'ITEM_PIPELINES': {
            'scraper.pipelines.validation_pipeline.PriceValidationPipeline': 300,
            'scraper.pipelines.mongodb_pipeline.MongoDBPipeline': 400,
        },
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.store_chain = "Naivas"
        # In a real implementation, you might want to load specific store branches
        # from configuration or database
        self.default_store_branch = "Online Store"

    def parse(self, response: scrapy.Response) -> Generator[Dict[str, Any], None, None]:
        """
        Parse the main page and extract category links.
        """
        logger = logging.getLogger(__name__)
        logger.info(f"Parsing Naivas main page: {response.url}")

        # Extract category links from navigation or homepage
        category_links = response.css(
            'nav a[href*="/category"], .menu-item a[href*="/shop"], .category-link'
        )::attr('href').getall()

        # Also look for category images or banners
        category_links += response.css(
            '.category-banner a, .product-category a, [class*="category"] a'
        )::attr('href').getall()

        # If no specific category links found, try to infer from common patterns
        if not category_links:
            category_links = response.css('a[href*]').re(r'/category/[\w\-/]+')

        # Follow category links
        for link in set(category_links):  # Remove duplicates
            if link and not link.startswith('http'):
                link = urljoin(response.url, link)
            yield scrapy.Request(
                url=link,
                callback=self.parse_category,
                meta={'use_playwright': True} if self._needs_js(link) else {}
            )

    def parse_category(self, response: scrapy.Response) -> Generator[Dict[str, Any], None, None]:
        """
        Parse a category page and extract product links.
        """
        logger = logging.getLogger(__name__)
        logger.info(f"Parsing Naivas category page: {response.url}")

        # Extract product links
        product_links = response.css(
            '.product-item a, .product-link, [data-testid="product-link"]'
        )::attr('href').getall()

        # Fallback selectors
        if not product_links:
            product_links = response.css(
                '.product-card a, .item-link, a[href*="/product/"]'
            )::attr('href').getall()

        # Follow product links
        for link in set(product_links):
            if link and not link.startswith('http'):
                link = urljoin(response.url, link)
            yield scrapy.Request(
                url=link,
                callback=self.parse_product,
                meta={'use_playwright': True} if self._needs_js(link) else {}
            )

        # Handle pagination
        next_page = response.css(
            'a[rel="next"], .next-page, .pagination__next'
        )::attr('href').get()
        if next_page:
            if not next_page.startswith('http'):
                next_page = urljoin(response.url, next_page)
            yield scrapy.Request(
                url=next_page,
                callback=self.parse_category,
                meta={'use_playwright': True} if self._needs_js(next_page) else {}
            )

    def parse_product(self, response: scrapy.Response) -> Generator[Dict[str, Any], None, None]:
        """
        Parse individual product page and extract price information.
        """
        logger = logging.getLogger(__name__)
        logger.info(f"Parsing Naivas product page: {response.url}")

        try:
            # Extract product information
            product_name = self._extract_product_name(response)
            category = self._extract_category(response)
            price_text = self._extract_price(response)
            is_promotional = self._is_promotional(response)
            promotion_details = self._extract_promotion_details(response) if is_promotional else None

            if not product_name or price_text is None:
                logger.warning(f"Could not extract product name or price from {response.url}")
                return

            # Parse price
            price = self._parse_price(price_text)
            if price is None:
                logger.warning(f"Could not parse price from text: {price_text}")
                return

            # Generate item
            item = {
                'product_name': product_name.strip(),
                'category': category.strip() if category else 'General',
                'store_chain': self.store_chain,
                'store_branch': self.default_store_branch,
                'price_kes': price,
                'source': 'naivas_online',
                'is_promotional': bool(is_promotional),
                'promotion_details': promotion_details,
                'scraped_at': response.meta.get('download_latency', 0),
                'response_url': response.url
            }

            # Process through base spider validation
            # Note: In practice, the validation pipeline will handle most of this
            yield item

        except Exception as e:
            logger.error(f"Error parsing product page {response.url}: {e}")

    def _extract_product_name(self, response: scrapy.Response) -> Optional[str]:
        """Extract product name from page."""
        selectors = [
            'h1.product-title::text',
            'h1[data-testid="product-title"]::text',
            '.product-name::text',
            'h1::text'
        ]

        for selector in selectors:
            text = response.css(selector).get()
            if text and text.strip():
                return text.strip()
        return None

    def _extract_category(self, response: scrapy.Response) -> Optional[str]:
        """Extract product category from page."""
        selectors = [
            '[data-testid="product-category"]::text',
            '.product-category::text',
            '.breadcrumb a:last-child::text',
            'nav ol li:last-child a::text'
        ]

        for selector in selectors:
            text = response.css(selector).get()
            if text and text.strip():
                return text.strip()
        return None

    def _extract_price(self, response: scrapy.Response) -> Optional[str]:
        """Extract price text from page."""
        selectors = [
            '[data-testid="price"]::text',
            '.price-current::text',
            '.price-sale::text',
            '.price::text',
            '.cost::text',
            'span.price::text'
        ]

        for selector in selectors:
            text = response.css(selector).get()
            if text:
                return text.strip()
        return None

    def _is_promotional(self, response: scrapy.Response) -> bool:
        """Check if product is on promotion."""
        promo_indicators = [
            '.badge-sale, .label-offer, .promo-tag',
            '[data-testid="price-original"]',  # Original price indicates sale
            '.price-was, .original-price',
            'text*=Sale, text*=Offer, text*=Discount'
        ]

        for indicator in promo_indicators:
            if response.css(indicator):
                return True

        # Check for "Was/Know" pricing pattern
        original_price = response.css('.price-was::text, .original-price::text').get()
        current_price = response.css('.price-current::text, .price-sale::text').get()
        if original_price and current_price:
            try:
                orig = float(re.sub(r'[^\d.]', '', original_price))
                curr = float(re.sub(r'[^\d.]', '', current_price))
                return curr < orig  # Current price less than original = sale
            except ValueError:
                pass

        return False

    def _extract_promotion_details(self, response: scrapy.Response) -> Optional[str]:
        """Extract promotion details if available."""
        selectors = [
            '.promo-details::text',
            '.offer-text::text',
            '[data-testid="promotion-details"]::text',
            '.badge-sale::text, .label-offer::text'
        ]

        for selector in selectors:
            text = response.css(selector).get()
            if text and text.strip():
                return text.strip()
        return None

    def _parse_price(self, price_text: str) -> Optional[float]:
        """Parse price text into float value."""
        if not price_text:
            return None

        # Remove currency symbols and extra text
        cleaned = re.sub(r'[^\d\.]', '', price_text)
        try:
            return float(cleaned)
        except ValueError:
            # Try to extract first number if multiple present
            numbers = re.findall(r'\d+(?:\.\d+)?', price_text)
            if numbers:
                try:
                    return float(numbers[0])
                except ValueError:
                    pass
        return None

    def _needs_js(self, url: str) -> bool:
        """Determine if URL needs JavaScript rendering."""
        parsed = urlparse(url)
        return any(domain in parsed.netloc for domain in self.js_domains)