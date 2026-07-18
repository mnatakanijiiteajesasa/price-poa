# Damru Scraper Integration Research

This document outlines how we can integrate **Damru**—the open-source, Android-native stealth browser automation framework—as our web scraper for target stores (like Naivas, Carrefour, etc.) that employ sophisticated anti-bot systems.

---

## Executive Summary: What is Damru?

Damru is an Android-native stealth browser automation framework that runs a real Android 14 OS (via **Redroid** inside a Docker container), drives Chrome via the **Chrome DevTools Protocol (CDP)** using **Playwright**, and applies fingerprint spoofing at the OS, binary, and CDP layers with **zero JavaScript injection**.

It serves as a highly robust mobile alternative to desktop tools like `undetected-chromedriver` and `playwright-stealth`.

### The 8 Layers of Stealth
Instead of attempting to patch browser features by injecting JavaScript override hooks (which are easily detected by modern anti-bots like Cloudflare Turnstile, DataDome, and Fingerprint Pro), Damru modifies the environment from the outside in:
1. **OS-Level Props (`resetprop`)**: Root access modifies Android system properties (e.g., `build.prop`) to spoof genuine device models (e.g., Pixel 8 Pro or Samsung S24).
2. **GPU Binary Patching**: Patches Vulkan/GLES `.so` files in the Android filesystem so the GPU renderer reports realistic mobile chipsets (e.g., Adreno or Mali) instead of "SwiftShader" or generic Docker graphics.
3. **Syscall Interception (`LD_PRELOAD`)**: Intercepts `sysinfo` and `sysconf` calls via a custom `libfakemem.so` library to simulate accurate physical CPU core and RAM specs.
4. **C++ CDP Overrides**: Injects hardware concurrency, display properties, and touch support directly into Chromium's C++ engine.
5. **Thread & Worker Interception**: Uses `Target.setAutoAttach` to ensure all Service Workers, Web Workers, and background threads inherit spoofed properties.
6. **Browser Config & Flags**: Randomizes Chrome preferences, locales, and cipher suites (~184 JA3 combinations).
7. **OS-Level Evasions**: Blocks WebRTC private IP leaks and disables IPv6 via `iptables` rules.
8. **Display & Density Spoofing**: Modifies the Android Window Manager (`wm size` / `wm density`) natively to match accurate physical dimensions.

---

## Comparison: Current Playwright vs. Damru

