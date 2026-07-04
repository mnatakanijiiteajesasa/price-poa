"""
whatsapp_webhook.py
FastAPI webhook endpoints for Meta WhatsApp - receives messages, sends replies
"""

from fastapi import APIRouter, Request, HTTPException, Response
from fastapi.responses import JSONResponse
import os
import json
import logging
from io import BytesIO

from whatsapp_meta import verify_signature, send_whatsapp_text, send_whatsapp_image

# Import your infographic generator
# Adjust this path based on your project structure
try:
    from infographics.generator import (
        generate_single_product_image,
        generate_shopping_list_image,
    )
except ImportError:
    # Fallback if infographic generator not available
    generate_single_product_image = None
    generate_shopping_list_image = None

logger = logging.getLogger("uvicorn.error")

# Config
META_WHATSAPP_VERIFY_TOKEN = os.getenv("META_WHATSAPP_VERIFY_TOKEN", "")

# Create router
router = APIRouter()


async def process_whatsapp_message(from_number: str, text: str) -> dict:
    """
    Process an incoming WhatsApp message and return structured data for infographic.
    This is where your NLP parser will go (Phase 2).
    """
    logger.info(f"Processing message from {from_number}: {text}")

    # TODO: Phase 2 - Implement NLP intent classification and entity extraction
    # TODO: Phase 2 - Query the database for prices
    # TODO: Phase 2 - Format the response data

    # Simple heuristic for now
    text_lower = text.lower()
    shopping_keywords = ["list", "basket", "shopping", "buy", "get", "shop", "market"]
    
    if any(keyword in text_lower for keyword in shopping_keywords):
        # Shopping list
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
                    }
                ],
                "recommendation": "Quickmart - Lowest total",
                "savings": "20 KES vs Naivas",
                "date": "2026-06-26"
            }
        }
    else:
        # Single product
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


@router.api_route("/webhook/whatsapp", methods=["GET", "POST"])
async def whatsapp_webhook(request: Request):
    """
    Handle WhatsApp webhook - GET for verification, POST for incoming messages
    """
    
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
                logger.info(f"Received status update")
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

        # Process the message
        try:
            processed = await process_whatsapp_message(from_number, text)
        except Exception as e:
            logger.error(f"Error processing message: {e}")
            fallback_text = "Sorry, I encountered an error processing your request. Please try again."
            send_whatsapp_text(from_number, fallback_text)
            return JSONResponse(status_code=200, content={"status": "accepted"})

        # Generate image if generator is available
        image_bytes = None
        if generate_single_product_image and generate_shopping_list_image:
            try:
                if processed["type"] == "single_product":
                    image_bytes = generate_single_product_image(processed["data"])
                elif processed["type"] == "shopping_list":
                    image_bytes = generate_shopping_list_image(processed["data"])
            except Exception as e:
                logger.error(f"Error generating image: {e}")
                image_bytes = None

        # Try to send image if we have it
        if image_bytes is not None:
            success = send_whatsapp_image(from_number, image_bytes)
            if success:
                return JSONResponse(status_code=200, content={"status": "accepted"})
            else:
                logger.warning("Failed to send image, falling back to text")

        # Fallback to text message
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

        return JSONResponse(status_code=200, content={"status": "accepted"})