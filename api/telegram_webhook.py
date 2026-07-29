"""
telegram_webhook.py
FastAPI webhook endpoint for the Telegram Bot API - receives messages, sends replies.
"""

from fastapi import APIRouter, Request, HTTPException, Header
from fastapi.responses import JSONResponse
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone

from telegram_bot import verify_telegram_secret, send_telegram_text, send_telegram_photo
from infographics.generator import (
    generate_single_product_image,
    generate_shopping_list_image,
)
from query_engine import get_product_prices, find_product
from database.connection import get_database
from intelligence.nlp.product_matcher import find_product_enhanced

logger = logging.getLogger("uvicorn.error")

# Create router
router = APIRouter()


def extract_product_names_from_shopping_list(text: str) -> List[str]:
    """
    Extract potential product names from a shopping list query.

    Args:
        text: The user's message text

    Returns:
        List of potential product names to look up
    """
    # Convert to lowercase for processing
    text_lower = text.lower().strip()

    # Remove common shopping-related phrases
    shopping_indicators = [
        "i want to buy", "i need to buy", "can you show me prices for",
        "shopping list:", "buy", "get", "need", "want", "show me prices for",
        "what is the price of", "what are the prices of", "prices for",
        " cost", " costs", "price", "prices"
    ]

    for indicator in shopping_indicators:
        text_lower = text_lower.replace(indicator, "")

    # Split by common delimiters
    # First replace common conjunctions and punctuation with spaces
    for delim in [",", "&", "and", "plus", "+"]:
        text_lower = text_lower.replace(delim, " | ")

    # Split by the pipe delimiter we introduced
    parts = [part.strip() for part in text_lower.split("|") if part.strip()]

    # Further split by spaces and filter out empty strings and common words
    words = []
    common_words = {"a", "an", "the", "of", "for", "in", "on", "at", "to", "from",
                   "kg", "g", "gms", "ml", "l", "ltr", "liter", "liter", "piece",
                   "pieces", "pc", "pcs", "bottle", "bottles", "packet", "packets",
                   "pack", "packs", "can", "cans", "jar", "jars", "tin", "tins",
                   "bag", "bags", "pouch", "pouches", "box", "boxes"}

    for part in parts:
        # Split by spaces and take meaningful words
        subparts = part.split()
        for word in subparts:
            # Remove any trailing/leading punctuation
            word = word.strip(".,!?;:")
            if word and word not in common_words and len(word) > 1:
                words.append(word)

    # Also try to keep multi-word combinations (like "maize flour")
    # by looking at 2-3 word combinations
    multi_word_candidates = []
    words_with_pos = text_lower.split()
    for i in range(len(words_with_pos)):
        # 2-word combinations
        if i < len(words_with_pos) - 1:
            two_word = f"{words_with_pos[i]} {words_with_pos[i+1]}"
            two_word = two_word.strip(".,!?;:")
            if len(two_word) > 3:  # Avoid very short combinations
                multi_word_candidates.append(two_word)
        # 3-word combinations
        if i < len(words_with_pos) - 2:
            three_word = f"{words_with_pos[i]} {words_with_pos[i+1]} {words_with_pos[i+2]}"
            three_word = three_word.strip(".,!?;:")
            if len(three_word) > 3:
                multi_word_candidates.append(three_word)

    # Combine single words and multi-word candidates, removing duplicates
    all_candidates = list(set(words + multi_word_candidates))

    # Filter out anything that looks like a quantity or unit
    filtered_candidates = []
    quantity_indicators = {"kg", "g", "mg", "ml", "l", "litre", "liter",
                          "piece", "pieces", "pc", "pcs", "bottle", "bottles",
                          "packet", "packets", "pack", "packs", "can", "cans",
                          "jar", "jars", "tin", "tins", "bag", "bags",
                          "pouch", "pouches", "box", "boxes", "dozen"}

    for candidate in all_candidates:
        # Skip if it's just a number or number + unit
        if any(candidate.startswith(q) or candidate.endswith(q) for q in ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"]):
            # Check if it's just a number or number followed by a unit
            import re
            if re.match(r'^\d+\s*(kg|g|mg|ml|l|litre|liter|pcs?|bottles?|packets?|packs?|cans?|jars?|tins?|bags?|pouches?|boxes?|dozen)?$', candidate):
                continue
        filtered_candidates.append(candidate)

    return filtered_candidates


async def get_products_for_shopping_list(db, product_names: List[str]) -> List[Dict[str, Any]]:
    """
    Look up products by name for a shopping list.

    Args:
        db: Database connection
        product_names: List of product names to look up

    Returns:
        List of product dictionaries that were found
    """
    products = []
    found_names = set()  # To avoid duplicates

    for name in product_names:
        if not name or len(name.strip()) < 2:
            continue

        # Try to find the product using enhanced matching
        product = await find_product_enhanced(db, name.strip())
        if product and str(product["_id"]) not in found_names:
            products.append(product)
            found_names.add(str(product["_id"]))
        else:
            # Try exact match as fallback
            product = await find_product(db, name.strip())
            if product and str(product["_id"]) not in found_names:
                products.append(product)
                found_names.add(str(product["_id"]))

    return products


async def get_shopping_list_data(db, products: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Get pricing data for a list of products across stores and format for shopping list image.

    Args:
        db: Database connection
        products: List of product dictionaries

    Returns:
        Dictionary formatted for the shopping list image generator
    """
    if not products:
        return {
            "stores": [],
            "recommendation": "No products found",
            "savings": "",
            "date": datetime.now().strftime("%Y-%m-%d")
        }

    # Get all active stores
    stores_cursor = db.stores.find({"is_active": True})
    stores = await stores_cursor.to_list(length=None)

    if not stores:
        return {
            "stores": [],
            "recommendation": "No stores found",
            "savings": "",
            "date": datetime.now().strftime("%Y-%m-%d")
        }

    # For each store, get prices for all products and calculate total
    store_totals = []
    store_items = {}  # Store ID -> list of items with prices

    for store in stores:
        store_id = str(store["_id"])
        store_name = f"{store['chain_name']} - {store['branch_name']}"

        # Initialize for this store
        store_items[store_id] = []
        total_price = 0.0
        found_products = 0

        # For each product, get its price at this store
        for product in products:
            product_id = str(product["_id"])
            product_name = product["name"]

            # Look for price of this product at this store
            price_cursor = db.prices.find({
                "product_id": product_id,
                "store_id": store_id
            }).sort("verified_at", -1).limit(1)  # Get most recent price

            price_doc = await price_cursor.to_list(length=1)

            if price_doc:
                price = price_doc[0]
                price_kes = price["price_kes"]
                is_promotional = price.get("is_promotional", False)

                # Format price
                price_str = f"{int(price_kes)} KES" if price_kes == int(price_kes) else f"{price_kes:.1f} KES"

                # Add to store items
                store_items[store_id].append({
                    "name": product_name,
                    "price": price_str,
                    "offer": is_promotional
                })

                total_price += price_kes
                found_products += 1
            else:
                # Product not available at this store
                store_items[store_id].append({
                    "name": product_name,
                    "price": "N/A",
                    "offer": False
                })

        # Only include stores where we found at least one product
        if found_products > 0:
            total_str = f"{int(total_price)} KES" if total_price == int(total_price) else f"{total_price:.1f} KES"
            store_totals.append({
                "store_id": store_id,
                "store_name": store_name,
                "total": total_str,
                "total_value": total_price,  # For sorting
                "items": store_items[store_id],
                "product_count": found_products
            })

    # Sort stores by total price (ascending)
    store_totals.sort(key=lambda x: x["total_value"])

    # Format for the image generator
    stores_for_display = []
    for store_data in store_totals:
        stores_for_display.append({
            "name": store_data["store_name"],
            "total": store_data["total"],
            "items": store_data["items"]
        })

    # Generate recommendation and savings
    recommendation = ""
    savings = ""

    if len(stores_for_display) >= 2:
        cheapest = stores_for_display[0]
        most_expensive = stores_for_display[-1]

        # Extract numeric values for calculation
        def parse_price(price_str):
            try:
                # Extract number from string like "410 KES" or "410.5 KES"
                import re
                match = re.search(r'[\d,]+\.?\d*', price_str)
                if match:
                    return float(match.group().replace(',', ''))
                return 0
            except:
                return 0

        cheapest_val = parse_price(cheapest["total"])
        expensive_val = parse_price(most_expensive["total"])

        if expensive_val > cheapest_val:
            savings_amount = expensive_val - cheapest_val
            savings_str = f"{int(savings_amount)} KES" if savings_amount == int(savings_amount) else f"{savings_amount:.1f} KES"

            recommendation = f"{cheapest['name']} - Lowest total"
            savings = f"Save {savings_str} vs {most_expensive['name']}"
        else:
            recommendation = f"All stores have similar pricing"
    elif len(stores_for_display) == 1:
        recommendation = f"Only {stores_for_display[0]['name']} has pricing data"
    else:
        recommendation = "No pricing data available for any store"

    return {
        "stores": stores_for_display,
        "recommendation": recommendation,
        "savings": savings,
        "date": datetime.now().strftime("%Y-%m-%d"),
        "item_count": len(products)
    }


async def process_telegram_message(chat_id: int, text: str) -> dict:
    """
    Process an incoming Telegram message and return structured data for infographic.
    This is where the NLP parser will go (Phase 2).
    """
    logger.info(f"Processing message from {chat_id}: {text}")

    # Handle /start command
    if text.startswith("/start"):
        # Return a special response type for start command
        return {
            "type": "start",
            "data": {}
        }

    # Simple heuristic for now
    text_lower = text.lower()
    shopping_keywords = ["list", "basket", "shopping", "buy", "get", "shop", "market"]

    if any(keyword in text_lower for keyword in shopping_keywords):
        # Shopping list - process the request to get real data
        db = await get_database()

        # Extract potential product names from the text
        product_names = extract_product_names_from_shopping_list(text)
        logger.info(f"Extracted product names: {product_names}")

        # Look up the products in the database
        products = await get_products_for_shopping_list(db, product_names)
        logger.info(f"Found {len(products)} products: {[p['name'] for p in products]}")

        # Get shopping list data (prices across stores)
        if products:
            try:
                shopping_list_data = await get_shopping_list_data(db, products)
                return {
                    "type": "shopping_list",
                    "data": {
                        "stores": shopping_list_data["stores"],
                        "recommendation": shopping_list_data["recommendation"],
                        "savings": shopping_list_data["savings"],
                        "date": datetime.now().strftime("%Y-%m-%d"),
                        "item_count": len(products)
                    }
                }
            except Exception as e:
                logger.error(f"Error generating shopping list data: {e}")
                # Fallback to a simple response if data generation fails
                return {
                    "type": "shopping_list",
                    "data": {
                        "stores": [],
                        "recommendation": "Unable to retrieve pricing data at this time. Please try again later.",
                        "savings": "",
                        "date": datetime.now().strftime("%Y-%m-%d"),
                        "item_count": len(products)
                    }
                }
        else:
            # No products found
            return {
                "type": "shopping_list",
                "data": {
                    "stores": [],
                    "recommendation": "No products found in your query. Try specific product names like 'unga', 'sugar', or 'cooking oil'.",
                    "savings": "",
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "item_count": 0
                }
            }
    else:
        # Single product - use enhanced matching (exact + fuzzy + aliases) to find product.
        # NOTE: This replaces the old exact-only lookup with NLP-powered matching.
        db = await get_database()
        product = await find_product_enhanced(db, text)
        if product is None:
            return {
                "type": "not_found",
                "data": {"query_text": text},
            }

        # Get product prices (same as before)
        result = await get_product_prices(db, product)

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
        fallback_text = "Sorry, our service is temporarily unavailable. Please try again later."
        send_telegram_text(chat_id, fallback_text)
        return JSONResponse(status_code=200, content={"status": "accepted"})

    # Log query for analytics
    try:
        db = await get_database()
        query_log = {
            "user_id": chat_id,
            "text": text,
            "timestamp": datetime.now(timezone.utc),
            "products": [],  # will fill if we have product IDs
        }
        if processed.get("type") == "single_product":
            # Look up the product by text again for logging (we already did this in processing, but we need the object for logging)
            product = await find_product_enhanced(db, text)
            if product:
                query_log["products"] = [str(product["_id"])]
        # For other types, leave products empty
        await db.query_logs.insert_one(query_log)
    except Exception as e:
        logger.error(f"Failed to log query: {e}")

    if processed["type"] == "not_found":
        query_text = processed["data"]["query_text"]
        fallback_text = (
            f'Sorry, I couldn\'t find "{query_text}" in our database yet. '
            "Try the exact product name, e.g. \"Cooking Oil\" or \"unga\"."
        )
        send_telegram_text(chat_id, fallback_text)
        return JSONResponse(status_code=200, content={"status": "accepted"})

    # Handle start command
    if processed["type"] == "start":
        welcome_text = (
            "Welcome to PricePoa, your ultimate shopping partner, we help you find the best prices in you area by typing the product you need or a list of your entire shopping. Let's get Shopping!"
        )
        send_telegram_text(chat_id, welcome_text)
        return JSONResponse(status_code=200, content={"status": "accepted"})

    # Generate the infographic
    image_bytes = None
    try:
        if processed["type"] == "single_product":
            if "data" in processed:
                image_bytes = generate_single_product_image(processed["data"])
            else:
                logger.error("Missing 'data' key in processed for single_product")
        elif processed["type"] == "shopping_list":
            if "data" in processed:
                image_bytes = generate_shopping_list_image(processed["data"])
            else:
                logger.error("Missing 'data' key in processed for shopping_list")
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
        if data.get("item_count"):
            lines.append(f"Items: {data['item_count']}")
        fallback_text = "\n".join(lines)

    # Send the fallback text
    success = send_telegram_text(chat_id, fallback_text)
    if not success:
        logger.error("Failed to send fallback text message")

    return JSONResponse(status_code=200, content={"status": "accepted"})