Our current scraping stack in the [scraper](file:///home/kimura/Documents/price-poa/scraper) directory uses **Scrapy** and a custom **[PlaywrightMiddleware](file:///home/kimura/Documents/price-poa/scraper/middleware/playwright_middleware.py)**. 

| Vector | Current Scrapy Playwright Middleware | Damru Scraper Integration |
| :--- | :--- | :--- |
| **Fingerprint Profile** | Generic Desktop Headless Linux | 155 real device profiles (Samsung, Pixel, OnePlus, etc.) |
| **Stealth Hooking** | None (Default Playwright arguments) | Native OS, Binary, and CDP patching—no JS injection |
| **GPU Rendering** | Disables GPU (`--disable-gpu`) or SwiftShader | Patched native GPU binaries (Adreno/Mali) |
| **Worker Context** | Leaks actual host hardware specifications | Automatic CDP worker attachment & override |
| **TLS Fingerprint** | Fixed Chromium JA3 signature | ~184 randomized JA3 hashes via cipher blacklisting |
| **Network Signal** | Leaks WebRTC / IPv6 / host DNS | OS-level IP tables blocking WebRTC/IPv6, forces proxy ISP DNS |

---

## Integration Plan: Scrapy + Damru

Since our project uses **Scrapy** as the orchestrator and database pipeline router, we can integrate Damru in two ways:

### Option A: Replace Playwright Middleware in Scrapy (Recommended)
We can write a custom Scrapy Downloader Middleware (`DamruMiddleware`) that leverages the `AsyncDamru` API. Since Scrapy supports asynchronous downloader middlewares via Python's `asyncio`, we can seamlessly borrow contexts or spawn sessions.

#### Proposed Middleware: `scraper/middleware/damru_middleware.py`
Here is a complete implementation blueprint for integrating `AsyncDamru` (or `DamruPool` for multiple parallel containers) with Scrapy:

```python
import scrapy
from scrapy.http import HtmlResponse
import logging
import asyncio
from typing import Optional

# Import Damru components
from damru import AsyncDamru
from damru.pool import DamruPool

logger = logging.getLogger(__name__)

class DamruMiddleware:
    """
    Scrapy downloader middleware that uses Damru (Android-Native Playwright)
    to render pages stealthily.
    """
    def __init__(self, crawler):
        self.crawler = crawler
        self.pool: Optional[DamruPool] = None
        self.use_pool = crawler.settings.getbool('DAMRU_USE_POOL', False)
        
    @classmethod
    def from_crawler(cls, crawler):
        middleware = cls(crawler)
        crawler.signals.connect(middleware.spider_opened, signal=scrapy.signals.spider_opened)
        crawler.signals.connect(middleware.spider_closed, signal=scrapy.signals.spider_closed)
        return middleware

    async def spider_opened(self, spider):
        """Initialize the Damru Pool if enabled."""
        if self.use_pool:
            try:
                # Initialize DamruPool in auto mode (handles Redroid containers)
                self.pool = DamruPool(
                    mode="auto",
                    max_devices=self.crawler.settings.getint('DAMRU_MAX_DEVICES', 2),
                    proxy=self.crawler.settings.get('DAMRU_PROXY', None),
                    debug=self.crawler.settings.getbool('DAMRU_DEBUG', False)
                )
                await self.pool.__aenter__()
                logger.info("DamruPool initialized successfully.")
            except Exception as e:
                logger.error(f"Failed to initialize DamruPool: {e}")
                self.pool = None

    async def spider_closed(self, spider, reason):
        """Clean up Damru Pool resources."""
        if self.pool:
            await self.pool.__aexit__(None, None, None)
            logger.info("DamruPool shut down successfully.")

    async def process_request(self, request: scrapy.Request, spider: scrapy.Spider) -> Optional[HtmlResponse]:
        """Intercepts requests and executes them inside the stealth Android browser."""
        use_damru = request.meta.get('use_damru', False)
        
        # Fallback check if domain requires JS/Stealth
        js_domains = getattr(spider, 'js_domains', [])
        if any(domain in request.url for domain in js_domains):
            use_damru = True
            
        if not use_damru:
            return None # Fall back to normal Scrapy Downloader

        logger.info(f"Stealth scraping {request.url} using Damru")
        
        # Resolve proxy
        proxy = request.meta.get('proxy') or self.crawler.settings.get('DAMRU_PROXY')

        try:
            if self.pool:
                # Use pool session
                async with self.pool.session(device="random") as context:
                    page = await context.new_page()
                    return await self._render_page(page, request)
            else:
                # Standalone session (spins up/checks active default container)
                async with AsyncDamru(device="random", proxy=proxy) as context:
                    page = await context.new_page()
                    return await self._render_page(page, request)
                    
        except Exception as e:
            logger.error(f"Damru rendering failed for {request.url}: {e}")
            return None

    async def _render_page(self, page, request: scrapy.Request) -> HtmlResponse:
        # Optional custom viewport size (though Damru already matches device spec)
        # Navigate to target page
        timeout = request.meta.get('download_timeout', 30000)
        await page.goto(request.url, wait_until='domcontentloaded', timeout=timeout)
        
        # Optional wait for dynamic selector
        wait_selector = request.meta.get('wait_for_selector')
        if wait_selector:
            await page.wait_for_selector(wait_selector, timeout=10000)
            
        # Get content
        content = await page.content()
        
        # Create HtmlResponse
        return HtmlResponse(
            url=page.url,
            body=content.encode('utf-8'),
            encoding='utf-8',
            request=request
        )
```

To enable this, we would edit `scraper/settings.py` and modify `DOWNLOADER_MIDDLEWARES`:
```python
DOWNLOADER_MIDDLEWARES = {
    'scraper.middleware.damru_middleware.DamruMiddleware': 543,
    # Remove default PlaywrightMiddleware if entirely replacing it
    # 'scraper.middleware.playwright_middleware.PlaywrightMiddleware': None,
}
```

---

### Option B: Standalone Python Scraping Service
If Scrapy adds too much performance overhead or complex thread-loop synchronization issues with Pyppeteer/Playwright's async loops, we can build a lightweight scraping worker that reads URLs from a queue, processes them using `DamruPool`, and writes results directly to MongoDB.

```python
import asyncio
from damru.pool import DamruPool
from database.connection import get_database

async def scrape_product(context, url):
    page = await context.new_page()
    try:
        await page.goto(url, wait_until="networkidle")
        # Extract title and price
        title = await page.locator("h1.product-title").inner_text()
        price_text = await page.locator(".price-current").inner_text()
        return {"url": url, "name": title, "price": price_text}
    finally:
        await page.close()

async def worker():
    db = get_database()
    # Read targets from queue or database
    urls_to_scrape = ["https://naivas.online/supermarket", "https://naivas.online/groceries"]
    
    async with DamruPool(mode="auto", max_devices=3) as pool:
        tasks = []
        for url in urls_to_scrape:
            async def task_wrapper(u):
                async with pool.session() as context:
                    result = await scrape_product(context, u)
                    # Save directly to database
                    await db.products.insert_one(result)
            tasks.append(task_wrapper(url))
        
        await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(worker())
```

---

## Deployment & Setup Steps

### 1. Host Machine Requirements
Damru depends on low-level Linux kernel features (Binder filesystem) for Redroid containers:
- **OS**: Ubuntu 24.04 LTS (recommended) or Ubuntu inside WSL2.
- **Docker & ADB**: Installed and running on the host.
- **Binderfs**: Required to run Android container binaries natively. On Ubuntu 24.04, ensure `binder_linux` kernel module is loaded:
  ```bash
  sudo modprobe binder_linux
  ```

### 2. Installing Damru
Install Damru from PyPI or directly from the Git source:
```bash
pip install git+https://github.com/akwin1234/damru.git
```

### 3. Initialize & Install Assets
Configure Damru directories, pull the optimized Redroid Docker image, and fetch the raw Chrome split-APK rotation package:
```bash
# Initialize directories & config folders
python -m damru setup

# Install required host packages (iptables-legacy, gcc, build-essential)
python -m damru install-deps

# Load/download the pre-baked Redroid OS container image
python -m damru install-image --download

# Download verified Chrome/WebView split-APKs bundle
python -m damru install-apks --download
```

### 4. Run Environment Health Checks
Before starting scrapers, check that the host system, kernel, Docker daemon, and ADB are properly configured:
```bash
python -m damru check-env
```

---

## Technical & Performance Considerations

1. **Resource Overhead**: Headless Chromium on desktop requires ~100–300MB RAM per page. Running a full Android OS via Redroid uses **1–2GB RAM** per container. If running a pool of 5 parallel scrapers, ensure the host machine has at least 8–12GB of RAM.
2. **PolyForm Noncommercial 1.0.0 License**: Damru is released under the PolyForm Noncommercial license. If PricePoa is a commercial entity or aims to generate profit, we must verify compliance or seek a commercial license/exemption from the Damru maintainers.
3. **Session Warm Starts**: Cold-starting a fresh Redroid emulator and installing/configuring Chrome takes ~30–45 seconds. Damru supports **Warm Starts** where standard setup steps (clearing Chrome, system-level properties) are skipped if the container was previously initialized, cutting session setup time down to under 5 seconds.
