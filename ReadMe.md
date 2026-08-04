# PricePoa — Development & Operations Guide

**WhatsApp and Telegram-native price intelligence agent for Kenya (under development)**

Kenya's location-aware grocery price comparison tool. This repository contains the scraper engine, backend API, Telegram bot endpoint, and database pipelines to crawl, normalize, and compare supermarket prices.

---

## 1. Project Architecture

The system is split into six primary microservices managed via Docker Compose:

| Service | Container Name | Technology | Internal Port | External Port | Purpose |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **mongo** | `pricepoa_mongo` | MongoDB 6.0 | `27017` | `27017` | Document database for products, prices, and scrape targets. |
| **mongo-express** | `pricepoa_mongo_express` | Node.js / Admin UI | `8081` | `8081` | Visual web interface for database management (Dev only). |
| **api** | `pricepoa_api` | FastAPI (Python 3.12) | `8000` | `8000` | Webhook endpoints for Telegram/WhatsApp and core API. |
| **scraper** | `pricepoa_scraper` | Scrapy / Playwright | - | - | Scheduled crawler and background worker. |
| **intelligence** | `pricepoa_intelligence` | Python 3.12 | - | - | NLP and machine learning services for product matching, recommendations, and analytics. |
| **qdrant** | `pricepoa_qdrant` | Qdrant Vector Database | `6333` | `6333` | Vector database for storing and searching product embeddings for semantic search. |

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

Build the API and Scraper images (including downloading Playwright stealth web binaries), and start the database, backend, intelligence, and vector database:
```bash
# Build the containers
sudo docker compose build

# Start all services (including qdrant and intelligence) in the background
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
### Manually triggering one scraper (e.g., the bar spider)
```bash
docker compose run --rm scraper python scraper/worker.py --mode once --spider thebar_spider
```

### Scraper diagnostic tool
```bash
docker compose run --rm scraper python inspect_selectors.py https://ke.thebar.com/collections/party
```

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

FastAPI automatically generates interactive documentation. You can view all endpoint structures and send test payloads via:  
👉 **[http://localhost:8000/docs](http://localhost:8000/docs)**

### Inspecting API Logs

To monitor incoming webhook requests, message parsing updates, and infographics generation output:
```bash
sudo docker compose logs -f api
```

---

## 6. Intelligence Layer (NLP Capabilities)

**Phase 4 of the project introduced the intelligence engine, which provides advanced analytics capabilities.** The natural language processing (NLP) parser for extracting product names and locations from free-form user messages has been implemented and is now integrated into the Telegram webhook for fuzzy product matching.

### Key Components

The intelligence engine includes the following components:

- **Enhanced Fuzzy Matching**: Uses **RapidFuzz** (a fast, performance-focused replacement for FuzzyWuzzy) for typo-tolerant product name matching, phonetic algorithms (Soundex/Metaphone), and Swahili/Sheng alias support.
- **Vector Semantic Search**: Integrated with **Qdrant** vector database to store and search product embeddings generated by **sentence-transformers** (e.g., all-MiniLM-L6-v2) for semantic product search.
- **Anomaly Detection**: Isolation Forest model to detect unusual price spikes or drops.
- **Product Recommendations**: Cosine similarity‑based recommender to suggest substitutes or complementary products.
- **Price Correlation Tracking**: Pearson correlation analysis to identify leader‑follower relationships between products across stores.
- **Query Trend Aggregation**: Analysis of user search queries to identify trending products and seasonal demand.

These components are orchestrated by the `IntelligenceEngine` class in `intelligence/intelligence_engine.py` and can be invoked via the API endpoints or background workers.

The intelligence components are initialized and maintained via the `initialize_intelligence` and `run_intelligence_maintenance` functions, which train/update models using recent data from the MongoDB database.

---
## 6b. MongoDB ↔ Qdrant Embedding Consistency (Outbox)

Product embeddings live in Qdrant's `product_embeddings` collection but their source
of truth is MongoDB's `products`. To avoid the classic **dual-write problem** (a crash
between the Mongo write and the Qdrant write leaving the two stores silently drifted),
the project uses the **transactional outbox pattern**:

1. When a product is created/updated, the product write **and** a pending `embeddings_outbox`
   record are committed to MongoDB in a **single transaction**.
2. A background worker (`intelligence/outbox/worker.py`, auto-started in the
   `intelligence` container) tails the outbox via **Change Streams** (CDC), embeds the
   product, pushes the vectors to Qdrant, and marks the record `processed` **only after
   Qdrant confirms**.
3. A periodic **reconciliation sweep** re-claims anything left pending — so if the worker
   crashes mid-write it simply resumes on restart. Processing is **idempotent by product
   `_id`** (Qdrant point IDs are deterministic hashes of `product_id` + variant text), so
   re-processing never double-writes.

> **⚠️ IMPORTANT — MongoDB must run as a replica set.** Transactions *and* Change Streams
> both require one. `docker-compose.yml` now runs `mongo` with `--replSet rs0` plus a
> `mongo-init` service that calls `rs.initiate()` once. To pick this up on an existing
> deployment (your running Mongo is currently standalone), recreate the Mongo stack:
> ```bash
> sudo docker compose up -d --force-recreate mongo mongo-init
> sudo docker compose up -d qdrant intelligence api scraper
> ```

### Viewing / driving the outbox

```bash
# Watch the worker consume the outbox (Change Stream + sweep logs)
sudo docker compose logs -f intelligence

