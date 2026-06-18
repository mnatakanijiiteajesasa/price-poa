# PricePoa — Development Repository

**WhatsApp-native price intelligence agent for Kenya**

Kenya's instant, location-aware grocery price comparison tool. No app downloads. No account creation. Just send a WhatsApp message and get back a visual price comparison.

---

## Quick Start (Under 5 Minutes)

### Prerequisites

You need:
- **Docker** (version 20.10+) - [Install here](https://docs.docker.com/get-docker/)
- **Docker Compose** (version 1.29+) - Usually bundled with Docker Desktop

Verify installation:
```bash
docker --version
docker compose version
```

### Clone & Run

```bash
# 1. Clone the repository
git clone <repository_url>
cd pricepoa

# 2. Set up environment variables
cp .env.example .env

# 3. Start all services (api, mongo, mongo-express)
docker compose up

# 4. Verify everything is running
curl http://localhost:8000/health
```

That's it! Within 60 seconds, you should see:

```json
{
  "status": "healthy",
  "timestamp": "2026-06-18T10:30:00Z",
  "environment": "development",
  "mongodb": {
    "status": "healthy",
    "connected": true,
    "database": "pricepoa"
  }
}
```

---

## Access Points

Once `docker compose up` completes:

| Service | URL | Purpose |
|---------|-----|---------|
| **API** | http://localhost:8000 | FastAPI backend |
| **API Docs** | http://localhost:8000/docs | Interactive Swagger UI |
| **Health Check** | http://localhost:8000/health | Service status |
| **Mongo Express** | http://localhost:8081 | MongoDB admin UI (dev only) |

**MongoDB Direct Connection** (from host machine):
```bash
mongosh mongodb://pricepoa_dev:pricepoa_dev_password@localhost:27017/pricepoa
```

---

## Project Structure

```
pricepoa/
├── api/                    # FastAPI backend service
│   ├── main.py            # Main application with /health endpoint
│   ├── Dockerfile         # API container definition
│   └── requirements.txt    # Python dependencies
├── scraper/               # Web scraping service (Phase 1+)
│   ├── worker.py          # Background scraper worker
│   ├── Dockerfile         # Scraper container definition
│   └── requirements.txt    # Python dependencies
├── infographic/           # Infographic generation (Phase 3+)
├── intelligence/          # ML/Analytics layer (Phase 4+)
├── data/                  # Seed data and fixtures (Phase 1+)
├── docker-compose.yml     # Services orchestration
├── .env.example           # Environment variables template
├── .gitignore             # Git ignore rules
└── README.md              # This file
```

---

## Environment Variables

All configuration is managed via `.env` file (copy from `.env.example`).

| Variable | Default | Purpose |
|----------|---------|---------|
| `ENVIRONMENT` | `development` | dev, staging, production |
| `MONGO_INITDB_ROOT_USERNAME` | `pricepoa_dev` | MongoDB admin user |
| `MONGO_INITDB_ROOT_PASSWORD` | `pricepoa_dev_password` | MongoDB admin password |
| `MONGODB_URI` | `mongodb://...@mongo:27017/pricepoa` | Connection string |
| `API_HOST` | `0.0.0.0` | API listen address |
| `API_PORT` | `8000` | API port |
| `API_RELOAD` | `true` | Hot reload on code changes |
| `ENABLE_SCRAPER` | `false` | Enable scheduled scraping |
| `ENABLE_OCR` | `false` | Enable receipt OCR |
| `ENABLE_WHATSAPP` | `false` | Enable WhatsApp integration |

---

## Development Workflow

### Start Services

```bash
# Start all services in foreground (see logs)
docker compose up

# Start in background
docker compose up -d

# View logs
docker compose logs -f api     # API logs
docker compose logs -f mongo   # MongoDB logs
docker compose logs -f scraper # Scraper logs
docker compose logs -f         # All services

# Stop services
docker compose down            # Stop and remove containers
docker compose down -v         # Also remove volumes/data
```

### Add Python Dependencies

If you add a new package to `api/requirements.txt`:

```bash
# Rebuild the API container
docker compose build api

# Restart the service
docker compose up api
```

### Connect to MongoDB

**From inside API container:**
```python
from motor.motor_asyncio import AsyncClient
client = AsyncClient(os.getenv("MONGODB_URI"))
db = client[os.getenv("MONGODB_DB")]
```

**From Mongo Express UI:**
Visit http://localhost:8081 and browse collections visually.

**From CLI (mongosh):**
```bash
mongosh mongodb://pricepoa_dev:pricepoa_dev_password@localhost:27017/pricepoa
```

### Test the API

```bash
# Health check
curl http://localhost:8000/health

# Root endpoint
curl http://localhost:8000/

# Test endpoint
curl http://localhost:8000/test

# Swagger UI (interactive)
# Open http://localhost:8000/docs in browser
```

---

## Phase 0 Exit Criteria ✓

This foundation is complete when all of the following pass:

- [ ] `docker compose up` starts all services with zero errors
- [ ] `curl http://localhost:8000/health` returns HTTP 200 with healthy status
- [ ] `http://localhost:8081` shows Mongo Express with empty database
- [ ] Any developer can clone the repo and be fully running in under 5 minutes
- [ ] All services are on the same Docker network (pricepoa_network)
- [ ] Only the API port (8000) is exposed to the host; MongoDB is internal

**To verify all criteria:**

```bash
# Start services
docker compose up -d

# Wait 10 seconds for startup
sleep 10

# Run the verification script
./verify_phase0.sh  # (script provided in repo root)
```

---

## Troubleshooting

### "Address already in use"
If port 8000 or 8081 is already in use:

```bash
# Change the port in docker-compose.yml or .env
# Edit docker-compose.yml and change:
# ports:
#   - "8001:8000"  # Use 8001 instead of 8000
```

### MongoDB connection fails
```bash
# Check MongoDB container is healthy
docker compose ps

# View MongoDB logs
docker compose logs mongo

# Restart MongoDB
docker compose restart mongo
```

### Slow startup (MongoDB taking time)
MongoDB health check has a 15-second startup delay. This is normal. The API waits for MongoDB to be ready before starting.

### Hot reload not working
If changes to `api/main.py` aren't reflected:

```bash
# Rebuild the container
docker compose build api
docker compose up api
```

### "ModuleNotFoundError" in API
If a Python package is missing:

```bash
# Rebuild the API with fresh dependencies
docker compose build --no-cache api
docker compose up api
```

---

## Architecture Decisions

### Why Docker from the Start?
- **Consistency**: dev, staging, production are identical from day one
- **Isolation**: services don't interfere with host system
- **Scalability**: easy to add services, replicate, or move to cloud
- **Team onboarding**: new developers clone, run one command, they're done

### Why MongoDB?
- **Flexible schema**: price documents vary by context (promoted, verified, etc.)
- **Time-series support**: native aggregation on timestamps for trend analysis
- **Scaling**: sharding-ready for high query volume
- **Local development**: mongo-express provides visual admin UI

### Why FastAPI?
- **Performance**: async-first, built for I/O-heavy operations
- **Easy integration**: webhooks for WhatsApp are trivial to implement
- **Documentation**: auto-generated Swagger/OpenAPI docs
- **Async/await**: natural fit for database operations and API calls

### Single Dockerfile per Service?
Rather than a shared base image, each service has its own Dockerfile:
- **Clarity**: dependencies for each service are explicit
- **Optimization**: each image is tailored to its needs
- **Independence**: services can be updated without affecting others

---

## Next Steps (Phase 1)

Phase 1 begins with the **Data Layer — MongoDB + Scraping** (Weeks 2–3):

1. **MongoDB Schema Design** - products, stores, prices collections
2. **Manual Data Seeding** - 200 core SKUs across Nairobi and Nyeri
3. **Scraper Implementation** - Scrapy spiders for Naivas, Carrefour, Quickmart
4. **Scheduled Scraping** - APScheduler cron job inside scraper container

See `PricePoa_Development_Roadmap.docx` for full Phase 1 details.

---

## Contributing

### Code Style
- Follow PEP 8 for Python
- Use type hints in FastAPI endpoints
- Add docstrings to all functions
- Test locally before pushing

### Commit Messages
```
feat: Add health check endpoint
fix: Correct MongoDB connection timeout
docs: Update README with new endpoints
```

---

## License

Confidential — PricePoa Development Repository

---

## Support

For issues or questions:
1. Check this README's Troubleshooting section
2. Review the Phase 0 checklist above
3. Check Docker and service logs: `docker compose logs -f`
4. Consult `PricePoa_Development_Roadmap.docx` for architectural context

---

**Last Updated:** June 2026  
**Status:** Phase 0 — Foundation & Docker Environment  
**Next Phase:** Phase 1 — Data Layer & Scraping