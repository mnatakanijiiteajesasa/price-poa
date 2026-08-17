import asyncio
from playwright.async_api import async_playwright

NAKURU_COOKIES = [
    {"name": "_ygShopId", "value": "67"},
    {"name": "_ygGeoAddress", "value": "Nakuru, Kenya"},
    {"name": "_ygGeoLat", "value": "-0.3030988"},
    {"name": "_ygGeoLng", "value": "36.080026"},
    {"name": "_ygGeoRadius", "value": "15"},
]
DOMAIN = "www.quickmart.co.ke"
URL = "https://www.quickmart.co.ke/foods"

async def main():
    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        await context.add_cookies([{**c, "domain": DOMAIN, "path": "/"} for c in NAKURU_COOKIES])
        page = await context.new_page()
        await page.goto(URL, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(3000)
        html = await page.content()
        with open("category_test_output.html", "w", encoding="utf-8") as f:
            f.write(html)
        print("Saved category_test_output.html")
        await browser.close()

asyncio.run(main())