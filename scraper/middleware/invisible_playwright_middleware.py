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
from datetime import datetime
from urllib.parse import urlparse
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

        context = None
        page = None
        try:
            logger.info(f"Rendering {request.url} with InvisiblePlaywright Firefox")

            # Create isolated context per request so cookies don't leak across requests
            context = await self.browser.new_context(
                viewport={"width": 1920, "height": 1080}
            )

            # Apply any gate-bypass cookies the spider defines (e.g. Quickmart's
            # location_gate_cookies). Each gate type gets its own named attribute
            # so a spider only opts into the bypasses it actually needs, and
            # spiders that don't define any are completely unaffected.
            gate_cookie_attrs = ['location_gate_cookies', 'age_gate_cookies']
            gate_cookies = []
            for attr in gate_cookie_attrs:
                gate_cookies.extend(getattr(spider, attr, []))

            if gate_cookies:
                domain = urlparse(request.url).netloc
                cookies_to_set = [
                    {**c, "domain": domain, "path": "/"} for c in gate_cookies
                ]
                await context.add_cookies(cookies_to_set)

            page = await context.new_page()

            # Set viewport size to simulate a standard desktop screen
            # (also set at context level above; kept here as a no-op safe default
            # in case a future page is opened without going through the context init)
            await page.set_viewport_size({"width": 1920, "height": 1080})

            # Navigate to the page
            scrapy_timeout = request.meta.get('download_timeout', 30)
            # Scrapy timeout is in seconds, Playwright expects milliseconds
            playwright_timeout = int(scrapy_timeout * 1000) if scrapy_timeout < 1000 else int(scrapy_timeout)
            await page.goto(request.url, wait_until='domcontentloaded', timeout=playwright_timeout)

            # Bypass any age-verification gate (e.g. The Bar's year-of-birth gate)
            # that would otherwise leave the page hiding its real content.
            # Only runs for spiders that explicitly opt in, so it never interferes
            # with sites like Quickmart that have unrelated modals (e.g. location gates).
            if getattr(spider, 'enable_age_gate_bypass', False):
                await self._bypass_age_gate(page)

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

            # Close page and context
            await page.close()
            await context.close()

            # Return HtmlResponse with rendered content
            return HtmlResponse(
                url=request.url,
                body=content.encode('utf-8'),
                encoding='utf-8',
                request=request
            )

        except Exception as e:
            logger.error(f"Error rendering {request.url} with InvisiblePlaywright: {e}")
            # Ensure page/context don't leak even on failure
            try:
                if page is not None:
                    await page.close()
            except Exception:
                pass
            try:
                if context is not None:
                    await context.close()
            except Exception:
                pass
            return None

    # --- Age-verification gate bypass --------------------------------------

    def _year_selectors(self) -> list:
        return [
            'select[name*="year" i]', 'input[name*="year" i]',
            'select[id*="year" i]', 'input[id*="year" i]',
            'select[aria-label*="year" i]', 'input[aria-label*="year" i]',
            'select[placeholder*="year" i]', 'input[placeholder*="year" i]',
            'select[placeholder*="YYYY" i]', 'input[placeholder*="YYYY" i]',
        ]

    def _month_selectors(self) -> list:
        return [
            'select[name*="month" i]', 'input[name*="month" i]',
            'select[id*="month" i]', 'input[id*="month" i]',
            'select[aria-label*="month" i]', 'input[aria-label*="month" i]',
            'select[placeholder*="month" i]', 'input[placeholder*="month" i]',
        ]

    def _day_selectors(self) -> list:
        return [
            'select[name*="day" i]', 'input[name*="day" i]',
            'select[id*="day" i]', 'input[id*="day" i]',
            'select[aria-label*="day" i]', 'input[aria-label*="day" i]',
            'select[placeholder*="day" i]', 'input[placeholder*="day" i]',
        ]

    async def _first_visible(self, page: Any, selectors: list) -> Any:
        """Return the first visible locator matching any selector, or None."""
        for selector in selectors:
            try:
                locator = page.locator(selector).first
                if await locator.count() and await locator.is_visible():
                    return locator
            except Exception:
                continue
        return None

    async def _bypass_age_gate(self, page: Any) -> bool:
        """
        Detect and click through an age-verification gate by entering a birth
        date/year comfortably over 18 years old. The Bar (ke.thebar.com) shows
        a year-of-birth gate on first load; the backend sets a
        'the-bar-gateway' cookie once a valid adult year is submitted.

        Returns True if a gate was found and handled, False otherwise.
        """
        try:
            # Give the JS app time to mount its gate before we look for it
            await page.wait_for_timeout(2000)
        except Exception:
            pass

        try:
            if not await self._detect_age_gate(page):
                return False

            logger.info("Age-verification gate detected - entering an adult birth date")
            await self._fill_birthdate(page)
            clicked = await self._click_age_gate_button(page)
            if not clicked:
                logger.warning("Age gate found but no confirm button matched")

            # Wait for the gate to dismiss and real content to render
            await page.wait_for_timeout(3000)
            return True
        except Exception as e:
            logger.warning(f"Age-gate bypass attempt failed: {e}")
            return False

    async def _detect_age_gate(self, page: Any) -> bool:
        """Return True if an age-gate container or birth-date form is visible."""
        gate_containers = [
            '[data-testid*="age" i]',
            '[class*="age-gate" i]', '[class*="age_gate" i]', '[class*="agegate" i]',
            '[class*="age-verification" i]', '[class*="ageverification" i]',
            '[class*="age-check" i]', '[id*="age-gate" i]', '[id*="age_gate" i]',
            '[role="dialog"]',
        ]
        container = await self._first_visible(page, gate_containers)
        if container is not None:
            return True

        # Fall back: a visible birth-date/year form almost certainly means a gate
        if await self._first_visible(page, self._year_selectors()) is not None:
            return True

        return False

    async def _fill_birthdate(self, page: Any) -> None:
        """Fill day/month/year fields with a birth date over 18 years old."""
        # A birth date comfortably over 18 in any year (born ~35 years ago)
        year = str(datetime.now().year - 35)

        year_field = await self._first_visible(page, self._year_selectors())
        if year_field is not None:
            await self._fill_year_field(year_field, year)

        month_field = await self._first_visible(page, self._month_selectors())
        if month_field is not None:
            await self._fill_simple_field(month_field, '1')

        day_field = await self._first_visible(page, self._day_selectors())
        if day_field is not None:
            await self._fill_simple_field(day_field, '15')

    async def _fill_year_field(self, field: Any, year: str) -> None:
        """Set an adult birth year on a select/input, respecting adult range."""
        try:
            tag = (await field.evaluate("el => el.tagName")).upper()
            if tag == 'SELECT':
                # Pick the option closest to our target year within the adult range
                selected = await field.evaluate(
                    """(sel, target) => {
                        const thisYear = new Date().getFullYear();
                        const maxAllowed = thisYear - 19;
                        const adults = Array.from(sel.options).filter(o => {
                            const n = parseInt(o.value || o.text, 10);
                            return !Number.isNaN(n) && n >= 1900 && n <= maxAllowed;
                        });
                        if (adults.length === 0) return false;
                        let best = adults[0];
                        for (const o of adults) {
                            const n = parseInt(o.value || o.text, 10);
                            const bn = parseInt(best.value || best.text, 10);
                            if (Math.abs(n - target) < Math.abs(bn - target)) best = o;
                        }
                        sel.value = (best.value !== '' && best.value != null) ? best.value : best.text;
                        sel.dispatchEvent(new Event('change', { bubbles: true }));
                        sel.dispatchEvent(new Event('input', { bubbles: true }));
                        return true;
                    }""",
                    int(year),
                )
                if selected:
                    logger.info(f"Selected adult birth year in year select")
            else:
                await field.fill(year)
                logger.info(f"Filled birth year field with {year}")
        except Exception as e:
            logger.warning(f"Failed to fill year field: {e}")

    async def _fill_simple_field(self, field: Any, value: str) -> None:
        """Fill a month/day select or input with the given value."""
        try:
            tag = (await field.evaluate("el => el.tagName")).upper()
            if tag == 'SELECT':
                try:
                    await field.select_option(value=value)
                except Exception:
                    # fall back to first option (e.g. month '1' -> 'January')
                    await field.select_option(index=0)
            else:
                await field.fill(value)
        except Exception as e:
            logger.warning(f"Failed to fill month/day field: {e}")

    async def _click_age_gate_button(self, page: Any) -> bool:
        """Click the affirmative/confirm button of the age gate."""
        button_selectors = [
            'button[type="submit"]',
            'button:has-text("Enter")',
            'button:has-text("Confirm")',
            'button:has-text("Continue")',
            'button:has-text("Submit")',
            'button:has-text("Verify")',
            'button:has-text("Yes")',
            'button:has-text("OK")',
            'button:has-text("I am over 18")',
            'button:has-text("I am 18")',
            'button:has-text("Access")',
            'button:has-text("Join")',
            '[role="button"]:has-text("Enter")',
            '[role="button"]:has-text("Confirm")',
            '[role="button"]:has-text("Continue")',
            '[role="button"]:has-text("Yes")',
            'a:has-text("Enter")',
            'a:has-text("Confirm")',
            'a:has-text("Continue")',
            'a:has-text("Yes")',
        ]
        for selector in button_selectors:
            try:
                locator = page.locator(selector).first
                if await locator.count() and await locator.is_visible():
                    await locator.click()
                    logger.info(f"Clicked age-gate confirm button via '{selector}'")
                    return True
            except Exception:
                continue
        return False

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