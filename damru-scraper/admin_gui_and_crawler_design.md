# Admin GUI and Deep Supermarket Crawler Architecture

This document describes how to implement:
1. An **Admin GUI** for managing dynamic scraping target URLs.
2. A **Deep Supermarket Crawler** capable of recursively scraping all categories, subcategories, pagination pages, and product pages on `naivas.online` and similar supermarkets.

---

## 1. Admin GUI & REST API Design

To allow an admin to manage scraping URLs, we introduce a single-page HTML dashboard served directly by the FastAPI backend (`api/main.py`), which connects to the MongoDB `scrape_targets` collection.

### A. FastAPI API Endpoints
We add target management endpoints to the FastAPI application:

```python
from fastapi import APIRouter, HTTPException
from bson import ObjectId
from pydantic import BaseModel
from database.connection import get_database

router = APIRouter(prefix="/api/targets", tags=["Scraping Targets"])

class TargetCreate(BaseModel):
    store_chain: str
    target_url: str
    category: str
    is_active: bool = True
    use_stealth: bool = True

@router.get("/")
async def get_all_targets():
    db = await get_database()
    targets = await db.scrape_targets.find().to_list(length=100)
    for t in targets:
        t["id"] = str(t.pop("_id"))
    return targets

@router.post("/")
async def create_target(target: TargetCreate):
    db = await get_database()
    doc = target.dict()
    res = await db.scrape_targets.insert_one(doc)
    return {"id": str(res.inserted_id), "message": "Target created successfully"}

@router.patch("/{target_id}")
async def toggle_target(target_id: str, is_active: bool):
    db = await get_database()
    await db.scrape_targets.update_one(
        {"_id": ObjectId(target_id)}, 
        {"$set": {"is_active": is_active}}
    )
    return {"message": "Target updated successfully"}

@router.delete("/{target_id}")
async def delete_target(target_id: str):
    db = await get_database()
    await db.scrape_targets.delete_one({"_id": ObjectId(target_id)})
    return {"message": "Target deleted successfully"}
```

### B. Admin Panel GUI UI (Vanilla CSS + HTML + JS)
FastAPI can serve a single-page admin panel directly:
```python
from fastapi.responses import HTMLResponse

@app.get("/admin", response_class=HTMLResponse)
async def serve_admin_panel():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <title>PricePoa Admin Dashboard</title>
        <style>
            :root {
                --bg: #0b0f19;
                --surface: #161f30;
                --accent: #10b981;
                --text: #f3f4f6;
                --text-dim: #9ca3af;
                --border: rgba(255,255,255,0.08);
            }
            body { font-family: system-ui, sans-serif; background: var(--bg); color: var(--text); margin: 2rem; }
            h1 { color: var(--accent); }
            .card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 1.5rem; margin-bottom: 2rem; }
            table { width: 100%; border-collapse: collapse; margin-top: 1rem; }
            th, td { padding: 0.75rem; text-align: left; border-bottom: 1px solid var(--border); }
            th { color: var(--text-dim); }
            input, select, button { background: #1f293d; color: white; border: 1px solid var(--border); padding: 0.5rem 1rem; border-radius: 6px; }
            button.btn-primary { background: var(--accent); color: #04130d; font-weight: 600; cursor: pointer; }
            .status-badge { padding: 0.25rem 0.5rem; border-radius: 999px; font-size: 0.8rem; }
            .status-active { background: rgba(16,185,129,0.15); color: var(--accent); }
        </style>
    </head>
    <body>
        <h1>PricePoa Scraper Admin Panel</h1>
        
        <!-- Target Form -->
        <div class="card">
            <h2>Add New Scrape Target</h2>
            <form id="targetForm" style="display:flex; gap:1rem; flex-wrap:wrap;">
                <input type="text" id="storeChain" placeholder="Store Chain (e.g. Naivas)" required>
                <input type="url" id="targetUrl" placeholder="Target Start URL" style="flex-grow:1;" required>
                <input type="text" id="category" placeholder="Category" required>
                <select id="useStealth">
                    <option value="true">Use Damru Stealth</option>
                    <option value="false">Standard Download</option>
                </select>
                <button type="submit" class="btn-primary">Add Target</button>
            </form>
        </div>

        <!-- Targets List -->
        <div class="card">
            <h2>Target URLs</h2>
            <table>
                <thead>
                    <tr>
                        <th>Store</th>
                        <th>URL</th>
                        <th>Category</th>
                        <th>Stealth</th>
                        <th>Status</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody id="targetsList"></tbody>
            </table>
        </div>

        <script>
            async function loadTargets() {
                const res = await fetch('/api/targets/');
                const data = await res.json();
                const tbody = document.getElementById('targetsList');
                tbody.innerHTML = data.map(t => `
                    <tr>
                        <td><strong>${t.store_chain}</strong></td>
                        <td><a href="${t.target_url}" target="_blank" style="color:#60a5fa;">${t.target_url}</a></td>
                        <td>${t.category}</td>
                        <td>${t.use_stealth ? '✅ Yes' : '❌ No'}</td>
                        <td><span class="status-badge ${t.is_active ? 'status-active' : ''}">${t.is_active ? 'Active' : 'Inactive'}</span></td>
                        <td>
                            <button onclick="toggleTarget('${t.id}', ${!t.is_active})">${t.is_active ? 'Pause' : 'Activate'}</button>
                            <button onclick="deleteTarget('${t.id}')" style="background:#ef4444; border:none; cursor:pointer;">Delete</button>
                        </td>
                    </tr>
                `).join('');
            }

            document.getElementById('targetForm').addEventListener('submit', async (e) => {
                e.preventDefault();
                await fetch('/api/targets/', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        store_chain: document.getElementById('storeChain').value,
                        target_url: document.getElementById('targetUrl').value,
                        category: document.getElementById('category').value,
                        use_stealth: document.getElementById('useStealth').value === 'true'
                    })
                });
                document.getElementById('targetForm').reset();
                loadTargets();
            });

            async function toggleTarget(id, active) {
                await fetch(`/api/targets/${id}?is_active=${active}`, { method: 'PATCH' });
                loadTargets();
            }

            async function deleteTarget(id) {
                if (confirm('Delete target?')) {
                    await fetch(`/api/targets/${id}`, { method: 'DELETE' });
                    loadTargets();
                }
            }

            loadTargets();
        </script>
    </body>
    </html>
    """
```