# Backfill: enqueue every product not yet indexed (run after seeding)
sudo docker exec -it pricepoa_intelligence python -m outbox.backfill

# Force re-index of ALL products (when the model or variant logic changes)
sudo docker exec -it pricepoa_intelligence python -m outbox.backfill --force

# Inspect outbox state in mongosh
sudo docker compose exec mongo mongosh -u pricepoa_dev -p pricepoa_dev_password --authenticationDatabase admin pricepoa --eval 'db.embeddings_outbox.aggregate([{$group:{_id:"$status",n:{$sum:1}}}])'
```

Outbox records store `intent` (`create`/`update`/`delete`/`backfill`), `status`
(`pending`/`processing`/`processed`), an `attempts` counter, and `last_error`/`backoff_until`
so permanent failures are retried with backoff rather than lost. Every product write the
scraper performs (via `NormalizationPipeline`) already goes through the outbox
transactionally; the scheduler's 6-hourly backfill catches anything written outside it.

### Direct (legacy) indexer

`python -m index_product_embeddings` still works as a **one-off repair tool** that writes
straight to Qdrant without the outbox. For normal operation prefer the outbox so writes
stay consistent.

## 7. Stop and Clean Up Services

* **Stop all containers** (leaves database volumes intact):
  ```bash
  sudo docker compose down
  ```
* **Wipe all containers, networks, and data volumes** (resets the database completely):
  ```bash
  sudo docker compose down -v
  ```

---

## 8. Troubleshooting & Common Mismatches

### 1. `ValueError: "...Queue" does not support CONCURRENT_REQUESTS_PER_IP`
* **Cause**: Modern Scrapy uses `DownloaderAwarePriorityQueue` which limits concurrency by domain, not IP.
* **Resolution**: Ensure `CONCURRENT_REQUESTS_PER_IP` is commented out or removed in `settings.py`. Use `CONCURRENT_REQUESTS_PER_DOMAIN = 1` instead.

### 2. `Page.goto: Timeout 180ms exceeded`
* **Cause**: Scrapy download timeouts are defined in **seconds** (e.g., 180s), while Playwright/Puppeteer page navigation expects **milliseconds** (180,000ms). Without conversion, a 180s timeout is interpreted as 180ms.
* **Resolution**: The `InvisiblePlaywrightMiddleware` automatically converts seconds to milliseconds before dispatching requests.

### 3. `Forbidden by robots.txt` or Offsite Requests Dropped
* **Cause**: Supermarkets block scrapers via their `robots.txt` policies.
* **Resolution**: Set `ROBOTSTXT_OBEY = False` in `settings.py`. Also ensure `allowed_domains` in spiders contains raw hosts (e.g., `['carrefour.ke']`), not full URLs.

### 4. `missing or empty required field: Product ID` in Pipelines
* **Cause**: Item validation runs before normalization, checking fields that aren't populated yet.
* **Resolution**: Swap pipeline priorities in `settings.py` so `NormalizationPipeline` runs first (`300`) to match items to database entities, followed by `PriceValidationPipeline` (`400`).

### 5. `NotImplementedError: Database objects do not implement truth value testing`
* **Cause**: PyMongo 4+ raises an error when comparing databases or collections in boolean contexts (`if not self.db`).
* **Resolution**: Use explicit `None` checks (`if self.db is None`) instead.

### 6. Qdrant Connection Issues
* **Symptoms**: Logs show "Failed to initialize Qdrant client" or vector search fallback to fuzzy matching.
* **Resolution**:
  1. Verify the `qdrant` service is running: `docker compose ps qdrant`
  2. Check Qdrant logs: `docker compose logs qdrant`
  3. Ensure the `.env` file contains `QDRANT_HOST=qdrant` and `QDRANT_PORT=6333`
  4. Verify network connectivity: `docker compose exec api ping -c 3 qdrant`
  5. If using custom hosts/ports, update the environment variables accordingly.