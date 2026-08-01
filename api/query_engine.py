"""
query_engine.py
Price query engine - looks up a product by name/alias, pulls matching
prices, optionally filters by town, and returns data shaped for the
infographic generator (see infographic/generator.py).
"""

import re
import logging
import os
from typing import Optional, Dict, Any, List, Tuple

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

logger = logging.getLogger("uvicorn.error")

# Import enhanced product matcher for fuzzy matching
try:
    from intelligence.nlp.product_matcher import find_product_enhanced
    # Import rapidfuzz for direct fuzzy matching if needed
    from rapidfuzz import fuzz, process
except ImportError as e:
    logger.warning(f"Could not import enhanced product matcher: {e}")
    # Fallback functions
    async def find_product_enhanced(db, query_text):
        return None
    fuzz = None
    process = None

# Import Qdrant client for vector search
try:
    from qdrant_client import QdrantClient
    from qdrant_client.http import models as rest
    from qdrant_client.http.models import PointStruct
    QDRANT_AVAILABLE = True
except ImportError:
    QDRANT_AVAILABLE = False
    logger.warning("Qdrant client not available. Vector search will be disabled.")


class VectorSearchService:
    """Service for handling vector-based product search using Qdrant."""

    _model = None  # Class-level cache for the sentence transformer model

    def __init__(self):
        self.client = None
        self.collection_name = "product_embeddings"
        self.vector_size = 384  # Default for sentence-transformers/all-MiniLM-L6-v2
        self._initialize_client()
        self._initialize_model()

    def _initialize_client(self):
        """Initialize Qdrant client connection."""
        if not QDRANT_AVAILABLE:
            return

        try:
            qdrant_host = os.getenv("QDRANT_HOST", "localhost")
            qdrant_port = int(os.getenv("QDRANT_PORT", "6333"))

            self.client = QdrantClient(host=qdrant_host, port=qdrant_port)

            # Try to get collection info, create if doesn't exist
            try:
                self.client.get_collection(self.collection_name)
                logger.info(f"Connected to existing Qdrant collection: {self.collection_name}")
            except Exception:
                # Collection doesn't exist, create it
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=rest.VectorParams(
                        size=self.vector_size,
                        distance=rest.Distance.COSINE
                    )
                )
                logger.info(f"Created new Qdrant collection: {self.collection_name}")

        except Exception as e:
            logger.warning(f"Failed to initialize Qdrant client: {e}")
            self.client = None

    def _initialize_model(self):
        """Initialize sentence transformer model for text encoding."""
        if VectorSearchService._model is not None:
            return

        try:
            from sentence_transformers import SentenceTransformer
            VectorSearchService._model = SentenceTransformer('all-MiniLM-L6-v2')
            logger.info("Loaded sentence transformer model: all-MiniLM-L6-v2")
        except Exception as e:
            logger.warning(f"Failed to load sentence transformer model: {e}")
            VectorSearchService._model = None

    async def search_similar_products(self, query_text: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Search for similar products using vector embeddings.

        Args:
            query_text: Text to search for
            limit: Maximum number of results to return

        Returns:
            List of product matches with scores and product IDs
        """
        if not self.client or VectorSearchService._model is None:
            logger.warning("Qdrant client or sentence transformer model not available for vector search")
            return []

        try:
            # Encode the query text to a vector
            vector = VectorSearchService._model.encode(query_text).tolist()

            # Search in Qdrant
            search_result = self.client.search(
                collection_name=self.collection_name,
                query_vector=vector,
                limit=limit,
                with_payload=True  # We need the payload to get the product ID
            )

            # Format results
            results = []
            for point in search_result:
                payload = point.payload or {}
                product_id = payload.get("product_id")
                if product_id:
                    results.append({
                        "product_id": product_id,
                        "score": point.score,
                        "payload": payload  # Include full payload for potential future use
                    })

            logger.info(f"Vector search for '{query_text}' returned {len(results)} results")
            return results

        except Exception as e:
            logger.error(f"Error performing vector search: {e}")
            return []


# Initialize vector search service
vector_search_service = VectorSearchService()


async def find_product(db, query_text: str) -> Optional[dict]:
    """
    Find a single product document matching the given text using enhanced fuzzy matching
    with RapidFuzz, falling back to exact matching, and enhanced with vector search.

    Args:
        db: MongoDB database connection
        query_text: Text to search for

    Returns:
        Product document or None
    """
    if not query_text or not query_text.strip():
        return None

    try:
        # First try enhanced fuzzy matching (includes RapidFuzz, phonetic, aliases)
        product = await find_product_enhanced(db, query_text)
        if product:
            product["_match_type"] = "enhanced_fuzzy"
            product["_confidence"] = getattr(product, '_confidence', 0.8)
            return product

    except Exception as e:
        logger.warning(f"Enhanced product matching failed: {e}")

    try:
        # Fallback to original exact matching if enhanced fails
        escaped = re.escape(query_text.strip())
        pattern = f"^{escaped}$"
        query = {
            "$or": [
                {"name": {"$regex": pattern, "$options": "i"}},
                {"swahili_aliases": {"$elemMatch": {"$regex": pattern, "$options": "i"}}},
                {"sheng_aliases": {"$elemMatch": {"$regex": pattern, "$options": "i"}}},
            ]
        }
        product = await db.products.find_one(query)
        if product:
            product["_match_type"] = "exact"
            product["_confidence"] = 1.0
            return product
    except Exception as e:
        logger.warning(f"Exact matching failed: {e}")

    # If both fail, return None
    return None


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
        "product_name": product.get("name", "Unknown Product"),
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


# Additional function for hybrid search (vector + fuzzy)
async def find_product_hybrid(db, query_text: str, limit: int = 10) -> List[Dict[str, Any]]:
    """
    Find products using hybrid approach: vector search + fuzzy matching.

    Args:
        db: MongoDB database connection
        query_text: Text to search for
        limit: Maximum number of results to return

    Returns:
        List of product matches sorted by relevance score
    """
    if not query_text or not query_text.strip():
        return []

    results = []

    # Get fuzzy matches using rapidfuzz (returns product documents)
    try:
        fuzzy_matches = await _get_fuzzy_matches(db, query_text, limit)
        results.extend(fuzzy_matches)
    except Exception as e:
        logger.warning(f"Fuzzy matching failed: {e}")

    # Get vector matches (returns product IDs and scores)
    try:
        vector_matches = await vector_search_service.search_similar_products(query_text, limit)
        # Fetch product documents for the vector matches
        for match in vector_matches:
            product_id = match.get("product_id")
            if product_id:
                try:
                    # Try to handle both string and ObjectId formats
                    if isinstance(product_id, str) and len(product_id) == 24:
                        object_id = ObjectId(product_id)
                    else:
                        object_id = ObjectId(product_id)  # Let ObjectId handle validation

                    product_doc = await db.products.find_one({"_id": object_id})
                    if product_doc:
                        # Add metadata to indicate it's a vector match
                        product_doc["_match_type"] = "vector"
                        product_doc["_confidence"] = match.get("score", 0.0)
                        product_doc["_vector_score"] = match.get("score", 0.0)
                        results.append(product_doc)
                except Exception as e:
                    logger.warning(f"Error fetching product {product_id} from vector match: {e}")
    except Exception as e:
        logger.warning(f"Vector search failed: {e}")

    # Deduplicate and rank results
    if results:
        # Remove duplicates by product_id, keeping highest score
        seen_products = {}
        for result in results:
            pid = str(result.get("_id"))
            # Determine score: use _confidence for fuzzy/enhanced, _vector_score for vector, default 0.5
            score = result.get("_confidence") or result.get("_vector_score") or 0.5
            if pid and (pid not in seen_products or score > seen_products[pid].get("score", 0)):
                seen_products[pid] = {
                    "document": result,
                    "score": score
                }

        # Sort by score descending
        results = sorted(
            [v["document"] for v in seen_products.values()],
            key=lambda x: x.get("_confidence") or x.get("_vector_score") or 0.5,
            reverse=True
        )
        return results[:limit]

    return []


async def _get_fuzzy_matches(db, query_text: str, limit: int) -> List[Dict[str, Any]]:
    """
    Get fuzzy matches using rapidfuzz.

    Args:
        db: MongoDB database connection
        query_text: Text to search for
        limit: Maximum number of results

    Returns:
        List of fuzzy matches (product documents)
    """
    try:
        # Get all product names and aliases for matching
        products_cursor = db.products.find(
            {},
            {
                "_id": 1,
                "name": 1,
                "swahili_aliases": 1,
                "sheng_aliases": 1
            }
        )
        products = await products_cursor.to_list(length=None)

        # Create searchable terms
        search_terms = []
        product_map = {}  # Maps search term to product info

        for product in products:
            product_id = str(product["_id"])
            name = product.get("name", "").strip()
            swahili_aliases = [alias.strip() for alias in product.get("swahili_aliases", [])]
            sheng_aliases = [alias.strip() for alias in product.get("sheng_aliases", [])]

            # Add main name
            if name:
                search_terms.append(name.lower())
                product_map[name.lower()] = {
                    "product_id": product_id,
                    "product_name": name,
                    "match_type": "exact",
                    "confidence": 1.0
                }

            # Add Swahili aliases
            for alias in swahili_aliases:
                if alias:
                    search_terms.append(alias.lower())
                    product_map[alias.lower()] = {
                        "product_id": product_id,
                        "product_name": name,
                        "match_type": "swahili_alias",
                        "confidence": 0.95
                    }

            # Add Sheng aliases
            for alias in sheng_aliases:
                if alias:
                    search_terms.append(alias.lower())
                    product_map[alias.lower()] = {
                        "product_id": product_id,
                        "product_name": name,
                        "match_type": "sheng_alias",
                        "confidence": 0.9
                    }

        # Use rapidfuzz for fuzzy matching
        if process and search_terms:
            matches = process.extract(
                query_text.lower(),
                search_terms,
                scorer=fuzz.WRatio,
                limit=limit * 2  # Get more to account for duplicates
            )

            results = []
            seen_products = set()

            for match_term, score, _ in matches:
                if score >= 60:  # Minimum similarity threshold
                    product_info = product_map.get(match_term)
                    if product_info:
                        pid = product_info["product_id"]
                        if pid not in seen_products:
                            seen_products.add(pid)
                            # Fetch full product document
                            product_doc = await db.products.find_one({"_id": ObjectId(pid)})
                            if product_doc:
                                product_doc["_match_type"] = product_info["match_type"]
                                product_doc["_confidence"] = score / 100.0
                                product_doc["_matched_term"] = match_term
                                results.append(product_doc)

            return results[:limit]

    except Exception as e:
        logger.error(f"Error in fuzzy matching: {e}")

    return []


# Backward compatibility alias
find_product_fuzzy = find_product