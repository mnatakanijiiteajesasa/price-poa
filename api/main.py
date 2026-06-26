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

@app.post("/webhook/whatsapp")
async def whatsapp_webhook(request: Request):
    """
    Webhook to receive incoming WhatsApp messages from Meta Cloud API.
    Handles GET verification and POST message notifications.
    """
    # GET request for webhook verification (Meta uses query params)
    if request.method == "GET":
        # For FastAPI, we need to get query params via request.query_params
        # However, this endpoint is only declared as POST; GET will not reach here.
        # To support verification, we need to allow both GET and POST.
        # Let's change the route to accept both methods.
        pass

    # Since we only declared POST, we need to adjust: we'll change the decorator to accept both.
    # We'll handle it below by checking request.method.

    # Get the raw body for signature verification
    body = await request.body()

    # Get the signature from headers (Meta uses 'X-Hub-Signature-256')
    signature = request.headers.get("X-Hub-Signature-256", "")

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

    # Meta payload structure:
    # {
    #   "object": "whatsapp_business_account",
    #   "entry": [
    #     {
    #       "id": "...",
    #       "changes": [
    #         {
    #           "value": {
    #             "messaging_product": "whatsapp",
    #             "metadata": {
    #               "display_phone_number": "...",
    #               "phone_number_id": "..."
    #             },
    #             "contacts": [...],
    #             "messages": [
    #               {
    #                 "from": "...",
    #                 "id": "...",
    #                 "timestamp": "...",
    #                 "type": "text",
    #                 "text": { "body": "..." }
    #               }
    #             ]
    #           },
    #           "field": "messages"
    #         }
    #       ]
    #     }
    #   ]
    # }

    # Extract message details
    try:
        entry = payload.get("entry", [])[0]
        changes = entry.get("changes", [])[0]
        value = changes.get("value", {})
        # Handle status updates (ignore for now)
        if "status"status := value.get("status"):
            logger.info(f"Received status update: {status}")
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
            # For non-text, we can ignore or handle differently
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
        # We still return 200 to avoid retries, but log the error

    return JSONResponse(
        status_code=200,
        content={
            "status": "accepted",
            "message": "Message processed"
        }
    )

# Need to handle GET verification separately; change route to allow both GET and POST
# Let's replace the decorator above with a custom route that handles both.

# Actually we need to redo the endpoint. Let's rewrite after this comment.