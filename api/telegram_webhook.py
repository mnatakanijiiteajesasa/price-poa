"""
telegram_webhook.py
FastAPI webhook endpoint for the Telegram Bot API - receives messages, sends replies.
"""

from fastapi import APIRouter, Request, HTTPException, Header
from fastapi.responses import JSONResponse
import logging
from typing import Optional

from telegram_bot import verify_telegram_secret, send_telegram_text, send_telegram_photo
from infographics.generator import (
    generate_single_product_image,
    generate_shopping_list_image,
)
from query_engine import query_single_product
from database.connection import get_database

logger = logging.getLogger("uvicorn.error")

# Create router
router = APIRouter()


async def process_telegram_message(chat_id: int, text: str) -> dict:
    """
    Process an incoming Telegram message and return structured data for infographic.
    This is where your NLP parser will go (Phase 2).
    """
    logger.info(f"Processing message from {chat_id}: {text}")

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
        # Single product - real lookup against the prices collection.
        # NOTE: treats the whole message as the product query text (e.g.
        # "unga" or "cooking oil"). Free-text sentences like "what are
        # prices for 2L cooking oil in Nyeri" won't match anything yet -
        # extracting the product/town out of a full sentence is the NLP
        # parser's job (still a Phase 2 TODO), not query_engine's.
        db = await get_database()
        result = await query_single_product(db, text)

        if result is None:
            return {
                "type": "not_found",
                "data": {"query_text": text},
            }

        return {
            "type": "single_product",
            "data": result,
        }


@router.post("/webhook/telegram")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: Optional[str] = Header(None),
):
    """
    Handle incoming Telegram updates.

    Unlike Meta, there's no GET-based verification handshake - you register
    this URL once with Telegram via set_telegram_webhook(). Telegram then
    POSTs every update here and attaches your secret_token in the
    X-Telegram-Bot-Api-Secret-Token header for you to verify.
    """
    if not verify_telegram_secret(x_telegram_bot_api_secret_token or ""):
        logger.warning("Invalid or missing secret token on Telegram webhook")
        raise HTTPException(status_code=401, detail="Invalid secret token")

    try:
        update = await request.json()
    except Exception:
        logger.error("Invalid JSON in Telegram webhook payload")
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Extract message details. Telegram updates can be messages, edited
    # messages, channel posts, callback queries, etc. - we only care about
    # plain incoming text messages for now.
    message = update.get("message")
    if not message:
        logger.info("Received non-message update (e.g. edited_message, callback_query)")
        return JSONResponse(status_code=200, content={"status": "ok"})

    chat = message.get("chat", {})
    chat_id = chat.get("id")
    text = message.get("text")

    if not chat_id or not text:
        logger.info("Message has no chat id or text (e.g. photo/sticker) - ignoring")
        return JSONResponse(status_code=200, content={"status": "ok"})

    text = text.strip()

    # Process the message
    try:
        processed = await process_telegram_message(chat_id, text)
    except Exception as e:
        logger.error(f"Error processing message: {e}")
        fallback_text = "Sorry, I encountered an error processing your request. Please try again."
        send_telegram_text(chat_id, fallback_text)
        return JSONResponse(status_code=200, content={"status": "accepted"})

    if processed["type"] == "not_found":
        query_text = processed["data"]["query_text"]
        fallback_text = (
            f'Sorry, I couldn\'t find "{query_text}" in our database yet. '
            "Try the exact product name, e.g. \"Cooking Oil\" or \"unga\"."
        )
        send_telegram_text(chat_id, fallback_text)
        return JSONResponse(status_code=200, content={"status": "accepted"})

    # Generate the infographic
    image_bytes = None
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
        success = send_telegram_photo(chat_id, image_bytes)
        if success:
            return JSONResponse(status_code=200, content={"status": "accepted"})
        else:
            logger.warning("Failed to send photo, falling back to text")

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
    success = send_telegram_text(chat_id, fallback_text)
    if not success:
        logger.error("Failed to send fallback text message")

    return JSONResponse(status_code=200, content={"status": "accepted"})