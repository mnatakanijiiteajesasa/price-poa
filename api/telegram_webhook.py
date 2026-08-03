"""
telegram_webhook.py
FastAPI webhook endpoint for the Telegram Bot API - receives messages, sends replies.
"""

from fastapi import APIRouter, Request, HTTPException, Header
from fastapi.responses import JSONResponse
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from bson import ObjectId

from telegram_bot import verify_telegram_secret, send_telegram_text, send_telegram_photo
from infographics.generator import (
    generate_single_product_image,
    generate_shopping_list_image,
    generate_product_options_image,
)
from query_engine import get_product_prices, find_product_matches
from database.connection import get_database
from intelligence.nlp.product_matcher import find_product_fuzzy
from query_engine import find_product

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

    # Extract meaningful terms
    terms = []

    # First, add the cleaned text itself if it's substantial
    cleaned_text = text_lower.strip()
    if len(cleaned_text) > 2 and not cleaned_text.isdigit():
        terms.append(cleaned_text)

    # Extract meaningful multi-word combinations (2-3 words)
    words_with_pos = text_lower.split()
    for i in range(len(words_with_pos)):
        # 2-word combinations
        if i < len(words_with_pos) - 1:
            two_word = f"{words_with_pos[i]} {words_with_pos[i+1]}"
            two_word = two_word.strip(".,!?;:")
            # Only add if it's not just common words and has sufficient length
            if len(two_word) > 3 and not _is_meaningless_phrase(two_word):
                terms.append(two_word)
        # 3-word combinations
        if i < len(words_with_pos) - 2:
            three_word = f"{words_with_pos[i]} {words_with_pos[i+1]} {words_with_pos[i+2]}"
            three_word = three_word.strip(".,!?;:")
            # Only add if it's not just common words and has sufficient length
            if len(three_word) > 3 and not _is_meaningless_phrase(three_word):
                terms.append(three_word)

    # Extract single meaningful words (nouns, etc.) but be very selective
    # Skip extremely common words that are unlikely to be product names
    stop_words = {"a", "an", "the", "of", "for", "in", "on", "at", "to", "from",
                  "with", "by", "is", "are", "was", "were", "be", "been", "being",
                  "have", "has", "had", "do", "does", "did", "will", "would", "should",
                  "could", "may", "might", "must", "can", "and", "or", "but", "in",
                  "on", "at", "to", "for", "of", "with", "by", "about", "like",
                  "through", "over", "before", "between", "after", "since", "without",
                  "under", "within", "along", "following", "across", "behind",
                  "beyond", "plus", "except", "but", "up", "down", "in", "out",
                  "on", "off", "over", "under", "again", "further", "then", "once",
                  "here", "there", "when", "where", "why", "how", "all", "any",
                  "both", "each", "few", "more", "most", "other", "some", "such",
                  "no", "nor", "not", "only", "own", "same", "so", "than", "too",
                  "very", "s", "t", "can", "will", "just", "don", "should", "now"}

    # Also skip units and quantities as they're handled elsewhere
    unit_words = {"kg", "g", "mg", "ml", "l", "ltr", "liter", "litre",
                  "piece", "pieces", "pc", "pcs", "bottle", "bottles",
                  "packet", "packets", "pack", "packs", "can", "cans",
                  "jar", "jars", "tin", "tins", "bag", "bags",
                  "pouch", "pouches", "box", "boxes", "dozen"}

    # Descriptor words that are only meaningful as part of a phrase, not standalone
    descriptor_words = {"baby", "premium", "large", "small", "fresh", "organic",
                        "natural", "new", "classic", "original", "extra",
                        "super", "mega", "mini", "jumbo", "value", "family",
                        "regular", "select", "choice", "quality", "special"}

    for part in parts:
        # Split by spaces and consider each word
        subparts = part.split()
        for word in subparts:
            # Remove any trailing/leading punctuation
            word = word.strip(".,!?;:")
            # Only consider words that are not too short, not stop words, not units, and not descriptors
            if (len(word) > 2 and
                word not in stop_words and
                word not in unit_words and
                word not in descriptor_words and   # Skip descriptor words as standalone terms
                not word.isdigit()):  # Not just a number
                terms.append(word)

    # Remove duplicates while preserving order
    seen = set()
    unique_terms = []
    for term in terms:
        if term not in seen:
            seen.add(term)
            unique_terms.append(term)

    return unique_terms


