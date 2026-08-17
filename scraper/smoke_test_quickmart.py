"""
Smoke test: does pre-setting the 5 Quickmart location cookies bypass the
'Find your nearest Quickmart store' modal, without any manual interaction?

Run inside the scraper container where Playwright is already installed:
    python smoke_test_quickmart_cookies.py

What we're checking:
  1. No location modal appears (body should NOT have 'modal-open' class)
  2. The header shows the branch/town we set (e.g. "Nakuru, Kenya")
  3. Product/category content actually loads (sidebar categories, etc.)
"""
import asyncio
from playwright.async_api import async_playwright

# Values captured manually from DevTools for Nakuru Statehouse branch
NAKURU_COOKIES = [
    {"name": "_ygShopId", "value": "67"},
    {"name": "_ygGeoAddress", "value": "Nakuru, Kenya"},
    {"name": "_ygGeoLat", "value": "-0.3030988"},
    {"name": "_ygGeoLng", "value": "36.080026"},
    {"name": "_ygGeoRadius", "value": "15"},
]

DOMAIN = "www.quickmart.co.ke"
URL = "https://www.quickmart.co.ke/flour"


async def main():
    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
        )

        # Pre-set cookies BEFORE navigating
        cookies_to_set = []
        for c in NAKURU_COOKIES:
            cookies_to_set.append({
                "name": c["name"],
                "value": c["value"],
                "domain": DOMAIN,
                "path": "/",
            })
        await context.add_cookies(cookies_to_set)

        page = await context.new_page()
        print(f"Navigating to {URL} with pre-set Nakuru cookies...")
        await page.goto(URL, wait_until="networkidle", timeout=30000)

        # Check 1: modal-open class on body?
        body_class = await page.get_attribute("body", "class")
        print(f"\n[1] <body> class: {body_class}")
        modal_blocked = "modal-open" in (body_class or "")
        print(f"    -> Modal blocking page: {modal_blocked}")

        # Check 2: does header show Nakuru?
        try:
            header_text = await page.locator("text=Nakuru").first.inner_text(timeout=5000)
            print(f"\n[2] Found 'Nakuru' text on page: '{header_text}'")
        except Exception as e:
            print(f"\n[2] Could NOT find 'Nakuru' text on page: {e}")

        # Check 3: does sidebar category menu / product content exist?
        html = await page.content()
        with open("smoke_test_output.html", "w", encoding="utf-8") as f:
            f.write(html)
        print("\n[3] Saved full rendered HTML to smoke_test_output.html for inspection")

        has_categories = "categories-menu" in html
        print(f"    -> 'categories-menu' element present: {has_categories}")

        await browser.close()

        print("\n=== SUMMARY ===")
        if not modal_blocked:
            print("✅ Modal did NOT appear — cookie bypass likely WORKING")
        else:
            print("❌ Modal still appeared — cookie bypass NOT working, needs more investigation")


if __name__ == "__main__":
    asyncio.run(main())