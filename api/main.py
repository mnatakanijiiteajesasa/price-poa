from fastapi import FastAPI, Request, HTTPException, Response
from fastapi.responses import JSONResponse
import os
import sys
from motor.motor_asyncio import AsyncIOMotorClient
import requests
import hmac
import hashlib
import json
import logging
from io import BytesIO

# Add project root to sys.path to allow imports from sibling directories
sys.path.append('/home/mogaka/projects/Price-Poa')
from infographics.generator import (
    generate_single_product_image,
    generate_shopping_list_image,
)

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


def send_whatsapp_text(to: str, message: str) -> bool:
    """
    Send a WhatsApp text message via Meta Cloud API.
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
        logger.info(f"Sent WhatsApp text message to {to}: {message}")
        return True
    except Exception as e:
        logger.error(f"Failed to send WhatsApp text message: {e}")
        return False


def send_whatsapp_image(to: str, image_bytes: bytes) -> bool:
    """
    Send a WhatsApp image via Meta Cloud API.
    Returns True if successful, False otherwise.
    Steps:
    1. Upload the image to get a media ID.
    2. Send a message with the image media ID.
    """
    # Step 1: Upload media
    upload_url = f"https://graph.facebook.com/{META_API_VERSION}/{META_WHATSAPP_PHONE_NUMBER_ID}/media"
    files = {
        'file': ('image.png', image_bytes, 'image/png')
    }
    data = {
        'messaging_product': 'whatsapp'
    }
    headers = {
        "Authorization": f"Bearer {META_WHATSAPP_ACCESS_TOKEN}"
    }
    try:
        upload_response = requests.post(upload_url, headers=headers, data=data, files=files)
        upload_response.raise_for_status()
        media_id = upload_response.json()["id"]
        logger.info(f"Uploaded image, media ID: {media_id}")
    except Exception as e:
        logger.error(f"Failed to upload image to WhatsApp: {e}")
        return False

    # Step 2: Send the image message
    send_url = f"https://graph.facebook.com/{META_API_VERSION}/{META_WHATSAPP_PHONE_NUMBER_ID}/messages"
    send_headers = {
        "Authorization": f"Bearer {META_WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    send_data = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "image",
        "image": {
            "id": media_id
        }
    }
    try:
        send_response = requests.post(send_url, headers=send_headers, json=send_data)
        send_response.raise_for_status()
        logger.info(f"Sent WhatsApp image message to {to} with media ID {media_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to send WhatsApp image message: {e}")
        return False


async def process_whatsapp_message(from_number: str, text: str) -> dict:
    """
    Process an incoming WhatsApp message and return structured data for an infographic.
    For now, we return a placeholder single product or shopping list based on simple heuristics.
    """
    logger.info(f"Processing message from {from_number}: {text}")

    # TODO: Implement NLP intent classification and entity extraction
    # TODO: Query the database for prices
    # TODO: Format the response data

    # Simple heuristic: if the message contains words like "list", "basket", "shopping", "buy", "get"
    # then we assume a shopping list, else a single product.
    text_lower = text.lower()
    shopping_keywords = ["list", "basket", "shopping", "buy", "get", "shop", "market"]
    if any(keyword in text_lower for keyword in shopping_keywords):
        # Return a placeholder shopping list with multiple stores
        return {
            "type": "shopping_list",
            "data": {
                "stores": [
                    {
                        "name": "Naivas",
                        "total": "410 KES",
                        "items": [
                            {"name": "Tomatoes", "price": "120 KES"},
                            {"name": "Milk", "price": "60 KES"},
                            {"name": "Bread", "price": "50 KES"},
                            {"name": "Eggs", "price": "180 KES"}
                        ]
                    },
                    {
                        "name": "Quickmart",
                        "total": "390 KES",
                        "items": [
                            {"name": "Tomatoes", "price": "110 KES"},
                            {"name": "Milk", "price": "55 KES"},
                            {"name": "Bread", "price": "48 KES"},
                            {"name": "Eggs", "price": "177 KES"}
                        ]
                    },
                    {
                        "name": "Chandarana",
                        "total": "420 KES",
                        "items": [
                            {"name": "Tomatoes", "price": "130 KES"},
                            {"name": "Milk", "price": "65 KES"},
                            {"name": "Bread", "price": "52 KES"},
                            {"name": "Eggs", "price": "183 KES"}
                        ]
                    }
                ],
                "recommendation": "Quickmart - Lowest total",
                "savings": "20 KES vs Naivas",
                "date": "2026-06-26"
            }
        }
    else:
        # Return a placeholder single product with multiple stores
        return {
            "type": "single_product",
            "data": {
                "product_name": "Tomatoes (1kg)",
                "stores": [
                    {"name": "Naivas", "price": "120 KES", "offer": False},
                    {"name": "Quickmart", "price": "110 KES", "offer": True},
                    {"name": "Chandarana", "price": "130 KES", "offer": False}
                ],
                "date": "2026-06-26"
            }
        }


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
            # Only handle text messages for now
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

        # Process the message to get structured data for infographic
        try:
            processed = await process_whatsapp_message(from_number, text)
        except Exception as e:
            logger.error(f"Error processing message: {e}")
            # Fallback to a simple text message
            fallback_text = "Sorry, I encountered an error processing your request. Please try again."
            success = send_whatsapp_text(from_number, fallback_text)
            return JSONResponse(
                status_code=200,
                content={
                    "status": "accepted",
                    "message": "Message processed with error fallback"
                }
            )

        # Generate image based on type
        image_bytes = None
        try:
            if processed["type"] == "single_product":
                image_bytes = generate_single_product_image(processed["data"])
            elif processed["type"] == "shopping_list":
                image_bytes = generate_shopping_list_image(processed["data"])
            else:
                logger.warning(f"Unknown message type: {processed['type']}")
                image_bytes = None
        except Exception as e:
            logger.error(f"Error generating image: {e}")
            image_bytes = None

        # Try to send image if we have it
        if image_bytes is not None:
            success = send_whatsapp_image(from_number, image_bytes)
            if success:
                return JSONResponse(
                    status_code=200,
                    content={
                        "status": "accepted",
                        "message": "Image sent successfully"
                    }
                )
            else:
                logger.warning("Failed to send image, falling back to text")

        # Fallback to text message
        # Generate a simple text summary from the data
        if processed["type"] == "single_product":
            data = processed["data"]
            text_lines = [f"Product: {data.get('product_name', 'N/A')}"]
            stores = data.get("stores", [])
            if stores:
                text_lines.append("Prices per store:")
                for store in stores:
                    text_lines.append(f"  {store.get('name', 'Unknown')}: {store.get('price', 'N/A')}")
                    if store.get('offer'):
                        text_lines[-1] += " (Offer!)"
            text_lines.append(f"Date: {data.get('date', 'N/A')}")
            fallback_text = "\n".join(text_lines)
        else:  # shopping list
            data = processed["data"]
            lines = [f"Shopping List Comparison:"]
            stores = data.get("stores", [])
            for store in stores:
                lines.append(f"  {store.get('name', 'Unknown')}: {store.get('total', 'N/A')}")
            recommendation = data.get("recommendation", "")
            if recommendation:
                lines.append(f"Recommendation: {recommendation}")
            savings = data.get("savings", "")
            if savings:
                lines.append(f"Savings: {savings}")
            lines.append(f"Date: {data.get('date', 'N/A')}")
            fallback_text = "\n".join(lines)

        # Send the fallback text
        success = send_whatsapp_text(from_number, fallback_text)
        if not success:
            logger.error("Failed to send fallback text message")

        return JSONResponse(
            status_code=200,
            content={
                "status": "accepted",
                "message": "Message processed with fallback text"
            }
        )


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


# The test endpoints remain unchanged
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