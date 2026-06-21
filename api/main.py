from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
import os
from motor.motor_asyncio import AsyncIOMotorClient
import requests
import hmac
import hashlib
import json
import logging

app = FastAPI(title="PricePoa API", description="AI agent for Kenyan grocery price comparisons")

# Africa's Talking Configuration
AFRICASTALKING_USERNAME = os.getenv("AFRICASTALKING_USERNAME", "sandbox")
AFRICASTALKING_API_KEY = os.getenv("AFRICASTALKING_API_KEY", "sandbox_key")
AFRICASTALKING_WHATSAPP_SENDER = os.getenv("AFRICASTALKING_WHATSAPP_SENDER", "+254700000000")  # Your WhatsApp number
AFRICASTALKING_WHATSAPP_WEBHOOK_SECRET = os.getenv("AFRICASTALKING_WHATSAPP_WEBHOOK_SECRET", "")

# Logging
logger = logging.getLogger("uvicorn.error")
logger.setLevel(logging.INFO)

def send_whatsapp_message(to: str, message: str) -> bool:
    """
    Send a WhatsApp message via Africa's Talking API.
    Returns True if successful, False otherwise.
    """
    url = "https://api.africastalking.com/version1/messaging"
    headers = {
        "apiKey": AFRICASTALKING_API_KEY,
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    data = {
        "username": AFRICASTALKING_USERNAME,
        "to": to,
        "message": message,
        "from": AFRICASTALKING_WHATSAPP_SENDER
    }
    try:
        response = requests.post(url, headers=headers, data=data)
        response.raise_for_status()
        logger.info(f"Sent WhatsApp message to {to}: {message}")
        return True
    except Exception as e:
        logger.error(f"Failed to send WhatsApp message: {e}")
        return False

def verify_signature(request_body: bytes, signature: str) -> bool:
    """
    Verify the HMAC signature for Africa's Talking webhook.
    """
    if not AFRICASTALKING_WHATSAPP_WEBHOOK_SECRET:
        # If no secret is set, skip verification (for development)
        logger.warning("No webhook secret set, skipping signature verification")
        return True
    # Africa's Talking uses HMAC SHA256
    expected_signature = hmac.new(
        AFRICASTALKING_WHATSAPP_WEBHOOK_SECRET.encode('utf-8'),
        request_body,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected_signature, signature)

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

@app.post("/webhook/whatsapp")
async def whatsapp_webhook(request: Request):
    """
    Webhook to receive incoming WhatsApp messages from Africa's Talking.
    """
    # Get the raw body for signature verification
    body = await request.body()

    # Get the signature from headers (Africa's Talking uses 'X-Signature' or similar?)
    # According to Africa's Talking documentation, the signature is in the header 'X-Signature'
    signature = request.headers.get("X-Signature", "")

    # Verify the signature
    if not verify_signature(body, signature):
        logger.warning("Invalid signature for WhatsApp webhook")
        raise HTTPException(status_code=401, detail="Invalid signature")

    # Parse the JSON payload
    try:
        payload = json.loads(body.decode('utf-8'))
    except json.JSONDecodeError:
        logger.error("Invalid JSON in WhatsApp webhook payload")
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Extract the message details
    # Note: The exact structure depends on Africa's Talking WhatsApp API
    # We'll assume the following fields are present:
    from_number = payload.get("from") or payload.get("phoneNumber")
    text = payload.get("text", "").strip()

    if not from_number or not text:
        logger.error("Missing 'from' or 'text' in WhatsApp webhook payload")
        raise HTTPException(status_code=400, detail="Missing required fields")

    # Process the message and generate a reply
    reply_text = await process_whatsapp_message(from_number, text)

    # Send the reply
    success = send_whatsapp_message(from_number, reply_text)
    if not success:
        logger.error(f"Failed to send reply to {from_number}")
        # We still return 200 to avoid retries, but log the error

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

        recent_prices = await db.prices.aggregate(pipeline).to_list(length=limit)

        client.close()

        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "count": len(recent_prices),
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)