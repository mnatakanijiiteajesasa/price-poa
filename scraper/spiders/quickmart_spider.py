"""
Scrapy spider for scraping prices from Quickmart Kenya Online.
"""
import scrapy
from scrapy.http import Response
from typing import Generator, Dict, Any, Optional
import logging
from scraper.base_spider import BasePricePoaSpider

logger = logging.getLogger(__name__)


class QuickmartSpider(BasePricePoaSpider):
    """Spider for scraping Quickmart Kenya Online store."""
    
    name = 'quickmart_spider'
    allowed_domains = ['quickmart.co.ke']
    start_urls = [
        'https://www.quickmart.co.ke/',
    ]

    # Domains that require JavaScript rendering
    js_domains = ['quickmart.co.ke']

    custom_settings = {
        'RETRY_TIMES': 2,
        'USER_AGENT': 'PricePoa Scraper - Quickmart (+https://pricepoa.co.ke)',
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.store_chain = "Quickmart"
        self.default_store_branch = "Online Store"
        self.location_gate_cookies = [
            {"name": "_ygShopId", "value": "67"},
            {"name": "_ygGeoAddress", "value": "Nakuru, Kenya"},
            {"name": "_ygGeoLat", "value": "-0.3030988"},
            {"name": "_ygGeoLng", "value": "36.080026"},
            {"name": "_ygGeoRadius", "value": "15"},
        ]

    def parse(self, response: Response) -> Generator[scrapy.Request, None, None]:
        """Parse Quickmart homepage and extract category links."""
        logger.info(f"Parsing Quickmart homepage: {response.url}")

        # Real markup uses flat slugs (e.g. /flour, /dairy-products), not /shop/...
        # Confirmed via rendered HTML inspection (category-menu-link.categoryMenuLinkJs)
        category_links = response.css(
            '.category-menu-link.categoryMenuLinkJs::attr(href)'
        ).getall()

        for link in set(category_links):
            # Skip the "all categories" toggle link, which isn't a real category page
            if link and 'btn-all-categories' not in link:
                yield response.follow(
                    url=link,
                    callback=self.parse_category,
                    meta={'use_playwright': self._needs_js(link)}
                )

    def parse_category(self, response: Response) -> Generator[scrapy.Request, None, None]:
        """Parse category page and extract product links."""
        logger.info(f"Parsing Quickmart category: {response.url}")

        # Real markup uses flat product slugs (e.g. /brookside-dairy-best-milk-500ml-22)
        # with no /product/ path segment. Container class confirmed via rendered HTML
        # inspection (.products.product-item). TODO: verify the <a> tag's exact position
        # inside this container (outer div vs. .products-img vs. .products-title) once
        # a full card's markup is confirmed — this selector assumes an <a> descendant
        # exists directly under .products.product-item.
        product_links = response.css(
            '.products.product-item a::attr(href)'
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
        logger.info(f"Parsing Quickmart product: {response.url}")

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
                                yield self.build_item(
                                    product_name=name.strip(),
                                    store_branch=response.meta.get('store_branch', self.default_store_branch),
                                    price_kes=str(price),
                                    source='quickmart_online',
                                    response_url=response.url,
                                    category=response.meta.get('category', 'General'),
                                )
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

            yield self.build_item(
                product_name=product_name,
                store_branch=response.meta.get('store_branch', self.default_store_branch),
                price_kes=price_text,
                source='quickmart_online',
                is_promotional=is_promotional,
                promotion_details=promotion_details,
                response_url=response.url,
                category=category,
            )

        except Exception as e:
            logger.error(f"Error parsing Quickmart product {response.url}: {e}", exc_info=True)

    def _extract_first(self, response: Response, selectors: list) -> Optional[str]:
        """Extract trimmed text from the first selector that yields a match."""
        for selector in selectors:
            text = response.css(selector).get()
            if text:
                return text.strip()
        return None