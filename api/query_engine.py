"""
query_engine.py
Thin orchestration layer for product search using the new search pipeline.
All search logic resides exclusively in intelligence/nlp/search_pipeline.
"""

import logging
from typing import Optional, Dict, Any
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
from intelligence.nlp.search_pipeline import search_products

logger = logging.getLogger("uvicorn.error")


async def get_product_by_id(db: AsyncIOMotorDatabase, product_id: str) -> Optional[Dict[str, Any]]:
    """
    Helper function to fetch a product document by ID.

    Args:
        db: MongoDB database connection
        product_id: Product ID string

    Returns:
        Product document or None
    """
    try:
        object_id = ObjectId(product_id)
        return await db.products.find_one({"_id": object_id})
    except Exception as e:
        logger.warning(f"Error fetching product {product_id}: {e}")
        return None


async def find_product(db: AsyncIOMotorDatabase, query_text: str) -> Optional[Dict[str, Any]]:
    """
    Find a single product document matching the given text using the search pipeline.

    Responsibilities:
    1. Validate query
    2. Call search_pipeline.search_products(limit=1)
    3. Fetch MongoDB document using returned product_id
    4. Attach metadata (_match_type, _confidence)
    5. Return product document or None

    Does NOT perform any internal searching or fallback logic.

    Args:
        db: MongoDB database connection
        query_text: Text to search for

    Returns:
        Product document with added metadata or None
    """
    if not query_text or not query_text.strip():
        return None

    try:
        # Import here to avoid circular imports and allow graceful degradation
        from intelligence.nlp.search_pipeline import search_products

        # Get top result from search pipeline (limit=1)
        results = await search_products(db, query_text, limit=1, vector_limit=50)

        if not results:
            return None

        result = results[0]
        product_id = result.get("product_id")

        if not product_id:
            logger.warning("Search result missing product_id")
            return None

        # Fetch the full product document from MongoDB
        product = await get_product_by_id(db, product_id)
        if not product:
            logger.warning(f"Product {product_id} not found in MongoDB")
            return None

        # Attach metadata from search pipeline result
        product["_match_type"] = result.get("match_type", "pipeline")
        product["_confidence"] = result.get("final_score", 0.0)

        return product

    except Exception as e:
        logger.exception(f"Error in find_product for query '{query_text}': {e}")
        return None


async def get_product_prices(
    db: AsyncIOMotorDatabase,
    product: Dict[str, Any],
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

    store_entries: list[dict] = []
    for price in prices:
        store = stores_by_id.get(price["store_id"])
        if not store:
            continue  # orphaned reference, skip rather than crash
        store_entries.append({
            "name": f"{store['chain']} - {store['branch']}",
            "price": f"{price['price_kes']:.0f} KES",
            "offer": bool(price.get("is_promotional", False)),
        })

    if not store_entries:
        return None

    latest_verified = max(p["verified_at"] for p in prices)

    return {
        "product_name": product.get("name", "Unknown Product"),
        "stores": store_entries,
        "date": latest_verified.strftime("%Y-%m-%d"),
    }


async def query_single_product(
    db: AsyncIOMotorDatabase,
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


def parse_price_value(price_str: str) -> float:
    """Extract a float from strings like '479 KES' for sorting purposes."""
    cleaned = ''.join(c for c in str(price_str) if c.isdigit() or c == '.')
    try:
        return float(cleaned) if cleaned else 0.0
    except ValueError:
        return 0.0


async def get_products_by_ids(
    db: AsyncIOMotorDatabase,
    product_ids: list[str],
) -> list[Dict[str, Any]]:
    """
    Fetch multiple products while preserving the order of product_ids.
    """

    object_ids = []

    for pid in product_ids:
        try:
            object_ids.append(ObjectId(pid))
        except Exception:
            continue

    products = await db.products.find(
        {
            "_id": {
                "$in": object_ids
            }
        }
    ).to_list(length=None)

    lookup = {
        str(product["_id"]): product
        for product in products
    }

    return [
        lookup[pid]
        for pid in product_ids
        if pid in lookup
    ]


async def find_product_matches(
    db: AsyncIOMotorDatabase,
    query_text: str,
    limit: int = 10,
) -> list[Dict[str, Any]]:
    """
    Return multiple matching products using the unified search pipeline.

    Responsibilities:
    1. Call search_products()
    2. Fetch MongoDB documents
    3. Attach cheapest current price
    4. Return formatted results

    No searching, ranking, fuzzy matching or vector search happens here.
    """

    if not query_text or not query_text.strip():
        return []

    try:
        # Ask the pipeline for the best products
        search_results = await search_products(
            db,
            query_text,
            limit=limit,
        )

        if not search_results:
            return []

        # Preserve pipeline ranking
        ordered_ids = [
            r["product_id"]
            for r in search_results
            if r.get("product_id")
        ]

        products = await get_products_by_ids(db, ordered_ids)

        results = []

        for product in products:

            prices = await get_product_prices(db, product)

            if not prices or not prices.get("stores"):
                continue

            cheapest = prices["stores"][0]

            results.append({
                "product_id": str(product["_id"]),
                "name": product.get("name", "Unknown"),
                "price_label": cheapest["price"],
                "price_value": parse_price_value(cheapest["price"]),
                "store_name": cheapest["name"],
                "offer": cheapest["offer"],
                "confidence": next(
                    (
                        r.get("final_score", 0.0)
                        for r in search_results
                        if r["product_id"] == str(product["_id"])
                    ),
                    0.0,
                ),
                "match_type": next(
                    (
                        r.get("match_type", "pipeline")
                        for r in search_results
                        if r["product_id"] == str(product["_id"])
                    ),
                    "pipeline",
                ),
            })

        return results

    except Exception:
        logger.exception(
            "Failed to retrieve product matches for query '%s'",
            query_text,
        )
        return []

# Backward compatibility alias
find_product_fuzzy = find_product