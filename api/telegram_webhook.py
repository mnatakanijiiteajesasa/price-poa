"""
telegram_webhook.py
FastAPI webhook endpoint for the Telegram Bot API - receives messages, sends replies.
"""

from fastapi import APIRouter, Request, HTTPException, Header
from fastapi.responses import JSONResponse
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone, timedelta
from bson import ObjectId

from telegram_bot import verify_telegram_secret, send_telegram_text, send_telegram_photo
from infographics.generator import (
    generate_shopping_list_image,
    generate_product_options_image,
)
from query_engine import get_product_prices, find_product_matches
from database.connection import get_database
from intelligence.nlp.product_matcher import find_product_fuzzy
from query_engine import find_product
from database.models import ChatSession, ChatMessage, Grocer, ChatRequest

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

    # Get all active stores first
    stores_cursor = db.stores.find({"is_active": True})
    stores = await stores_cursor.to_list(length=None)

    if not stores:
        return {
            "stores": [],
            "recommendation": "No stores found",
            "savings": "",
            "date": datetime.now().strftime("%Y-%m-%d")
        }

    # Get active store IDs for filtering
    active_store_ids = [str(store["_id"]) for store in stores]

    # Drop products with no pricing data in any of the active stores
    priced_products = []
    for product in products:
        has_price = await db.prices.count_documents({
            "product_id": str(product["_id"]),
            "store_id": {"$in": active_store_ids}
        }) > 0
        if has_price:
            priced_products.append(product)
        else:
            logger.info(f"Dropping product with no pricing data in any active store: {product.get('name', 'Unknown')}")
    products = priced_products

    if not products:
        return {
            "stores": [],
            "recommendation": "No pricing data available for any product in your list",
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

    # Handle GTA 6 special chat dimension
    text_lower = text.lower().strip()
    if text_lower in ["gta 6", "gta6", "grand theft auto 6", "grand theft auto six"]:
        # Check if there's an active GTA 6 chat session
        db = await get_database()

        # Look for existing active GTA 6 session
        existing_session = await db.chat_sessions.find_one({
            "topic": {"$regex": "^gta 6$", "$options": "i"},
            "is_active": True
        })

        if existing_session:
            # Join existing session
            session_id = str(existing_session["_id"])

            # Add user as participant if not already counted
            # For simplicity, we'll just increment participant count (in a real app,
            # we'd check if user is already in the session)
            await db.chat_sessions.update_one(
                {"_id": ObjectId(session_id)},
                {"$inc": {"participant_count": 1}, "$set": {"updated_at": datetime.now(timezone.utc)}}
            )

            # Save the message to the chat session
            chat_message = ChatMessage(
                session_id=session_id,
                user_id=chat_id,
                message_text=text,
                created_at=datetime.now(timezone.utc)
            )
            await db.chat_messages.insert_one(chat_message.dict(by_alias=True))

            # Return a special response type for GTA 6 chat
            return {
                "type": "gta6_chat",
                "data": {
                    "session_id": session_id,
                    "message": f"Welcome to the GTA 6 chat dimension! You're now chatting with other GTA 6 enthusiasts. Your message: '{text}'",
                    "participant_count": existing_session["participant_count"] + 1
                }
            }
        else:
            # Create new GTA 6 chat session
            chat_session = ChatSession(
                topic="GTA 6",
                description="Chat room for discussing Grand Theft Auto 6",
                is_active=True,
                participant_count=1,  # Current user
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc)
            )

            result = await db.chat_sessions.insert_one(chat_session.dict(by_alias=True))
            session_id = str(result.inserted_id)

            # Save the initial message
            chat_message = ChatMessage(
                session_id=session_id,
                user_id=chat_id,
                message_text=text,
                created_at=datetime.now(timezone.utc)
            )
            await db.chat_messages.insert_one(chat_message.dict(by_alias=True))

            # Return a special response type for GTA 6 chat
            return {
                "type": "gta6_chat",
                "data": {
                    "session_id": session_id,
                    "message": f"Welcome to the GTA 6 chat dimension! You're the first to join this chat. Your message: '{text}'",
                    "participant_count": 1
                }
            }

    # Handle /start command
    if text.startswith("/start"):
        # Return a special response type for start command
        return {
            "type": "start",
            "data": {}
        }

    # Handle /sell command for seller onboarding
    if text.startswith("/sell"):
        return {
            "type": "sell_onboarding",
            "data": {
                "step": 1,
                "message": "Welcome to seller onboarding! Let's get you set up as a verified seller. What's your display name? (e.g., 'Mama Mboga Nairobi')"
            }
        }

    # Handle phase B: seller discovery trigger phrases
    # Check if message starts with trigger phrases for seller discovery
    trigger_phrases = ["sell ", "sell:", "where to buy ", "where to buy:", "find seller ", "find seller:"]
    is_seller_discovery = any(text_lower.startswith(phrase) for phrase in trigger_phrases)

    if is_seller_discovery:
        # Extract the product/search term after the trigger phrase
        search_term = text_lower
        for phrase in trigger_phrases:
            if text_lower.startswith(phrase):
                search_term = text_lower[len(phrase):].strip()
                break

        # If there's a trailing location/category filter (e.g., "in Nairobi" or "for vegetables")
        # We'll parse simple prepositions
        location_filter = None
        category_filter = None

        # Simple parsing for common patterns
        if " in " in search_term:
            parts = search_term.split(" in ")
            search_term = parts[0].strip()
            location_filter = parts[1].strip()
        elif " for " in search_term:
            parts = search_term.split(" for ")
            search_term = parts[0].strip()
            category_filter = parts[1].strip()

        # Perform seller discovery
        db = await get_database()

        # Build query for verified, opted-in grocers
        query = {
            "verification_status": "verified",
            "opted_in_visible": True,
            "is_banned": False
        }

        # Add text search on display_name, description, or categories
        if search_term:
            # For simplicity, we'll do a text search on display_name and description
            # In a real app, we'd use text indexes or more sophisticated search
            search_regex = {"$regex": search_term, "$options": "i"}
            query["$or"] = [
                {"display_name": search_regex},
                {"description": search_regex},
                {"categories": {"$in": [search_term]}}  # Exact match on category
            ]

        # Add location filter if specified
        if location_filter:
            location_regex = {"$regex": location_filter, "$options": "i"}
            query["town"] = location_regex

        # Add category filter if specified
        if category_filter:
            query["categories"] = {"$in": [category_filter]}

        # Find matching grocers (limit to 10 for display)
        grocers_cursor = db.grocers.find(query).limit(10)
        grocers = await grocers_cursor.to_list(length=10)

        if not grocers:
            # No sellers found
            return {
                "type": "seller_discovery_results",
                "data": {
                    "message": f"No verified sellers found for '{search_term}'{' in ' + location_filter if location_filter else ''}{' for ' + category_filter if category_filter else ''}.\n\nTry a different search term or check spelling.",
                    "sellers": []
                }
            }

        # Format results for display (we'll use a simple text format for now)
        # In a real implementation, we might generate an image or use inline keyboards
        seller_list_text = f"Found {len(grocers)} verified seller(s) for '{search_term}'"
        if location_filter:
            seller_list_text += f" in {location_filter}"
        if category_filter:
            seller_list_text += f" selling {category_filter}"
        seller_list_text += ":\n\n"

        for i, grocer in enumerate(grocers, 1):
            seller_list_text += f"{i}. {grocer['display_name']} "
            if 'town' in grocer:
                seller_list_text += f"({grocer['town']}) "
            seller_list_text += f"- Rating: {grocer.get('rating_average', 0):.1f}/5 ({grocer.get('review_count', 0)} reviews)\n"

        seller_list_text += "\nReply with the number of the seller you'd like to contact (e.g., '1')"

        # Store the search results in temporary context for the next step
        # In a real app, we'd use a proper session/store, but for simplicity we'll
        # encode the search parameters in a way we can retrieve them
        # For now, we'll just return the data and handle selection in the webhook

        return {
            "type": "seller_discovery_results",
            "data": {
                "message": seller_list_text,
                "sellers": grocers,
                "search_term": search_term,
                "location_filter": location_filter,
                "category_filter": category_filter
            }
        }

    # Handle seller selection (when user replies with a number after seeing seller results)
    # This would be handled by checking if we have recent seller search context
    # For simplicity in this implementation, we'll check if the message is just a number
    # and if there was a recent seller search (in a real app, we'd store this in user session)
    elif text.strip().isdigit():
        # Check if this looks like a seller selection (simple heuristic)
        # In a real implementation, we'd store the search context in a user session
        choice_num = int(text.strip())
        if 1 <= choice_num <= 10:  # Reasonable range for a list of sellers
            # We would normally look up the user's recent search, but for simplicity
            # we'll just acknowledge the selection and simulate the next step
            # A proper implementation would store the search results in a temporary
            # collection or cache keyed by user ID

            # For now, let's return a placeholder indicating selection was received
            # In a complete implementation, this would:
            # 1. Retrieve the stored search results for this user
            # 2. Select the chosen seller
            # 3. Create a ChatRequest document
            # 4. Notify the seller of the request

            return {
                "type": "seller_selection",
                "data": {
                    "selected_index": choice_num - 1,  # Zero-based index
                    "message": f"You selected option {choice_num}. Please wait while we connect you with the seller...",
                    "note": "In a full implementation, this would create a chat request and notify the seller."
                }
            }

    # Handle actual seller selection with context (simplified implementation)
    # In a real app, we would store search context in a user session or temporary collection
    # For this implementation, we'll check if the user recently performed a seller search
    # by looking for recent seller_discovery_results in their query log (simplified)
    elif text.strip().isdigit() and len(text.strip()) <= 2:  # Likely a selection number
        choice_num = int(text.strip())
        if 1 <= choice_num <= 10:
            # In a full implementation, we would:
            # 1. Retrieve the user's last seller search from a session store
            # 2. Get the selected seller from that search
            # 3. Create a ChatRequest
            # 4. Notify the seller

            # For this demo, we'll simulate the process by creating a mock request
            # In reality, you'd want to store search context per user

            return {
                "type": "seller_selection_processing",
                "data": {
                    "selected_index": choice_num - 1,
                    "message": f"You selected option {choice_num}. Processing your request..."
                }
            }

    # Handle /end command to end chat sessions
    if text.startswith("/end"):
        # Check if user is in an active chat session
        db = await get_database()

        # Find active chat sessions where user is either buyer or grocer
        # First check as buyer in ChatSession
        chat_session = await db.chat_sessions.find_one({
            "$or": [
                {"buyer_user_id": chat_id},
                # Note: We'd need to join with grocers table to check grocer's telegram_user_id
                # For simplicity, we'll just check buyer side for now
            ],
            "status": "active"
        })

        if chat_session:
            # End the session
            await db.chat_sessions.update_one(
                {"_id": chat_session["_id"]},
                {"$set": {"status": "ended_by_buyer", "ended_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc)}}
            )

            return {
                "type": "chat_ended",
                "data": {
                    "message": "Chat session ended. Thank you for using PricePoa!"
                }
            }
        else:
            # Check if user is a grocer in an active session (simplified)
            grocer = await db.grocers.find_one({"telegram_user_id": chat_id})
            if grocer:
                # Find active session where this grocer is participating
                chat_session = await db.chat_sessions.find_one({
                    "grocer_id": str(grocer["_id"]),
                    "status": "active"
                })

                if chat_session:
                    await db.chat_sessions.update_one(
                        {"_id": chat_session["_id"]},
                        {"$set": {"status": "ended_by_grocer", "ended_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc)}}
                    )

                    return {
                        "type": "chat_ended",
                        "data": {
                            "message": "Chat session ended. Thank you for using PricePoa!"
                        }
                    }

            return {
                "type": "not_found",
                "data": {"message": "You are not currently in an active chat session."}
            }

    # Enhanced logic: Check for shopping keywords OR multiple product terms
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

    # Handle GTA 6 chat dimension
    if processed["type"] == "gta6_chat":
        data = processed["data"]
        message = (
            f"🎮 GTA 6 Chat Dimension 🎮\n\n"
            f"{data['message']}\n\n"
            f"Participants in this chat: {data['participant_count']}\n\n"
            f"To leave this chat dimension, simply type any other query or command."
        )
        send_telegram_text(chat_id, message)
        return JSONResponse(status_code=200, content={"status": "accepted"})

    # Handle sell onboarding
    if processed["type"] == "sell_onboarding":
        data = processed["data"]
        step = data.get("step", 1)
        message = data["message"]

        if step == 1:
            message = (
                "📝 SELLER ONBOARDING - STEP 1/4\n\n"
                f"{message}\n\n"
                "Please reply with your display name (e.g., 'Mama Mboga Nairobi', 'Fresh Fruits Vendor')"
            )
        elif step == 2:
            message = (
                "📝 SELLER ONBOARDING - STEP 2/4\n\n"
                f"{message}\n\n"
                "Please reply with your town/city location (e.g., 'Nairobi', 'Mombasa', 'Kisumu')"
            )
        elif step == 3:
            message = (
                "📝 SELLER ONBOARDING - STEP 3/4\n\n"
                f"{message}\n\n"
                "Please reply with the categories of goods you sell (comma-separated, e.g., 'vegetables, fruits, herbs')"
            )
        elif step == 4:
            message = (
                "📝 SELLER ONBOARDING - STEP 4/4\n\n"
                f"{message}\n\n"
                "Would you like to add a photo of your stall or ID for verification? (Reply 'yes' or 'skip')"
            )
        else:
            message = "Onboarding complete! Thank you for registering as a seller."

        send_telegram_text(chat_id, message)
        return JSONResponse(status_code=200, content={"status": "accepted"})

    # Handle seller discovery results
    if processed["type"] == "seller_discovery_results":
        data = processed["data"]
        message = data["message"]
        send_telegram_text(chat_id, message)
        return JSONResponse(status_code=200, content={"status": "accepted"})

    # Handle seller selection
    if processed["type"] == "seller_selection":
        data = processed["data"]
        message = data["message"]
        note = data.get("note", "")
        if note:
            message += f"\n\n💡 {note}"
        send_telegram_text(chat_id, message)
        return JSONResponse(status_code=200, content={"status": "accepted"})

    # Handle seller selection processing (create chat request and notify seller)
    if processed["type"] == "seller_selection_processing":
        data = processed["data"]
        selected_index = data["selected_index"]

        # Get database connection
        db = await get_database()

        # TODO: In a real implementation, we would retrieve the user's search context
        # For now, we'll simulate by getting some verified grocers
        # In production, you would store search context per user (e.g., in a session store or temporary collection)

        # Get some verified grocers to simulate search results
        grocers_cursor = db.grocers.find({
            "verification_status": "verified",
            "opted_in_visible": True,
            "is_banned": False
        }).limit(10)
        grocers = await grocers_cursor.to_list(length=10)

        if not grocers or selected_index >= len(grocers):
            # Invalid selection or no grocers found
            await send_telegram_text(chat_id, "Sorry, there was an error processing your selection. Please try searching again.")
            return JSONResponse(status_code=200, content={"status": "accepted"})

        # Get the selected grocer
        selected_grocer = grocers[selected_index]

        # Create a chat request
        from datetime import datetime, timedelta

        chat_request = ChatRequest(
            buyer_user_id=chat_id,
            grocer_id=str(selected_grocer["_id"]),
            status="pending",
            buyer_message=f"Hello! I'm interested in your products. Let's discuss pricing and availability.",
            created_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
            responded_at=None
        )

        # Insert the chat request
        result = await db.chat_requests.insert_one(chat_request.dict(by_alias=True))
        request_id = str(result.inserted_id)

        # Notify the buyer that the request has been sent
        buyer_message = (
            f"Your request to connect with {selected_grocer['display_name']} has been sent! "
            f"They have 10 minutes to respond.\n\n"
            f"You'll be notified when they respond."
        )
        await send_telegram_text(chat_id, buyer_message)

        # Notify the seller (grocer) about the request
        # In a real implementation, we would send a message to the grocer's Telegram ID
        # For now, we'll log it and note that this would be implemented
        seller_notification = (
            f"New chat request!\n\n"
            f"A buyer is interested in connecting with you.\n"
            f"Your response is needed within 10 minutes.\n\n"
            f"To accept, reply with: ACCEPT {request_id}\n"
            f"To decline, reply with: DECLINE {request_id}"
        )

        # In a real implementation, we would send this to the grocer's telegram_user_id
        # await send_telegram_text(selected_grocer["telegram_user_id"], seller_notification)
        # For now, we'll just log it
        logger.info(f"Would send to grocer {selected_grocer['telegram_user_id']}: {seller_notification}")

        return JSONResponse(status_code=200, content={"status": "accepted"})

    # Handle chat ended
    if processed["type"] == "chat_ended":
        data = processed["data"]
        message = data["message"]
        send_telegram_text(chat_id, message)
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