"""
Playwright middleware for Scrapy to handle JavaScript-rendered pages.
Allows scraping of sites that require JavaScript execution to load price data.
"""
import scrapy
from scrapy.http import HtmlResponse
from typing import Optional
import asyncio
import logging
from playwright.async_api import async_playwright, Browser, Page

logger = logging.getLogger(__name__)


class PlaywrightMiddleware:
    """
    Scrapy middleware that uses Playwright to render JavaScript-heavy pages.
    Intercepts requests and uses Playwright to get fully rendered HTML.
    """

    def __init__(self, crawler=None):
        self.crawler = crawler
        self.browser: Optional[Browser] = None
        self.playwright = None
        logger.info("PlaywrightMiddleware initialized")

    @classmethod
    def from_crawler(cls, crawler):
        """Create middleware instance from crawler."""
        middleware = cls(crawler)
        crawler.signals.connect(middleware.spider_opened, signal=scrapy.signals.spider_opened)
        crawler.signals.connect(middleware.spider_closed, signal=scrapy.signals.spider_closed)
        return middleware

    async def spider_opened(self, spider):
        """Initialize Playwright browser when spider opens."""
        try:
            self.playwright = await async_playwright().start()
            # Launch browser in headless mode for production
            self.browser = await self.playwright.chromium.launch(
                headless=True,
                args=[
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-gpu',
                    '--no-zygote'
                ]
            )
            logger.info("Playwright browser initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Playwright browser: {e}")
            # Don't raise - allow spider to continue with regular Scrapy downloader
            self.browser = None

    async def spider_closed(self, spider, reason):
        """Clean up Playwright resources when spider closes."""
        try:
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
            logger.info("Playwright browser closed successfully")
        except Exception as e:
            logger.error(f"Error closing Playwright resources: {e}")

    async def process_request(self, request: scrapy.Request, spider: scrapy.Spider) -> Optional[HtmlResponse]:
        """
        Process request using Playwright if URL requires JavaScript rendering.
        Returns HtmlResponse with rendered content, or None to let Scrapy handle normally.
        """
        # Skip if browser not available
        if not self.browser:
            return None

        # Check if we should use Playwright for this request
        # You can customize this logic based on URL patterns, meta flags, etc.
        use_playwright = request.meta.get('use_playwright', False)

        # Alternative: Auto-detect JS-heavy sites by domain
        js_domains = getattr(spider, 'js_domains', [])
        if any(domain in request.url for domain in js_domains):
            use_playwright = True

        if not use_playwright:
            return None

        try:
            logger.debug(f"Rendering {request.url} with Playwright")

            # Create new page
            page = await self.browser.new_page()

            # Set viewport and user agent
            await page.set_viewport_size({"width": 1920, "height": 1080})
            await page.set_extra_http_headers({
                'User-Agent': 'PricePoa Scraper (+https://pricepoa.co.ke)'
            })

            # Navigate to page
            await page.goto(request.url, wait_until='networkidle', timeout=30000)

            # Wait for specific selectors if provided in meta
            wait_for = request.meta.get('wait_for_selector')
            if wait_for:
                try:
                    await page.wait_for_selector(wait_for, timeout=10000)
                except Exception as e:
                    logger.warning(f"Timeout waiting for selector {wait_for}: {e}")

            # Additional wait time for dynamic content
            await page.wait_for_timeout(request.meta.get('wait_timeout', 2000))

            # Get rendered HTML content
            content = await page.content()

            # Close page
            await page.close()

            # Create HtmlResponse with rendered content
            return HtmlResponse(
                url=request.url,
                body=content.encode('utf-8'),
                encoding='utf-8',
                request=request
            )

        except Exception as e:
            logger.error(f"Error rendering {request.url} with Playwright: {e}")
            # Return None to let Scrapy handle the request normally or fail
            return None


class PlaywrightRetryMiddleware:
    """
    Middleware to retry failed Playwright requests with regular Scrapy downloader.
    Provides fallback when JavaScript rendering fails.
    """

    def process_response(self, request: scrapy.Request, response: scrapy.Response, spider: scrapy.Spider) -> scrapy.Response:
        """
        If Playwright returned an empty or error response, retry with regular downloader.
        """
        # Check if response indicates Playwright failure
        if (hasattr(response, 'status') and
            response.status >= 400 and
            request.meta.get('use_playwright', False)):

            logger.warning(f"Playwright request failed for {request.url}, retrying with regular downloader")
            # Remove Playwright flag for retry
            retry_request = request.copy()
            retry_request.meta['use_playwright'] = False
            # Return the retry request to be processed again
            return retry_request

        return response

    def process_exception(self, request: scrapy.Request, exception: Exception, spider: scrapy.Spider):
        """
        Handle exceptions during Playwright processing by falling back to regular downloader.
        """
        if request.meta.get('use_playwright', False):
            logger.warning(f"Playwright exception for {request.url}: {exception}, falling back to regular downloader")
            retry_request = request.copy()
            retry_request.meta['use_playwright'] = False
            return retry_request
        return None