---

## 2. Deep Supermarket Crawler Architecture

To find and scrape *every* category, subcategory, and product in an online supermarket like `naivas.online`, we configure the scraper as a **Recursive Catalog Spider**.

### A. Link Extraction Strategy
A deep spider works by extracting links recursively matching specific regex rules:
1. **Category Discovery**: Extract links matching standard category navigation patterns (e.g. `/category/*` or `/supermarket/*`).
2. **Product Page Discovery**: Extract product card links (e.g., `/product/*`).
3. **Pagination**: Extract the "Next" page button to walk through all products in that category.

In Scrapy, we implement this using a **CrawlSpider** with custom LinkExtractor Rules:

```python
from scrapy.spiders import CrawlSpider, Rule
from scrapy.linkextractors import LinkExtractor

class DeepSupermarketSpider(CrawlSpider):
    name = 'deep_supermarket_spider'
    allowed_domains = ['naivas.online']
    
    # Start URL points to home page
    start_urls = ['https://naivas.online/']
    
    rules = (
        # 1. Follow category pages recursively (e.g., /category/groceries, /category/groceries/vegetables)
        Rule(
            LinkExtractor(allow=r'/category/[\w\-]+'), 
            callback='parse_category_page', 
            follow=True
        ),
        # 2. Extract and parse individual product detail pages
        Rule(
            LinkExtractor(allow=r'/product/[\w\-]+'), 
            callback='parse_product_details'
        ),
        # 3. Follow pagination link matching "?page=" or "p=" query arguments
        Rule(
            LinkExtractor(allow=r'\?page=\d+'), 
            follow=True
        )
    )

    def parse_category_page(self, response):
        self.logger.info(f"Navigating Category: {response.url}")
        # Scrapy follows standard categories automatically via rules

    def parse_product_details(self, response):
        """Extracts names, prices, categories, and promotions from the product page."""
        self.logger.info(f"Parsing Product: {response.url}")
        # Emits the parsed Item to MongoDB pipeline
        yield {
            'product_name': response.css('h1.product-title::text').get(),
            'price_kes': float(response.css('.price-current::text').get().replace(',', '')),
            'source': 'naivas_online',
            'response_url': response.url
        }
```

### B. Alternative Strategy: Sitemap Spiders (Fastest & Safest)
Supermarkets often expose their entire catalog directory via a `sitemap.xml`. Instead of parsing thousands of HTML links (which takes a long time and increases detection surface), we can configure Scrapy to read the sitemap directly:

```python
from scrapy.spiders import SitemapSpider

class SupermarketSitemapSpider(SitemapSpider):
    name = "supermarket_sitemap_spider"
    
    # Direct access to all product and category index links
    sitemap_urls = ['https://naivas.online/sitemap.xml']
    
    # Filter rules: Send category urls to parse_category, product urls to parse_product
    sitemap_rules = [
        ('/category/', 'parse_category'),
        ('/product/', 'parse_product'),
    ]

    def parse_product(self, response):
        # Extract product details directly from the product url page
        yield {
            'product_name': response.css('h1.product-title::text').get(),
            'price_kes': float(response.css('.price-current::text').get().replace(',', '')),
            'source': 'naivas_online',
            'response_url': response.url
        }
```

### C. CDP-driven Infinite Scrolling and Lazy Loading
When scanning categories on anti-bot sites, products are often loaded via infinite scroll or lazy image loaders. We configure Damru's Playwright instance to scroll down the page dynamically before reading HTML:

```python
# Inside the downloader middleware:
async def scroll_page_to_bottom(page):
    """CDP-driven scrolling script to trigger lazy-loaded products."""
    await page.evaluate("""
        async () => {
            await new Promise((resolve) => {
                var totalHeight = 0;
                var distance = 100;
                var timer = setInterval(() => {
                    var scrollHeight = document.body.scrollHeight;
                    window.scrollBy(0, distance);
                    totalHeight += distance;

                    if(totalHeight >= scrollHeight){
                        clearInterval(timer);
                        resolve();
                    }
                }, 100);
            });
        }
    """)
```
This forces the target supermarket server to render all products before Scrapy parses them.
