"""
Invisible Playwright middleware for Scrapy to handle JavaScript-rendered pages using stealth Firefox.
Allows scraping of sites that require JavaScript execution or have bot-detection mechanisms.
"""
import scrapy
from scrapy.http import HtmlResponse
from typing import Optional, Any
import asyncio
import logging
import os
from invisible_playwright.async_api import async_playwright

logger = logging.getLogger(__name__)


class InvisiblePlaywrightMiddleware:
    """
    Scrapy middleware that uses feder-cr/invisible_playwright (patched Firefox) 
    to render JavaScript-heavy pages stealthily.
    """

    def __init__(self, crawler=None):
        self.crawler = crawler
        self.browser: Any = None
        self.playwright = None
        logger.info("InvisiblePlaywrightMiddleware initialized")

    @classmethod
    def from_crawler(cls, crawler):
        """Create middleware instance from crawler."""
        middleware = cls(crawler)
        crawler.signals.connect(middleware.spider_opened, signal=scrapy.signals.spider_opened)
        crawler.signals.connect(middleware.spider_closed, signal=scrapy.signals.spider_closed)
        return middleware

    async def spider_opened(self, spider):
        """Initialize invisible_playwright Firefox browser when spider opens."""
        try:
            self.playwright = await async_playwright().start()
            
            # Read proxy configuration from environment variables
            proxy_url = os.getenv("DAMRU_PROXY") or os.getenv("PROXY")
            
            # Configure browser launch arguments
            launch_kwargs = {
                "headless": True,
                "args": [
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage"
                ]
            }
            
            if proxy_url:
                logger.info(f"Configuring invisible_playwright proxy: {proxy_url}")
                launch_kwargs["proxy"] = {"server": proxy_url}
            
            # Launch the patched Firefox browser
            self.browser = await self.playwright.firefox.launch(**launch_kwargs)
            logger.info("InvisiblePlaywright Firefox browser initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize InvisiblePlaywright browser: {e}")
            self.browser = None

    async def spider_closed(self, spider, reason):
        """Clean up Playwright resources when spider closes."""
        try:
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
            logger.info("InvisiblePlaywright browser closed successfully")
        except Exception as e:
            logger.error(f"Error closing InvisiblePlaywright resources: {e}")

    async def process_request(self, request: scrapy.Request, spider: scrapy.Spider) -> Optional[HtmlResponse]:
        """
        Process request using invisible_playwright if URL requires JavaScript rendering.
        Returns HtmlResponse with rendered content, or None to let Scrapy handle normally.
        """
        if not self.browser:
            return None

        # Check if we should use Playwright for this request
        use_playwright = request.meta.get('use_playwright', False)

        # Alternative: Auto-detect JS-heavy sites by domain
        js_domains = getattr(spider, 'js_domains', [])
        if any(domain in request.url for domain in js_domains):
            use_playwright = True

        if not use_playwright:
            return None

        try:
            logger.info(f"Rendering {request.url} with InvisiblePlaywright Firefox")

            # Create new page
            page = await self.browser.new_page()

            # Set viewport size to simulate a standard desktop screen
            await page.set_viewport_size({"width": 1920, "height": 1080})

            # Navigate to the page
            scrapy_timeout = request.meta.get('download_timeout', 30)
            # Scrapy timeout is in seconds, Playwright expects milliseconds
            playwright_timeout = int(scrapy_timeout * 1000) if scrapy_timeout < 1000 else int(scrapy_timeout)
            await page.goto(request.url, wait_until='domcontentloaded', timeout=playwright_timeout)

            # Scroll page to bottom to trigger dynamic/lazy-loaded products
            await self._scroll_page_to_bottom(page)

            # Wait for specific selectors if provided in meta
            wait_for = request.meta.get('wait_for_selector')
            if wait_for:
                try:
                    await page.wait_for_selector(wait_for, timeout=10000)
                except Exception as e:
                    logger.warning(f"Timeout waiting for selector {wait_for}: {e}")

            # Get fully rendered HTML content
            content = await page.content()

            # Close page
            await page.close()

            # Return HtmlResponse with rendered content
            return HtmlResponse(
                url=request.url,
                body=content.encode('utf-8'),
                encoding='utf-8',
                request=request
            )

        except Exception as e:
            logger.error(f"Error rendering {request.url} with InvisiblePlaywright: {e}")
            return None

    async def _scroll_page_to_bottom(self, page: Any):
        """Scroll down the page dynamically to trigger lazy-loaded catalog items."""
        try:
            await page.evaluate("""
                async () => {
                    await new Promise((resolve) => {
                        let totalHeight = 0;
                        const distance = 120;
                        const timer = setInterval(() => {
                            const scrollHeight = document.body.scrollHeight;
                            window.scrollBy(0, distance);
                            totalHeight += distance;

                            if (totalHeight >= scrollHeight) {
                                clearInterval(timer);
                                resolve();
                            }
                        }, 80);
                    });
                }
            """)
            logger.debug("Successfully scrolled page to bottom for lazy loading")
        except Exception as e:
            logger.warning(f"Failed to scroll page to bottom: {e}")
