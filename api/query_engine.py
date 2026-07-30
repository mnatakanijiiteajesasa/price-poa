"""
query_engine.py
Price query engine - looks up a product by name/alias, pulls matching
prices, optionally filters by town, and returns data shaped for the
infographic generator (see infographic/generator.py).
"""

import re
import logging
from typing import Optional, Dict, Any, List

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

# Import the product matcher for fuzzy matching
from intelligence.nlp.product_matcher import find_product_enhanced

logger = logging.getLogger("uvicorn.error")


async def find_product(db: AsyncIOMotorDatabase, query_text: str) -> Optional[dict]:
    """
    Find a single product document matching the given text using enhanced matching
    (exact + fuzzy + aliases). Returns None if nothing matches.

    Args:
        db: MongoDB database connection
        query_text: The text to search for

    Returns:
        Product document or None if not found
    """
    if not query_text or not query_text.strip():
        return None

    # Use enhanced matching (exact + fuzzy + aliases) to find the product
    product = await find_product_enhanced(db, query_text.strip())

    if product:
        logger.info(f"Found product '{product['name']}' for query '{query_text}' using enhanced matching")
    else:
        logger.info(f"No product matched query_text={query_text!r} using enhanced matching")

    return product


async def get_product_prices(
    db,
    product: dict,
    town: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Given a product document, fetch all matching prices, optionally
    filtered by town, and return data shaped for
    infographic.generator.generate_single_product_image().

    Returns None if there are no prices at all for this product
    (optionally, after the town filter).
    """
    product_id = str(product["_id"])

    prices = await db.prices.find({"product_id": product_id}).to_list(length=None)
    if not prices:
        logger.info(f"No prices found for product_id={product_id}")
        return None

    store_ids = list({p["store_id"] for p in prices})
    stores = await db.stores.find(
        {"_id": {"$in": [ObjectId(sid) for sid in store_ids]}}
    ).to_list(length=None)
    stores_by_id = {str(s["_id"]): s for s in stores}

    if town:
        town_lower = town.strip().lower()
        matching_store_ids = {
            sid for sid, s in stores_by_id.items()
            if s.get("town", "").strip().lower() == town_lower
        }
        prices = [p for p in prices if p["store_id"] in matching_store_ids]
        if not prices:
            logger.info(f"No prices found for product_id={product_id} in town={town}")
            return None

    # Rank cheapest first
    prices.sort(key=lambda p: p["price_kes"])

    store_entries: List[dict] = []
    for price in prices:
        store = stores_by_id.get(price["store_id"])
        if not store:
            continue  # orphaned reference, skip rather than crash
        store_entries.append({
            "name": f"{store['chain_name']} - {store['branch_name']}",
            "price": f"{price['price_kes']:.0f} KES",
            "offer": bool(price.get("is_promotional", False)),
        })

    if not store_entries:
        return None

    latest_verified = max(p["verified_at"] for p in prices)

    return {
        "product_name": product["name"],
        "stores": store_entries,
        "date": latest_verified.strftime("%Y-%m-%d"),
    }


async def query_single_product(
    db,
    query_text: str,
    town: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    End-to-end lookup: text -> matching product -> ranked prices.
    Returns None if the product isn't found, or if it's found but has
    no matching prices (optionally, after the town filter).
    """
    product = await find_product(db, query_text)
    if product is None:
        logger.info(f"No product matched query_text={query_text!r}")
        return None

    return await get_product_prices(db, product, town=town)