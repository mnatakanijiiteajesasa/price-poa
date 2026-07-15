"""
Scrapy spider for scraping prices from Chandarana Foodplus Online.
"""
import scrapy
from scrapy.http import Response
from typing import Generator, Dict, Any, Optional
import logging
from base_spider import BasePricePoaSpider

logger = logging.getLogger(__name__)


class ChandaranaSpider(BasePricePoaSpider):
    """Spider for scraping Chandarana Foodplus Online store."""
    
    name = 'chandarana_spider'
    allowed_domains = ['foodplus.co.ke']
    start_urls = [
        'https://foodplus.co.ke/fresh-food.html',
    ]

    # Domains that require JavaScript rendering
    js_domains = ['foodplus.co.ke']

    custom_settings = {
        'RETRY_TIMES': 2,
        'USER_AGENT': 'PricePoa Scraper - Chandarana (+https://pricepoa.co.ke)',
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.store_chain = "Chandarana"
        self.default_store_branch = "Online Store"

    def parse(self, response: Response) -> Generator[scrapy.Request, None, None]:
        """Parse Chandarana homepage and extract category links."""
        logger.info(f"Parsing Chandarana homepage: {response.url}")

        category_links = response.css(
            'a[href*="/shop/"]::attr(href), .category-link::attr(href), .menu-item a[href*="/category/"]::attr(href)'
        ).getall()

        for link in set(category_links):
            if link:
                yield response.follow(
                    url=link,
                    callback=self.parse_category,
                    meta={'use_playwright': self._needs_js(link)}
                )

    def parse_category(self, response: Response) -> Generator[scrapy.Request, None, None]:
        """Parse category page and extract product links."""
        logger.info(f"Parsing Chandarana category: {response.url}")

        product_links = response.css(
            '.product-item a::attr(href), .product-link::attr(href), a[href*="/item/"]::attr(href)'
        ).getall()

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
        logger.info(f"Parsing Chandarana product: {response.url}")

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
                                    'source': 'chandarana_online',
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
                'h1::text',
                '.product-title::text',
                '.product-name::text'
            ])

            category = self._extract_first(response, [
                '.breadcrumb li:last-child a::text',
                '.category-path::text'
            ]) or response.meta.get('category', 'General')

            price_text = self._extract_first(response, [
                '.price::text',
                '.current-price::text',
                '[data-testid="price"]::text',
                '.sale-price::text',
                '[class*="price"]::text'
            ])

            if not product_name or not price_text:
                logger.warning(f"Missing product name or price for {response.url}")
                return

            # Check for promotional details
            promo_selector = self._extract_first(response, [
                '.badge-offer, .label-sale, .promo-badge',
                '[data-testid="original-price"]',
                '.was-price::text'
            ])
            is_promotional = bool(promo_selector)

            promotion_details = None
            if is_promotional:
                promotion_details = self._extract_first(response, [
                    '.offer-details::text',
                    '.promo-text::text',
                    '.badge-offer::text'
                ])

            yield {
                'product_name': product_name,
                'store_chain': self.store_chain,
                'store_branch': response.meta.get('store_branch', self.default_store_branch),
                'price_kes': price_text,
                'source': 'chandarana_online',
                'is_promotional': is_promotional,
                'promotion_details': promotion_details,
                'response_url': response.url,
                'category': category
            }

        except Exception as e:
            logger.error(f"Error parsing Chandarana product {response.url}: {e}", exc_info=True)

    def _extract_first(self, response: Response, selectors: list) -> Optional[str]:
        """Extract trimmed text from the first selector that yields a match."""
        for selector in selectors:
            text = response.css(selector).get()
            if text:
                return text.strip()
        return None