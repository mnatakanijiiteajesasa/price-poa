"""
Scrapy spider for scraping prices from The Bar Kenya Online.
"""
import scrapy
from scrapy.http import Response
from typing import Generator, Dict, Any, Optional
import logging
from base_spider import BasePricePoaSpider

logger = logging.getLogger(__name__)


class TheBarSpider(BasePricePoaSpider):
    """Spider for scraping The Bar Kenya Online store."""

    name = 'thebar_spider'
    allowed_domains = ['ke.thebar.com']
    start_urls = [
        'https://ke.thebar.com/collections/party'
    ]

    # Domains that require JavaScript rendering
    js_domains = ['ke.thebar.com']

    custom_settings = {
        'RETRY_TIMES': 2,
        'USER_AGENT': 'PricePoa Scraper - The Bar (+https://pricepoa.co.ke)',
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.store_chain = "The Bar"
        self.default_store_branch = "Online Store"

    def parse(self, response: Response) -> Generator[scrapy.Request, None, None]:
        """Parse The Bar homepage and extract product links."""
        logger.info(f"Parsing The Bar party collection: {response.url}")

        # Try to extract product links from the page
        # The site uses Vue.js, so we look for common product link patterns
        product_links = response.css(
            'a[href*="/products/"]::attr(href), .product-item a::attr(href), .product-link::attr(href)'
        ).getall()

        # If no product links found, try to look for product data in JSON-LD or window state
        if not product_links:
            logger.warning(f"No product links found via CSS selectors, trying alternative methods")
            # We'll try to extract product data directly from the page if possible
            # For now, we'll log and return, but in a real scenario we might need to adjust selectors
            pass

        for link in set(product_links):
            if link:
                # Ensure the link is absolute
                if link.startswith('/'):
                    link = f"https://ke.thebar.com{link}"
                yield response.follow(
                    url=link,
                    callback=self.parse_product,
                    meta={'use_playwright': self._needs_js(link)}
                )

        # Handle pagination if present
        next_page = response.css(
            'a[rel="next"]::attr(href), .next-page::attr(href), .pagination__next::attr(href)'
        ).get()
        if next_page:
            if next_page.startswith('/'):
                next_page = f"https://ke.thebar.com{next_page}"
            yield response.follow(
                url=next_page,
                callback=self.parse,
                meta={'use_playwright': self._needs_js(next_page)}
            )

    def parse_product(self, response: Response) -> Generator[Dict[str, Any], None, None]:
        """Parse individual product page and extract details."""
        logger.info(f"Parsing The Bar product: {response.url}")

        # 1. Try to parse from JSON-LD schema first (most reliable for modern JS apps)
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
                                    'source': 'thebar_online',
                                    'is_promotional': False,
                                    'promotion_details': None,
                                    'response_url': response.url,
                                    'category': 'Party'  # As requested, save under Party category
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
                'h1::text',
                '.product-title::text',
                '.product-name::text'
            ])

            # For category, we know it's Party from the collection, but we can also try to extract from breadcrumb
            category = self._extract_first(response, [
                '.breadcrumb li:last-child a::text',
                '.category-path::text',
                '[data-testid="category"]::text'
            ]) or 'Party'  # Default to Party as requested

            price_text = self._extract_first(response, [
                '.price-current::text',
                '.sales-price::text',
                '[data-testid="price"]::text',
                '.price::text',
                '[class*="price"]::text'
            ])

            if not product_name or not price_text:
                logger.warning(f"Missing product name or price for {response.url}")
                return

            # Check for promotional details
            promo_selector = self._extract_first(response, [
                '.badge-sale, .label-offer, .promo-tag',
                '[data-testid="price-original"]',
                '.was-price::text'
            ])
            is_promotional = bool(promo_selector)

            promotion_details = None
            if is_promotional:
                promotion_details = self._extract_first(response, [
                    '.promo-details::text',
                    '.offer-text::text',
                    '.badge-sale::text, .label-offer::text'
                ])

            yield {
                'product_name': product_name,
                'store_chain': self.store_chain,
                'store_branch': response.meta.get('store_branch', self.default_store_branch),
                'price_kes': price_text,
                'source': 'thebar_online',
                'is_promotional': is_promotional,
                'promotion_details': promotion_details,
                'response_url': response.url,
                'category': category
            }

        except Exception as e:
            logger.error(f"Error parsing The Bar product {response.url}: {e}", exc_info=True)

    def _extract_first(self, response: Response, selectors: list) -> Optional[str]:
        """Extract trimmed text from the first selector that yields a match."""
        for selector in selectors:
            text = response.css(selector).get()
            if text:
                return text.strip()
        return None