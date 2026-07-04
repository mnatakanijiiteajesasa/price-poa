from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import os
import sys
from motor.motor_asyncio import AsyncIOMotorClient
import logging

# Add project root to sys.path
sys.path.append('/home/mogaka/projects/Price-Poa')

# ✓ NEW: Import Telegram webhook router
from telegram_webhook import router as telegram_router
from telegram_bot import set_telegram_webhook

# Logging
logger = logging.getLogger("uvicorn.error")
logger.setLevel(logging.INFO)

# Create app
app = FastAPI(
    title="PricePoa API",
    description="AI agent for Kenyan grocery price comparisons"
)

# ✓ NEW: Include Telegram webhook routes
app.include_router(telegram_router)


@app.on_event("startup")
async def register_telegram_webhook():
    """
    Auto-register the webhook on boot, so you never have to manually call
    set_telegram_webhook() again after restarting ngrok - just update
    TELEGRAM_WEBHOOK_URL in .env and restart the app.
    """
    webhook_url = os.getenv("TELEGRAM_WEBHOOK_URL", "")
    if not webhook_url:
        logger.warning("TELEGRAM_WEBHOOK_URL not set - skipping webhook registration")
        return
    success = set_telegram_webhook(webhook_url)
    if not success:
        logger.error("Telegram webhook registration failed on startup")


@app.get("/")
async def root():
    return {"message": "PricePoa API is running"}


@app.get("/health")
async def health_check():
    # Check MongoDB connection
    mongodb_uri = os.getenv("MONGODB_URI", "not_set")
    mongodb_db = os.getenv("MONGODB_DB", "not_set")

    return JSONResponse(
        status_code=200,
        content={
            "status": "healthy",
            "service": "api",
            "mongodb_uri": mongodb_uri,
            "mongodb_db": mongodb_db
        }
    )


@app.get("/test/db")
async def test_database_connection():
    """Test endpoint to verify MongoDB connection and basic operations."""
    try:
        mongodb_uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
        mongodb_db = os.getenv("MONGODB_DB", "pricepoa")

        # Create client
        client = AsyncIOMotorClient(mongodb_uri)
        db = client[mongodb_db]

        # Test connection
        await client.admin.command('ping')

        # Get collection stats
        products_count = await db.products.count_documents({})
        stores_count = await db.stores.count_documents({})
        prices_count = await db.prices.count_documents({})

        # Get sample product if exists
        sample_product = await db.products.find_one({}, {"_id": 0})

        # Close connection
        client.close()

        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "message": "MongoDB connection test passed",
                "database": mongodb_db,
                "collections": {
                    "products": products_count,
                    "stores": stores_count,
                    "prices": prices_count
                },
                "sample_product": sample_product
            }
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": f"MongoDB connection test failed: {str(e)}"
            }
        )


@app.get("/test/prices/recent")
async def get_recent_prices(limit: int = 10):
    """Get recent price entries for testing."""
    try:
        mongodb_uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
        mongodb_db = os.getenv("MONGODB_DB", "pricepoa")

        client = AsyncIOMotorClient(mongodb_uri)
        db = client[mongodb_db]

        # Get recent prices with product and store info
        pipeline = [
            {"$sort": {"verified_at": -1}},
            {"$limit": limit},
            {
                "$lookup": {
                    "from": "products",
                    "localField": "product_id",
                    "foreignField": "_id",
                    "as": "product"
                }
            },
            {
                "$lookup": {
                    "from": "stores",
                    "localField": "store_id",
                    "foreignField": "_id",
                    "as": "store"
                }
            },
            {
                "$project": {
                    "_id": 0,
                    "price_kes": 1,
                    "source": 1,
                    "verified_at": 1,
                    "is_promotional": 1,
                    "product_name": {"$arrayElemAt": ["$product.name", 0]},
                    "store_chain": {"$arrayElemAt": ["$store.chain_name", 0]},
                    "store_branch": {"$arrayElemAt": ["$store.branch_name", 0]}
                }
            }
        ]

        recent_prices = await db.prices.aggregate(pipeline).to_list(length=None)

        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "message": "Recent prices retrieved",
                "prices": recent_prices
            }
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": f"Failed to retrieve recent prices: {str(e)}"
            }
        )