# PricePoa — Development & Operations Guide

**WhatsApp and Telegram-native price intelligence agent for Kenya**

Kenya's instant, location-aware grocery price comparison tool. This repository contains the scraper engine, backend API, Telegram bot endpoint, and database pipelines to crawl, normalize, and compare supermarket prices in real-time.

---

## 1. Project Architecture

The system is split into four primary microservices managed via Docker Compose:

| Service | Container Name | Technology | Internal Port | External Port | Purpose |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **mongo** | `pricepoa_mongo` | MongoDB 6.0 | `27017` | `27017` | Document database for products, prices, and scrape targets. |
| **mongo-express** | `pricepoa_mongo_express` | Node.js / Admin UI | `8081` | `8081` | Visual web interface for database management (Dev only). |
| **api** | `pricepoa_api` | FastAPI (Python 3.12) | `8000` | `8000` | Webhook endpoints for Telegram/WhatsApp and core API. |
| **scraper** | `pricepoa_scraper` | Scrapy / Playwright | - | - | Scheduled crawler and background worker. |

---

## 2. Quick Start: Spinning Up the Containers

Follow these steps to initialize and start the environment.

### Prerequisites
Ensure you have Docker and Docker Compose installed:
```bash
docker --version
docker compose version
```

### Step 1: Configure Environment Variables
Copy the template `.env.example` file and customize the variables if needed:
```bash
cp .env.example .env
```

### Step 2: Build & Start Core Services
Build the API and Scraper images (including downloading Playwright stealth web binaries), and start the database and backend:
```bash
# Build the containers
sudo docker compose build

# Start the database, API, and background scraper daemon in the background
sudo docker compose up -d
```

### Step 3: Start the Visual Database UI
The **Mongo Express** admin interface is configured under the `dev` profile. Spin it up by running:
```bash
sudo docker compose --profile dev up -d mongo-express
```
Once started, you can access the visual database dashboard at:  
👉 **[http://localhost:8081](http://localhost:8081)**

---

## 3. Scraper Operations

The scraper can run in two modes:

### Mode A: Scheduled Daemon Mode (Default)
When you run `sudo docker compose up -d`, the `scraper` container runs in the background in **scheduled mode** (via `worker.py --mode schedule`). 
* It automatically reads configurations and schedules daily full crawls for each spider using `APScheduler`.
* Spiders execute in the background according to their configured cron rules.

To view live scraper daemon operations and crawl status:
```bash
sudo docker compose logs -f scraper
```

### Mode B: Manual One-Shot Mode (Crawl Now)
To trigger an immediate scraping run of all active spiders and bypass the scheduler:
```bash
sudo docker compose run --rm scraper python worker.py --mode once
```

---

## 4. Viewing Database Contents

There are three ways to view and query your scraped price data:

### Method 1: Web Admin Interface (Visual)
Open your browser and navigate to **[http://localhost:8081](http://localhost:8081)**. Click on the `pricepoa` database to browse collections:
* `scrape_targets`: Active target URLs and custom scraper overrides.
* `products`: Matches canonical products.
* `prices`: Scraped daily-deduplicated price snapshots.
* `stores`: Registered store chains and branches.

### Method 2: Connection via CLI (`mongosh`)
Run the MongoDB shell directly inside the database container:
```bash
sudo docker compose exec mongo mongosh -u pricepoa_dev -p pricepoa_dev_password --authenticationDatabase admin pricepoa
```
Useful console commands:
```javascript
// Show all collections
show collections

// Count scraped price entries
db.prices.countDocuments()

// Query the latest 5 scraped prices
db.prices.find().sort({ verified_at: -1 }).limit(5).pretty()

// Exit the shell
exit
```

### Method 3: Quick Terminal Summary (One-Liner)
Run a quick Python diagnostic script inside the container to print database statistics:
```bash
sudo docker compose run --rm scraper python -c "
import asyncio
from database.connection import get_database
async def check():
    db = await get_database()
    print('--- Database Summary ---')
    print('Stores:', await db.stores.count_documents({}))
    print('Products:', await db.products.count_documents({}))
    print('Prices:', await db.prices.count_documents({}))
    print('Scrape Targets:', await db.scrape_targets.count_documents({}))
asyncio.run(check())
"
```

---

## 5. API and Webhook Operations

The API handles incoming messages from messaging channels like Telegram.

### Health Status
To check if the backend is successfully connected to the database and online:
```bash
curl http://localhost:8000/health
```

### Interactive API Documentation (Swagger)
FastAPI automatically compiles interactive documentation. You can view all endpoint structures and send test payloads via:  
👉 **[http://localhost:8000/docs](http://localhost:8000/docs)**

### Inspecting API Logs
To watch incoming webhook requests, message parsing updates, and infographics generation output:
```bash
sudo docker compose logs -f api
```

---

## 6. Stop and Clean Up Services

* **Stop all containers** (leaves database volumes intact):
  ```bash
  sudo docker compose down
  ```
* **Wipe all containers, networks, and data volumes** (resets the database completely):
  ```bash
  sudo docker compose down -v
  ```

---

## 7. Troubleshooting & Common Mismatches

### 1. `ValueError: "...Queue" does not support CONCURRENT_REQUESTS_PER_IP`
* **Cause**: Modern Scrapy uses `DownloaderAwarePriorityQueue` which limits concurrency by domain, not IP.
* **Resolution**: Ensure `CONCURRENT_REQUESTS_PER_IP` is commented out or removed in `settings.py`. Rely on `CONCURRENT_REQUESTS_PER_DOMAIN = 1` instead.

### 2. `Page.goto: Timeout 180ms exceeded`
* **Cause**: Scrapy download timeouts are defined in **seconds** (e.g., 180s), while Playwright/Puppeteer page navigation timeouts expect **milliseconds** (180,000ms). Without conversion, a default 180s timeout is parsed as 180ms.
* **Resolution**: The `InvisiblePlaywrightMiddleware` automatically converts seconds to milliseconds before dispatching requests.

### 3. `Forbidden by robots.txt` or Offsite Requests Dropped
* **Cause**: Supermarkets block scrapers in their robots.txt policies.
* **Resolution**: Set `ROBOTSTXT_OBEY = False` in `settings.py`. Additionally, ensure `allowed_domains` in spiders consists of raw hosts (e.g., `['carrefour.ke']`), not full URLs.

### 4. missing or empty required field: `Product ID` in Pipelines
* **Cause**: Item validation runs before normalization, checking fields that aren't populated yet.
* **Resolution**: Swapped pipeline priorities in `settings.py` so `NormalizationPipeline` runs first (`300`) to match items to database entities, followed by `PriceValidationPipeline` (`400`).

### 5. `NotImplementedError: Database objects do not implement truth value testing`
* **Cause**: PyMongo 4+ raises an error when comparing databases or collections in boolean contexts (`if not self.db`).
* **Resolution**: Use explicit `None` checks (`if self.db is None`) instead.
