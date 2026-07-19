"""
Scrapy spider for scraping prices from Naivas Online.
"""
import scrapy
from scrapy.http import Response
from typing import Generator, Dict, Any, Optional
from urllib.parse import urljoin
import re
import logging
from base_spider import BasePricePoaSpider

logger = logging.getLogger(__name__)


class NaivasSpider(BasePricePoaSpider):
    """Spider for scraping Naivas Online store."""
    
    name = 'naivas_spider'
    allowed_domains = ['naivas.online']
    start_urls = [
        'https://naivas.online',
    ]

    # Domains that require JavaScript rendering
    js_domains = ['naivas.online']

    custom_settings = {
        'RETRY_TIMES': 3,
        'USER_AGENT': 'PricePoa Scraper - Naivas (+https://pricepoa.co.ke)',
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.store_chain = "Naivas"
        self.default_store_branch = "Online Store"

    def parse(self, response: Response) -> Generator[scrapy.Request, None, None]:
        """Parse Naivas main page and extract category links.

        Verified 2026-07-19 via inspect_selectors.py: the category flyout
        renders into #mega-menu-full on every page load — it's CSS-hidden
        (off-canvas, translate-x-full) until the "categories" button is
        clicked, but the 72 links are already present in the DOM, so no
        click/JS-interaction is needed. Old selectors (nav a[href*="/category"]
        etc.) never matched anything on this platform.
        """
        logger.info(f"Parsing Naivas homepage: {response.url}")

        category_links = response.css('#mega-menu-full a::attr(href)').getall()

        if not category_links:
            logger.warning(f"Zero category links extracted from {response.url}")

        # Follow category links
        for link in set(category_links):
            if link:
                yield response.follow(
                    url=link,
                    callback=self.parse_category,
                    meta={'use_playwright': self._needs_js(link)}
                )

    def parse_category(self, response: Response) -> Generator[scrapy.Request, None, None]:
        """Parse category page and extract product links."""
        logger.info(f"Parsing Naivas category page: {response.url}")

        # Verified 2026-07-19 via inspect_selectors.py against /dairy: every
        # product's image sits inside a div.product-img, which is a real
        # semantic class (not a Tailwind utility), so it's the stable anchor
        # to select on. Old selectors (.product-item, .product-card, etc.)
        # never matched anything on this platform.
        product_links = response.css('.product-img a::attr(href)').getall()

        if not product_links:
            logger.warning(f"Zero product links extracted from {response.url}")

        for link in set(product_links):
            if link:
                yield response.follow(
                    url=link,
                    callback=self.parse_product,
                    meta={'use_playwright': self._needs_js(link)}
                )

        # Handle pagination
        next_page = response.css(
            'a[rel="next"]::attr(href), .next-page::attr(href), .pagination__next::attr(href)'
        ).get()
        if next_page:
            yield response.follow(
                url=next_page,
                callback=self.parse_category,
                meta={'use_playwright': self._needs_js(next_page)}
            )

    def parse_product(self, response: Response) -> Generator[Dict[str, Any], None, None]:
        """Parse individual product page and extract details."""
        logger.info(f"Parsing Naivas product: {response.url}")

        # 1. Try to parse from JSON-LD schema first (most reliable for Next.js/E-commerce apps)
        try:
            for script in response.xpath('//script[@type="application/ld+json"]/text()').getall():
                import json
                try:
                    data = json.loads(script)
                    data_list = data if isinstance(data, list) else [data]
                    for item in data_list:
                        if item.get('@type') == 'Product':
                            name = item.get('name')
                            offers = item.get('offers', {})
                            price = offers.get('price')
                            if name and price:
                                yield {
                                    'product_name': name.strip(),
                                    'store_chain': self.store_chain,
                                    'store_branch': response.meta.get('store_branch', self.default_store_branch),
                                    'price_kes': str(price),
                                    'source': 'naivas_online',
                                    'is_promotional': False,
                                    'promotion_details': None,
                                    'response_url': response.url,
                                    'category': response.meta.get('category', 'General')
                                }
                                return
                except Exception as e:
                    logger.debug(f"JSON-LD parsing block error: {e}")
        except Exception as e:
            logger.warning(f"Error checking JSON-LD: {e}")

        # 2. Fallback to CSS selectors if JSON-LD was missing or failed
        try:
            product_name = self._extract_first(response, [
                'h1 *::text',
                'h1.product-title::text',
                'h1[data-testid="product-title"]::text',
                '.product-name::text',
                'h1::text'
            ])

            category = self._extract_first(response, [
                '[data-testid="product-category"]::text',
                '.product-category::text',
                '.breadcrumb a:last-child::text',
                'nav ol li:last-child a::text'
            ]) or response.meta.get('category', 'General')

            price_text = self._extract_first(response, [
                '[data-testid="price"]::text',
                '.price-current::text',
                '.price-sale::text',
                '.price::text',
                '.cost::text',
                'span.price::text',
                '[class*="price"]::text'
            ])

            if not product_name or not price_text:
                logger.warning(f"Missing product name or price for {response.url}")
                return

            # Check for promotional details
            is_promotional = False
            promo_selector = self._extract_first(response, [
                '.badge-sale, .label-offer, .promo-tag',
                '[data-testid="price-original"]',
                '.price-was, .original-price'
            ])
            if promo_selector:
                is_promotional = True

            # Was/Now pricing pattern verification
            original_price = response.css('.price-was::text, .original-price::text').get()
            current_price = response.css('.price-current::text, .price-sale::text').get()
            if original_price and current_price:
                try:
                    orig = float(re.sub(r'[^\d.]', '', original_price))
                    curr = float(re.sub(r'[^\d.]', '', current_price))
                    if curr < orig:
                        is_promotional = True
                except ValueError:
                    pass

            promotion_details = None
            if is_promotional:
                promotion_details = self._extract_first(response, [
                    '.promo-details::text',
                    '.offer-text::text',
                    '[data-testid="promotion-details"]::text',
                    '.badge-sale::text, .label-offer::text'
                ])

            yield {
                'product_name': product_name,
                'store_chain': self.store_chain,
                'store_branch': response.meta.get('store_branch', self.default_store_branch),
                'price_kes': price_text,
                'source': 'naivas_online',
                'is_promotional': is_promotional,
                'promotion_details': promotion_details,
                'response_url': response.url,
                'category': category
            }

        except Exception as e:
            logger.error(f"Error parsing Naivas product {response.url}: {e}", exc_info=True)

    def _extract_first(self, response: Response, selectors: list) -> Optional[str]:
        """Extract trimmed text from the first selector that yields a match."""
        for selector in selectors:
            text = response.css(selector).get()
            if text:
                return text.strip()
        return None