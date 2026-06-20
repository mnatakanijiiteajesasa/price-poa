"""
Scrapy spider for scraping prices from Carrefour Kenya Online.
"""
import scrapy
import logging
from ..base_spider import BasePricePoaSpider
from ..middleware.playwright_middleware import PlaywrightMiddleware


class CarrefourSpider(BasePricePoaSpider):
    """
    Spider for scraping Carrefour Kenya Online store.
    """

    name = 'carrefour_spider'
    allowed_domains = ['carrefour.co.ke']
    start_urls = [
        'https://www.carrefour.co.ke/',
        'https://www.carrefour.co.ke/groceries',
        'https://www.carrefour.co.ke/supermarket',
    ]

    # Domains that require JavaScript rendering
    js_domains = ['carrefour.co.ke']

    custom_settings = {
        'DOWNLOAD_DELAY': 3,
        'RANDOMIZE_DOWNLOAD_DELAY': True,
        'CONCURRENT_REQUESTS': 6,
        'CONCURRENT_REQUESTS_PER_DOMAIN': 3,
        'RETRY_TIMES': 2,
        'USER_AGENT': 'PricePoa Scraper - Carrefour (+https://pricepoa.co.ke)',
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
        self.store_chain = "Carrefour"
        self.default_store_branch = "Online Store"

    def parse(self, response):
        """
        Parse Carrefour homepage and extract category links.
        """
        logging.info(f"Parsing Carrefour homepage: {response.url}")

        # Extract category links - adjust selectors based on actual site structure
        category_links = response.css(
            'a[href*="/c/"], .category-link, .menu-item a[href*="/groceries/"]'
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
        Parse category page and extract product links.
        """
        logging.info(f"Parsing Carrefour category: {response.url}")

        # Extract product links
        product_links = response.css(
            '.product-item a, .product-link, a[href*="/p/"]'
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
        next_page = response.css('a[rel="next"], .next::attr(href)').get()
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
        Parse individual product page and extract price data.
        """
        logging.info(f"Parsing Carrefour product: {response.url}")

        try:
            # Extract product information
            product_name = self._extract_text(response, [
                'h1.product-title::text',
                '.product-name::text',
                'h1::text'
            ])

            category = self._extract_text(response, [
                '.breadcrumb li:last-child a::text',
                '.category-path::text',
                '[data-testid="category"]::text'
            ])

            price_text = self._extract_text(response, [
                '.price-current::text',
                '.sales-price::text',
                '[data-testid="price"]::text',
                '.price::text'
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
                '.badge-sale, .label-offer, .promo-tag',
                '[data-testid="price-original"]',
                '.was-price::text'
            ]))

            promotion_details = None
            if is_promotional:
                promotion_details = self._extract_text(response, [
                    '.promo-details::text',
                    '.offer-text::text',
                    '.badge-sale::text'
                ])

            # Create item
            item = {
                'product_name': product_name.strip(),
                'store_chain': self.store_chain,
                'store_branch': self.default_store_branch,
                'price_kes': price,
                'source': 'carrefour_online',
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
            logging.error(f"Error parsing Carrefour product {response.url}: {e}")

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
        # Remove currency symbols, commas, and extract number
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