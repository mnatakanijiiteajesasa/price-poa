from fastapi import FastAPI, Request, HTTPException, Response
from fastapi.responses import JSONResponse
import os
from motor.motor_asyncio import AsyncIOMotorClient
import requests
import hmac
import hashlib
import json
import logging

app = FastAPI(title="PricePoa API", description="AI agent for Kenyan grocery price comparisons")

# Meta WhatsApp Business API Configuration
META_WHATSAPP_ACCESS_TOKEN = os.getenv("META_WHATSAPP_ACCESS_TOKEN", "")
META_WHATSAPP_PHONE_NUMBER_ID = os.getenv("META_WHATSAPP_PHONE_NUMBER_ID", "")
META_WHATSAPP_VERIFY_TOKEN = os.getenv("META_WHATSAPP_VERIFY_TOKEN", "")
META_APP_SECRET = os.getenv("META_APP_SECRET", "")
# Optional API version (default to v18.0)
META_API_VERSION = os.getenv("META_API_VERSION", "v18.0")

# Logging
logger = logging.getLogger("uvicorn.error")
logger.setLevel(logging.INFO)

def send_whatsapp_message(to: str, message: str) -> bool:
    """
    Send a WhatsApp message via Meta Cloud API.
    Returns True if successful, False otherwise.
    """
    url = f"https://graph.facebook.com/{META_API_VERSION}/{META_WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {META_WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    data = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {
            "body": message
        }
    }
    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        logger.info(f"Sent WhatsApp message to {to}: {message}")
        return True
    except Exception as e:
        logger.error(f"Failed to send WhatsApp message: {e}")
        return False

def verify_signature(request_body: bytes, signature_header: str) -> bool:
    """
    Verify the HMAC-SHA256 signature for Meta webhook.
    Expects signature_header like 'sha256=<hex_string>'.
    """
    if not META_APP_SECRET:
        # If no secret is set, skip verification (for development)
        logger.warning("No app secret set, skipping signature verification")
        return True
    # Remove 'sha256=' prefix if present
    if signature_header.startswith('sha256='):
        signature_header = signature_header[7:]
    # Compute expected signature
    expected_signature = hmac.new(
        META_APP_SECRET.encode('utf-8'),
        request_body,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected_signature, signature_header)

async def process_whatsapp_message(from_number: str, text: str) -> str:
    """
    Process an incoming WhatsApp message and generate a reply.
    This is where the NLP, query, and response generation will happen.
    For now, we return a fixed response.
    """
    logger.info(f"Processing message from {from_number}: {text}")

    # TODO: Implement NLP intent classification and entity extraction
    # TODO: Query the database for prices
    # TODO: Format the response

    # Placeholder response
    return f"Received your message: '{text}'. This is a placeholder response. The full agent is under development."

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

@app.api_route("/webhook/whatsapp", methods=["GET", "POST"])
async def whatsapp_webhook(request: Request):
    if request.method == "GET":
        # Webhook verification (GET)
        params = request.query_params
        mode = params.get("hub.mode")
        token = params.get("hub.verify_token")
        challenge = params.get("hub.challenge")
        if mode == "subscribe" and token == META_WHATSAPP_VERIFY_TOKEN:
            logger.info("Webhook verified")
            return Response(content=challenge, media_type="text/plain")
        else:
            logger.warning("Webhook verification failed")
            raise HTTPException(status_code=403, detail="Verification failed")
    else:
        # Handle incoming messages (POST)
        body = await request.body()
        signature = request.headers.get("X-Hub-Signature-256", "")
        if not verify_signature(body, signature):
            logger.warning("Invalid signature for WhatsApp webhook")
            raise HTTPException(status_code=401, detail="Invalid signature")
        try:
            payload = json.loads(body.decode('utf-8'))
        except json.JSONDecodeError:
            logger.error("Invalid JSON in WhatsApp webhook payload")
            raise HTTPException(status_code=400, detail="Invalid JSON")
        # Extract message details
        try:
            entry = payload.get("entry", [])[0]
            changes = entry.get("changes", [])[0]
            value = changes.get("value", {})
            # Ignore status updates
            if "status" in value:
                logger.info(f"Received status update: {value['status']}")
                return JSONResponse(status_code=200, content={"status": "ok"})
            messages = value.get("messages", [])
            if not messages:
                logger.info("No messages in webhook payload")
                return JSONResponse(status_code=200, content={"status": "ok"})
            message = messages[0]
            from_number = message.get("from")
            if message.get("type") == "text":
                text = message.get("text", {}).get("body", "").strip()
            else:
                logger.info(f"Received non-text message type: {message.get('type')}")
                return JSONResponse(status_code=200, content={"status": "ok"})
        except (IndexError, KeyError, TypeError) as e:
            logger.error(f"Failed to parse WhatsApp webhook payload: {e}")
            raise HTTPException(status_code=400, detail="Invalid payload structure")
        if not from_number or not text:
            logger.error("Missing 'from' or 'text' in WhatsApp webhook payload")
            raise HTTPException(status_code=400, detail="Missing required fields")
        # Process the message and generate a reply
        reply_text = await process_whatsapp_message(from_number, text)
        # Send the reply
        success = send_whatsapp_message(from_number, reply_text)
        if not success:
            logger.error(f"Failed to send reply to {from_number}")
        return JSONResponse(
            status_code=200,
            content={
                "status": "accepted",
                "message": "Message processed"
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