def _is_meaningless_phrase(phrase: str) -> bool:
    """
    Check if a phrase is likely to be meaningless for product matching.

    Args:
        phrase: The phrase to check

    Returns:
        True if the phrase is likely meaningless, False otherwise
    """
    # Common meaningless phrases
    meaningless_patterns = [
        "the ", "and ", "or ", "but ", "in ", "on ", "at ", "to ", "for ",
        "of ", "with ", "by ", "is ", "are ", "was ", "were ", "be ", "been ",
        "have ", "has ", "had ", "do ", "does ", "did ", "will ", "would ",
        "should ", "could ", "may ", "might ", "must ", "can ", "it ", "its ",
        "this ", "that ", "these ", "those ", "he ", "she ", "they ", "we ",
        "you ", "i ", "me ", "him ", "her ", "us ", "them "
    ]

    phrase_lower = phrase.lower() + " "  # Add space to match patterns
    for pattern in meaningless_patterns:
        if phrase_lower.startswith(pattern):
            return True

    # Also check if it's mostly just common words
    words = phrase.split()
    if len(words) > 0:
        meaningless_words = {"the", "and", "or", "but", "in", "on", "at", "to", "for",
                           "of", "with", "by", "is", "are", "was", "were", "be", "been",
                           "have", "has", "had", "do", "does", "did", "will", "would",
                           "should", "could", "may", "might", "must", "can", "it", "its",
                           "this", "that", "these", "those", "he", "she", "they", "we",
                           "you", "i", "me", "him", "her", "us", "them", "a", "an"}
        meaningful_count = sum(1 for w in words if w.lower() not in meaningless_words)
        # If less than 30% of words are meaningful, consider the phrase meaningless
        if len(words) > 0 and (meaningful_count / len(words)) < 0.3:
            return True

    return False


def extract_meaningful_product_terms(text: str) -> List[str]:
    """
    Extract and filter product terms, removing quantities, units, and non-meaningful terms.
    This helps determine if we have multiple products vs false positives.

    Args:
        text: The user's message text

    Returns:
        List of filtered product terms likely to be actual product names
    """
    # First extract all potential terms
    all_terms = extract_product_names_from_shopping_list(text)

    # Filter out terms that look like quantities or units
    filtered_terms = []
    import re
    unit_words = {"kg", "g", "mg", "ml", "l", "ltr", "liter", "litre",
                  "piece", "pieces", "pc", "pcs", "bottle", "bottles",
                  "packet", "packets", "pack", "packs", "can", "cans",
                  "jar", "jars", "tin", "tins", "bag", "bags",
                  "pouch", "pouches", "box", "boxes", "dozen"}

    for term in all_terms:
        term_lower = term.lower().strip()

        # Skip if it's just a number
        if term.isdigit():
            continue

        # Skip if it looks like a quantity (number + unit)
        # e.g., "2kg", "1.5l", "500g"
        if re.match(r'^\d+(\.\d+)?\s*(kg|g|mg|ml|l|ltr|liter|litre|piece|pieces|pc|pcs|bottle|bottles|packet|packets|pack|packs|can|cans|jar|jars|tin|tins|bag|bags|pouch|pouches|box|boxes|dozen)\s*$', term_lower):
            continue

        # Skip if it's just a unit
        if term_lower in unit_words:
            continue

        # Skip if it's too short (likely not a meaningful product name)
        if len(term_lower) < 3:
            continue

        # Skip if it's a common word that is unlikely to be a product name
        common_words = {"and", "or", "but", "in", "on", "at", "to", "for", "of", "with", "by", "is", "are", "was", "were", "be", "been", "have", "has", "had", "do", "does", "did", "will", "would", "should", "could", "may", "might", "must", "can", "it", "its", "this", "that", "these", "those", "he", "she", "they", "we", "you", "i", "me", "him", "her", "us", "them", "a", "an", "the"}
        if term_lower in common_words:
            continue

        filtered_terms.append(term)

    # Remove duplicates while preserving order
    seen = set()
    unique_filtered_terms = []
    for term in filtered_terms:
        if term not in seen:
            seen.add(term)
            unique_filtered_terms.append(term)

    return unique_filtered_terms


