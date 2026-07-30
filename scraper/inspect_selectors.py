"""
One-off diagnostic tool — NOT part of the regular scrape pipeline.

Renders a page with Playwright (same engine your InvisiblePlaywrightMiddleware
uses), saves the raw HTML to disk, and prints candidate selectors for product
cards by walking up from every "ADD TO CART" button. This is how we find the
real CSS classes that the markdown-converted fetch can't show us.

Usage (from inside the scraper container):
    python inspect_selectors.py https://www.naivas.online/commodities/flour
    python inspect_selectors.py https://www.naivas.online/commodities/flour flour_debug.html

    # With an age-gate (or any) cookie pre-set before navigation:
    python inspect_selectors.py https://ke.thebar.com/collections/party debug_page.html \\
        --cookie-name the-bar-gateway \\
        --cookie-value '{"status":"allowed","verified_at":"2026-07-30T15:26:45.551Z","source":"year","consent_id":"1RRVD"}' \\
        --cookie-domain ke.thebar.com
"""
import sys
import argparse
from playwright.sync_api import sync_playwright
from lxml import html as lxml_html


def scroll_to_bottom(page):
    page.evaluate(
        """async () => {
            await new Promise(resolve => {
                let total = 0;
                const distance = 400;
                const timer = setInterval(() => {
                    window.scrollBy(0, distance);
                    total += distance;
                    if (total >= document.body.scrollHeight) {
                        clearInterval(timer);
                        resolve();
                    }
                }, 200);
            });
        }"""
    )


def inspect(url: str, out_html: str = "debug_page.html", cookie: dict | None = None,
            click_selector: str | None = None):
    with sync_playwright() as p:
        browser = p.firefox.launch(headless=True)

        # Use an explicit context so we can pre-set cookies before the first
        # navigation (e.g. to bypass an age-verification gate).
        context = browser.new_context(viewport={"width": 1920, "height": 1080})

        if cookie:
            context.add_cookies([cookie])
            print(f"Applied cookie '{cookie['name']}' for domain '{cookie['domain']}'\n")

        page = context.new_page()
        page.goto(url, wait_until="networkidle", timeout=60000)

        # For server-driven gates (e.g. Livewire wire:click age gates) a cookie
        # alone won't work — the click itself triggers a backend request that
        # updates session state. Click through it here if a selector is given.
        if click_selector:
            try:
                page.click(click_selector, timeout=10000)
                print(f"Clicked '{click_selector}' — waiting for response...\n")
                page.wait_for_timeout(2000)
            except Exception as e:
                print(f"Could not click '{click_selector}': {e}\n")

        scroll_to_bottom(page)
        page.wait_for_timeout(1500)
        html = page.content()
        browser.close()

    with open(out_html, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Saved raw HTML ({len(html):,} bytes) to {out_html}\n")

    tree = lxml_html.fromstring(html)

    print("--- Product card candidates (ancestors of 'ADD TO CART') ---")
    seen = set()
    buttons = tree.xpath(
        "//*[contains(translate(text(), 'abcdefghijklmnopqrstuvwxyz', "
        "'ABCDEFGHIJKLMNOPQRSTUVWXYZ'), 'ADD TO CART')]"
    )
    for el in buttons:
        node, chain = el, []
        for _ in range(5):
            node = node.getparent()
            if node is None:
                break
            cls = node.get("class", "")
            chain.append(f"<{node.tag} class='{cls}'>")
        key = " > ".join(reversed(chain))
        if key and key not in seen:
            seen.add(key)
            print(key)
        if len(seen) >= 6:
            break

    if not seen:
        print("No 'ADD TO CART' text found — page may not have finished rendering, "
              "or product cards load via a different interaction. Check the saved HTML.")

    print("\n--- Elements containing the word 'categories' (toggle button candidates) ---")
    cat_seen = set()
    cat_elements = tree.xpath(
        "//*[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', "
        "'abcdefghijklmnopqrstuvwxyz'), 'categories')]"
    )
    for el in cat_elements:
        tag = el.tag
        cls = el.get("class", "")
        text = (el.text or "").strip()
        attrs = {k: v for k, v in el.attrib.items() if k != "class"}
        key = f"<{tag} class='{cls}' {attrs}> text='{text}'"
        if key not in cat_seen:
            cat_seen.add(key)
            print(key)
            # also show immediate parent for context
            parent = el.getparent()
            if parent is not None:
                print(f"    parent: <{parent.tag} class='{parent.get('class', '')}'>")
        if len(cat_seen) >= 10:
            break
    if not cat_seen:
        print("No elements containing 'categories' found in rendered DOM.")

    print("\n--- Links inside the mega-menu-full panel (checking if already in DOM) ---")
    label_matches = tree.xpath("//*[@id='mega-menu-full-label']")
    if not label_matches:
        print("No element with id='mega-menu-full-label' found.")
    else:
        label_el = label_matches[0]
        # walk up to find a reasonably-scoped container for the whole panel
        container = label_el
        for _ in range(6):
            parent = container.getparent()
            if parent is None:
                break
            container = parent
            # stop climbing once we hit something that looks like the panel root
            cls = container.get("class", "") or ""
            cid = container.get("id", "") or ""
            if "mega-menu" in cls or "mega-menu" in cid or container.get("role") == "dialog":
                break
        print(f"Using container: <{container.tag} id='{container.get('id','')}' class='{container.get('class','')}'>")
        links = container.xpath(".//a[@href]")
        print(f"Found {len(links)} <a href> descendants inside this container.\n")
        for a in links[:40]:
            href = a.get("href", "")
            text = "".join(a.itertext()).strip()
            cls = a.get("class", "")
            print(f"  href='{href}'  text='{text}'  class='{cls}'")

    print("\n--- Sample product-looking <a href> tags with class info (first 25) ---")
    count = 0
    for a in tree.xpath("//a[@href]"):
        href = a.get("href", "")
        title = a.get("title", "")
        if not href.startswith("http"):
            continue
        # skip obvious non-product chrome links
        if any(skip in href for skip in ("/customer/", "/cart", "/help", "/page/", "tel:", "javascript:", "#")):
            continue
        cls = a.get("class", "")
        parent = a.getparent()
        pcls = parent.get("class", "") if parent is not None else ""
        ptag = parent.tag if parent is not None else "?"
        print(f"{href}\n    title='{title}'  a.class='{cls}'  parent=<{ptag} class='{pcls}'>")
        count += 1
        if count >= 25:
            break


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Inspect rendered selectors for a store page.")
    parser.add_argument("url", nargs="?", default="https://www.naivas.online/commodities/flour")
    parser.add_argument("out_html", nargs="?", default="debug_page.html")
    parser.add_argument("--cookie-name", help="Name of a cookie to pre-set before navigation")
    parser.add_argument("--cookie-value", help="Value of the cookie to pre-set")
    parser.add_argument("--cookie-domain", help="Domain the cookie applies to")
    parser.add_argument("--cookie-path", default="/", help="Path the cookie applies to (default '/')")
    parser.add_argument("--click-selector", help="CSS selector to click before capturing content "
                                                    "(e.g. a server-driven age-gate 'yes' button)")
    args = parser.parse_args()

    cookie = None
    if args.cookie_name and args.cookie_value and args.cookie_domain:
        cookie = {
            "name": args.cookie_name,
            "value": args.cookie_value,
            "domain": args.cookie_domain,
            "path": args.cookie_path,
        }

    inspect(args.url, args.out_html, cookie, args.click_selector)