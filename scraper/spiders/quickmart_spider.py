"""
Scrapy spider for scraping prices from Quickmart Online.
"""
import scrapy
import logging
import re
from ..base_spider import BasePricePoaSpider
from ..middleware.playwright_middleware import PlaywrightMiddleware


class QuickmartSpider(BasePricePoaSpider):
    """
    Spider for scraping Quickmart Online store.
    """

    name = 'quickmart_spider'
    allowed_domains = ['quickmart.co.ke']
    start_urls = [
        'https://www.quickmart.co.ke/',
        'https://www.quickmart.co.ke/shop',
        'https://www.quickmart.co.ke/supermarket',
    ]

    # Domains that require JavaScript rendering
    js_domains = ['quickmart.co.ke']

    custom_settings = {
        'DOWNLOAD_DELAY': 2,
        'RANDOMIZE_DOWNLOAD_DELAY': True,
        'CONCURRENT_REQUESTS': 8,
        'CONCURRENT_REQUESTS_PER_DOMAIN': 4,
        'RETRY_TIMES': 2,
        'USER_AGENT': 'PricePoa Scraper - Quickmart (+https://pricepoa.co.ke)',
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
        self.store_chain = "Quickmart"
        self.default_store_branch = "Online Store"

    def parse(self, response):
        """
        Parse Quickmart homepage.
        """
        logging.info(f"Parsing Quickmart homepage: {response.url}")

        # Extract category links
        category_links = response.css(
            'a[href*="/shop/"], .category-link, .menu-category a'
        )::attr(href)'.getall()

        for link in set(category_links):
            if link:
                if not link.startswith('http'):
                    link = response.urljoin(link)
                yield scrapy.Request(
                    url=link,
                    callback=self.parse_category,
                    meta={'use_playwright': True} if self._needs_js(link) else {}
                )

    def parse_category(self, response):
        """
        Parse category page.
        """
        logging.info(f"Parsing Quickmart category: {response.url}")

        # Extract product links
        product_links = response.css(
            '.product-card a, .item-link, a[href*="/product/"]'
        )::attr(href)'.getall()

        for link in set(product_links):
            if link:
                if not link.startswith('http'):
                    link = response.urljoin(link)
                yield scrapy.Request(
                    url=link,
                    callback=self.parse_product,
                    meta={'use_playwright': True} if self._needs_js(link) else {}
                )

        # Handle pagination
        next_page = response.css('a.next, .pagination__next::attr(href)').get()
        if next_page:
            if not next_page.startswith('http'):
                next_page = response.urljoin(next_page)
            yield scrapy.Request(
                url=next_page,
                callback=self.parse_category,
                meta={'use_playwright': True} if self._needs_js(next_page) else {}
            )

    def parse_product(self, response):
        """
        Parse individual product page.
        """
        logging.info(f"Parsing Quickmart product: {response.url}")

        try:
            # Extract product information
            product_name = self._extract_text(response, [
                'h1::text',
                '.product-title::text',
                '.product-name::text'
            ])

            category = self._extract_text(response, [
                '.breadcrumb li:last-child a::text',
                '.category-path::text'
            ])

            price_text = self._extract_text(response, [
                '.price::text',
                '.current-price::text',
                '[data-testid="price"]::text',
                '.sale-price::text'
            ])

            if not product_name or not price_text:
                logging.warning(f"Missing product name or price for {response.url}")
                return

            # Parse price
            price = self._parse_price(price_text)
            if price is None:
                logging.warning(f"Could not parse price: {price_text}")
                return

            # Check for promotions
            is_promotional = bool(self._extract_text(response, [
                '.badge-offer, .label-sale, .promo-badge',
                '[data-testid="original-price"]',
                '.was-price::text'
            ]))

            promotion_details = None
            if is_promotional:
                promotion_details = self._extract_text(response, [
                    '.offer-details::text',
                    '.promo-text::text',
                    '.badge-offer::text'
                ])

            # Create item
            item = {
                'product_name': product_name.strip(),
                'store_chain': self.store_chain,
                'store_branch': self.default_store_branch,
                'price_kes': price,
                'source': 'quickmart_online',
                'is_promotional': is_promotional,
                'promotion_details': promotion_details,
                'scraped_at': response.meta.get('download_latency', 0),
                'response_url': response.url
            }

            # Add category if extracted
            if category:
                item['category'] = category.strip()

            yield item

        except Exception as e:
            logging.error(f"Error parsing Quickmart product {response.url}: {e}")

    def _extract_text(self, response, selectors):
        """Extract text using first matching selector."""
        for selector in selectors:
            text = response.css(selector).get()
            if text:
                return text.strip()
        return None

    def _parse_price(self, price_text):
        """Parse price text into float."""
        if not price_text:
            return None
        # Remove everything except digits and decimal point
        cleaned = re.sub(r'[^\d\.]', '', price_text)
        try:
            return float(cleaned)
        except ValueError:
            return None

    def _needs_js(self, url):
        """Check if URL needs JavaScript rendering."""
        from urllib.parse import urlparse
        parsed = urlparse(url)
        return any(domain in parsed.netloc for domain in self.js_domains)