async def find_alternative_product_in_store(db, product: dict, store_id: str) -> Optional[Dict[str, Any]]:
    """
    Find an alternative product in a specific store when the exact product is not available.
    Looks for products with similar names or aliases that ARE available in the store.

    Args:
        db: Database connection
        product: The original product dictionary
        store_id: The store ID to check for alternatives

    Returns:
        Alternative product dictionary or None if not found
    """
    try:
        product_name = product.get("name", "").lower()
        if not product_name:
            return None

        # Get product aliases
        swahili_aliases = [alias.lower() for alias in product.get("swahili_aliases", [])]
        sheng_aliases = [alias.lower() for alias in product.get("sheng_aliases", [])]

        # All possible names to search for
        search_terms = [product_name] + swahili_aliases + sheng_aliases

        # Remove duplicates and empty strings
        search_terms = list(set([term.strip() for term in search_terms if term.strip()]))

        # Search for products in the store that match our search terms
        for term in search_terms:
            # Build query for products matching this term in name or aliases
            query = {
                "$or": [
                    {"name": {"$regex": f"^{term}$", "$options": "i"}},
                    {"swahili_aliases": {"$elemMatch": {"$regex": f"^{term}$", "$options": "i"}}},
                    {"sheng_aliases": {"$elemMatch": {"$regex": f"^{term}$", "$options": "i"}}}
                ]
            }

            # Find matching products
            matching_products = await db.products.find(query).to_list(length=None)

            # Check which of these products have prices in the target store
            for candidate_product in matching_products:
                candidate_id = str(candidate_product["_id"])
                # Check if this product has a price in the store
                price_count = await db.prices.count_documents({
                    "product_id": candidate_id,
                    "store_id": store_id
                })
                if price_count > 0:
                    return candidate_product

        return None
    except Exception as e:
        logger.error(f"Error finding alternative product: {e}")
        return None


async def get_products_for_shopping_list(db, product_names: List[str]) -> List[Dict[str, Any]]:
    """
    Look up products by name for a shopping list.
    For each product name, selects the cheapest matching product variant.

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

        # Get multiple product matches by confidence
        matches = await find_product_fuzzy(db, name.strip(), threshold=0.3)
        # Take top 5 matches by confidence to consider for price-based selection
        matches = matches[:5] if len(matches) > 5 else matches

        best_match = None
        best_price = float('inf')  # Start with infinity as worst price

        # Evaluate each match to find the cheapest one
        for match in matches:
            product_id = match["product_id"]
            # Skip if we've already added this product
            if product_id in found_names:
                continue

            # Get prices for this product to determine its cost
            try:
                # Create a minimal product dict for get_product_prices
                product_for_pricing = {"_id": product_id}
                prices_data = await get_product_prices(db, product_for_pricing)

                if prices_data and "stores" in prices_data and prices_data["stores"]:
                    # Extract prices and find the minimum
                    min_price = float('inf')
                    for store in prices_data["stores"]:
                        price_str = store.get("price", "0 KES")
                        # Parse the price (e.g., "100 KES" -> 100)
                        try:
                            price_value = float(price_str.split()[0])
                            if price_value < min_price:
                                min_price = price_value
                        except (ValueError, IndexError):
                            # If we can't parse, skip this store's price
                            continue

                    # If we found valid prices, use the minimum
                    if min_price != float('inf'):
                        if min_price < best_price:
                            best_price = min_price
                            best_match = match
                # If no prices found, we might still want to consider the product
                # but give it a high price so it's less likely to be selected
                elif best_price == float('inf'):  # Only if we haven't found any priced products yet
                    best_price = float('inf')  # Keep as infinity
                    best_match = match  # Fallback to this match if no others have prices

            except Exception as e:
                logger.error(f"Error processing product match {product_id}: {e}")
                continue

        # If we found a best match, get the full product and add it
        if best_match:
            try:
                product = await db.products.find_one({"_id": ObjectId(best_match["product_id"])})
                if product and str(product["_id"]) not in found_names:
                    products.append(product)
                    found_names.add(str(product["_id"]))
            except Exception as e:
                logger.error(f"Error fetching product {best_match['product_id']}: {e}")
        else:
            # Fallback to the original behavior if our new method didn't work
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

    # Drop products with no pricing data in any store at all
    priced_products = []
    for product in products:
        has_price = await db.prices.count_documents({"product_id": str(product["_id"])}) > 0
        if has_price:
            priced_products.append(product)
        else:
            logger.info(f"Dropping product with no pricing data anywhere: {product.get('name', 'Unknown')}")
    products = priced_products

    if not products:
        return {
            "stores": [],
            "recommendation": "No pricing data available for any product in your list",
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
                # Product not available at this store, try to find similar alternatives
                alternative_product = await find_alternative_product_in_store(db, product, store_id)
                if alternative_product:
                    # Use the alternative product
                    alt_price_cursor = db.prices.find({
                        "product_id": str(alternative_product["_id"]),
                        "store_id": store_id
                    }).sort("verified_at", -1).limit(1)

                    alt_price_doc = await alt_price_cursor.to_list(length=1)
                    if alt_price_doc:
                        alt_price = alt_price_doc[0]
                        alt_price_kes = alt_price["price_kes"]
                        is_promotional = alt_price.get("is_promotional", False)

                        # Format price
                        price_str = f"{int(alt_price_kes)} KES" if alt_price_kes == int(alt_price_kes) else f"{alt_price_kes:.1f} KES"

                        # Add to store items with indication it's an alternative
                        store_items[store_id].append({
                            "name": f"{product_name} ({alternative_product['name']})",
                            "price": price_str,
                            "offer": is_promotional
                        })

                        total_price += alt_price_kes
                        found_products += 1
                    else:
                        # Fallback to N/A if somehow no price found for alternative
                        store_items[store_id].append({
                            "name": product_name,
                            "price": "N/A",
                            "offer": False
                        })
                else:
                    # No similar product found in this store
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
        

    # Sort stores: most complete basket first, then by total price ascending
    store_totals.sort(key=lambda x: (-x["product_count"], x["total_value"]))

    # Format for the image generator
    stores_for_display = []
    for store_data in store_totals:
        stores_for_display.append({
            "name": store_data["store_name"],
            "total": store_data["total"],
            "items": store_data["items"],
            "product_count": store_data["product_count"],
        })

    # Generate recommendation and savings
    recommendation = ""
    savings = ""

    if len(stores_for_display) >= 2:
        def parse_price(price_str):
            try:
                import re
                match = re.search(r'[\d,]+\.?\d*', price_str)
                return float(match.group().replace(',', '')) if match else 0
            except:
                return 0

        best_store = stores_for_display[0]  # completeness+price winner, already correctly ordered
        highest_priced_store = max(stores_for_display, key=lambda s: parse_price(s["total"]))

        best_val = parse_price(best_store["total"])
        highest_val = parse_price(highest_priced_store["total"])

        if highest_val > best_val:
            savings_amount = highest_val - best_val
            savings_str = f"{int(savings_amount)} KES" if savings_amount == int(savings_amount) else f"{savings_amount:.1f} KES"

            recommendation = f"{best_store['name']} - Lowest total ({best_store.get('product_count', '?')}/{len(products)} items found)"
            savings = f"Save {savings_str} vs {highest_priced_store['name']}"
        else:
            recommendation = f"{best_store['name']} - Best match ({best_store.get('product_count', '?')}/{len(products)} items found)"
            savings = ""


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

    # Enhanced logic: Check for shopping keywords OR multiple product terms
    text_lower = text.lower()
    shopping_keywords = ["list", "basket", "shopping", "buy", "get", "shop", "market"]

    # Extract meaningful product terms to detect multiple products
    meaningful_terms = extract_meaningful_product_terms(text)
    has_multiple_products = len(meaningful_terms) >= 2

    # Treat as shopping list if we see shopping keywords OR multiple products
    is_shopping_list = any(keyword in text_lower for keyword in shopping_keywords) or has_multiple_products

    if is_shopping_list:
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
                    "recommendation": "No products found in your query. Try common product names like 'unga', 'sugar', or 'cooking oil'.",
                    "savings": "",
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "item_count": 0
                }
            }
    else:
        # Single product query - return multiple options for comparison
        db = await get_database()
        matches = await find_product_matches(db, text, limit=5)

        if not matches:
            return {
                "type": "not_found",
                "data": {"query_text": text},
            }

        return {
            "type": "product_options",
            "data": {
                "query_text": text,
                "options": matches,
                "date": datetime.now().strftime("%Y-%m-%d"),
            },
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

    # Extract client IP address for device tracking (considering proxies)
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        # X-Forwarded-For can contain multiple IPs, the first is the client
        client_ip = forwarded.split(',')[0].strip()
    else:
        # If not behind a proxy, use the direct client host
        client_ip = request.client.host if request.client else "unknown"

    # Process the message
    try:
        processed = await process_telegram_message(chat_id, text)
    except Exception as e:
        logger.error(f"Error processing message from {chat_id} (IP: {client_ip}): {e}")
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
            "ip_address": client_ip,
            "products": [],  # will fill if we have product IDs
        }
        if processed.get("type") == "single_product":
            product = processed.get("_product")
            if product:
                query_log["products"] = [str(product["_id"])]
        elif processed.get("type") == "product_options":
            options = processed.get("data", {}).get("options", [])
            query_log["products"] = [opt["product_id"] for opt in options if opt.get("product_id")]

        # Store the query log in database
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
            "Welcome to PricePoa, your ultimate shopping partner, we help you find the best prices in you area by typing the products you need or a list of your entire shopping. Let's get Shopping!🛒"
        )
        send_telegram_text(chat_id, welcome_text)
        return JSONResponse(status_code=200, content={"status": "accepted"})

    # Generate the infographic
    image_bytes = None
    try:
        if processed["type"] == "shopping_list":
            if "data" in processed:
                image_bytes = generate_shopping_list_image(processed["data"])
            else:
                logger.error("Missing 'data' key in processed for shopping_list")
        elif processed["type"] == "product_options":
            if "data" in processed:
                image_bytes = generate_product_options_image(processed["data"])
            else:
                logger.error("Missing 'data' key in processed for product_options")
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
    if processed["type"] == "shopping_list":
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
    else:  # product_options
        data = processed["data"]
        text_lines = [f'Results for "{data.get("query_text", "")}":']
        for opt in data.get("options", []):
            line = f"  {opt['name']} ({opt['store_name']}): {opt['price_label']}"
            if opt.get('offer'):
                line += " (Offer!)"
            text_lines.append(line)
        text_lines.append(f"Date: {data.get('date', 'N/A')}")
        fallback_text = "\n".join(text_lines)

    # Send the fallback text
    success = send_telegram_text(chat_id, fallback_text)
    if not success:
        logger.error("Failed to send fallback text message")

    return JSONResponse(status_code=200, content={"status": "accepted"})