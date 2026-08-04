"""
Retrieval module for the search pipeline.
Orchestrates the complete search pipeline: normalization, parsing, vector search,
RapidFuzz re-ranking, and business rule ranking.
"""

import asyncio
import logging
import time
from typing import List, Dict, Any, Optional, Tuple
from motor.motor_asyncio import AsyncIOMotorDatabase

# Import pipeline components
from .normalizer import normalize_text, normalize_query
from .query_parser import parse_query, ParsedQuery
from .vector_search import EnhancedVectorSearchService
from .ranker import rank_search_results, RankedResult
from .product_representation import product_to_embedding_text

logger = logging.getLogger(__name__)

# Try to import RapidFuzz (will be handled gracefully if not available)
try:
    from rapidfuzz import fuzz, process
    RAPIDFUZZ_AVAILABLE = True
except ImportError:
    RAPIDFUZZ_AVAILABLE = False
    logger.warning("RapidFuzz not available, fuzzy matching will be limited")

class SearchPipeline:
    """
    Orchestrates the complete search pipeline:
    1. Normalize Query
    2. Parse Query
    3. Vector Search (Top 50)
    4. RapidFuzz Re-ranking
    5. Business Rule Ranking
     Ranking
    6. Return Top 6. Return Top 20
    """

    def __init__(self, db: AsyncIOMotorDatabase):
        """
        Initialize the search pipeline.

        Args:
            db: MongoDB database connection
        """
        self.db = db
        self.vector_service = EnhancedVectorSearchService()
        self._rapidfuzz_cache = {}
        self._cache_timestamps = {}
        self._initialize_rapidfuzz_config()

    def _initialize_rapidfuzz_config(self):
        """Initialize RapidFuzz configuration."""
        self.rapidfuzz_config = {
            'score_cutoff': 60,
            'limit_multiplier': 2,
            'scorer': fuzz.WRatio if RAPIDFUZZ_AVAILABLE else None
        }

    async def search(
        self,
        query_text: str,
        limit: int = 20,
        vector_limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Execute the complete search pipeline.

        Args:
            query_text: User query string
            limit: Maximum number of final results to return
            vector_limit: Number of results to retrieve from vector search

        Returns:
            List of search results with detailed scoring information
        """
        start_time = time.time()

        try:
            # Step 1: Normalize Query
            logger.debug(f"Normalizing query: '{query_text}'")
            normalized_result = normalize_query(query_text)
            normalized_query = normalized_result.normalized

            # Step 2: Parse Query
            logger.debug(f"Parsing normalized query: '{normalized_query}'")
            parsed_query = parse_query(normalized_query)

            # Step 3: Vector Search (Top 50)
            logger.debug(f"Performing vector search for: '{normalized_query}' (limit: {vector_limit})")
            vector_results = await self.vector_service.search_similar_products(
                query_text=normalized_query,
                limit=vector_limit,
                score_threshold=0.1  # Low threshold to get more candidates
            )

            # Step 4: RapidFuzz Re-ranking (on vector results only)
            logger.debug(f"Performing RapidFuzz re-ranking on {len(vector_results)} vector results")
            fuzzy_results = await self._rapidfuzz_rerank(
                query_text=normalized_query,
                vector_results=vector_results,
                limit=vector_limit
            )

            # Step 5: Business Rule Ranking
            logger.debug("Applying business rule ranking")
            ranked_results = rank_search_results(
                vector_results=vector_results,
                fuzzy_results=fuzzy_results,
                parsed_query=parsed_query
            )

            # Step 6: Return Top 20
            final_results = ranked_results[:limit]

            # Format results for output
            formatted_results = []
            for result in final_results:
                formatted_result = {
                    "product_id": result.product_id,
                    "product_name": result.product_name,
                    "vector_score": result.scores.vector_score,
                    "fuzzy_score": result.scores.fuzzy_score,
                    "brand_score": result.scores.brand_score,
                    "category_score": result.scores.category_score,
                    "quantity_score": result.scores.quantity_score,
                    "alias_score": result.scores.alias_score,
                    "final_score": result.scores.final_score,
                    "payload": result.payload,
                    "rank": result.rank
                }
                formatted_results.append(formatted_result)

            elapsed_time = time.time() - start_time
            logger.info(f"Search pipeline completed in {elapsed_time:.3f}s, returned {len(formatted_results)} results")

            return formatted_results

        except Exception as e:
            logger.error(f"Error in search pipeline: {e}")
            # Return empty results on error
            return []

    async def _rapidfuzz_rerank(
        self,
        query_text: str,
        vector_results: List[Dict[str, Any]],
        limit: int
    ) -> List[Dict[str, Any]]:
        """
        Apply RapidFuzz re-ranking to vector search results.

        Args:
            query_text: Normalized query text
            vector_results: Results from vector search
            limit: Maximum number of results to consider

        Returns:
            List of fuzzy match results with scores
        """
        if not RAPIDFUZZ_AVAILABLE or not vector_results:
            return []

        try:
            # Check cache
            cache_key = f"{query_text}:{hash(str(vector_results))}"
            if self._is_cache_valid(cache_key):
                logger.debug("Using cached RapidFuzz results")
                return self._rapidfuzz_cache[cache_key]

            # Prepare search terms from vector results
            search_terms = []
            product_map = {}  # Maps search term to product info

            for result in vector_results:
                payload = result.get("payload", {})
                product_id = result.get("product_id")
                if not product_id:
                    continue

                # Extract text for matching
                product_name = payload.get("product_name", "")
                brand = payload.get("brand", "")
                category = payload.get("category", "")
                aliases = payload.get("aliases", [])

                # Add all searchable terms
                terms_to_index = []
                if product_name:
                    terms_to_index.append(product_name)
                if brand:
                    terms_to_index.append(brand)
                if category:
                    terms_to_index.append(category)
                terms_to_index.extend(aliases)

                for term in terms_to_index:
                    if term and term.strip():
                        term_lower = term.lower().strip()
                        search_terms.append(term_lower)
                        product_map[term_lower] = {
                            "product_id": product_id,
                            "product_name": product_name,
                            "brand": brand,
                            "category": category,
                            "size": payload.get("size"),
                            "unit": payload.get("unit")
                        }

            if not search_terms:
                logger.warning("No search terms available for RapidFuzz matching")
                return []

            # Use RapidFuzz to find matches
            matches = process.extract(
                query_text.lower(),
                search_terms,
                scorer=self.rapidfuzz_config['scorer'],
                limit=limit * self.rapidfuzz_config['limit_multiplier'],
                score_cutoff=self.rapidfuzz_config['score_cutoff']
            )

            # Format results
            fuzzy_results = []
            seen_products = set()

            for match_term, score, _ in matches:
                product_info = product_map.get(match_term)
                if product_info:
                    pid = product_info["product_id"]
                    if pid not in seen_products:
                        seen_products.add(pid)
                        # Fetch full product document to get all details
                        product_doc = await self._fetch_product_document(pid)
                        if product_doc:
                            # Convert score to 0-1 range
                            normalized_score = score / 100.0

                            fuzzy_result = {
                                "product_id": pid,
                                "score": normalized_score,
                                "confidence": normalized_score,
                                "matched_term": match_term,
                                "match_type": "rapidfuzz",
                                "payload": {
                                    "product_name": product_doc.get("name", ""),
                                    "brand": product_doc.get("brand"),
                                    "category": product_doc.get("category"),
                                    "sizes_variants": product_doc.get("sizes_variants", []),
                                    "swahili_aliases": product_doc.get("swahili_aliases", []),
                                    "sheng_aliases": product_doc.get("sheng_aliases", [])
                                }
                            }
                            fuzzy_results.append(fuzzy_result)

            # Sort by score descending
            fuzzy_results.sort(key=lambda x: x["score"], reverse=True)

            # Limit results
            fuzzy_results = fuzzy_results[:limit]

            # Cache results
            self._rapidfuzz_cache[cache_key] = fuzzy_results
            self._cache_timestamps[cache_key] = time.time()

            logger.debug(f"RapidFuzz re-ranking produced {len(fuzzy_results)} results")
            return fuzzy_results

        except Exception as e:
            logger.error(f"Error in RapidFuzz re-ranking: {e}")
            return []

    async def _fetch_product_document(self, product_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetch a product document from MongoDB by ID.

        Args:
            product_id: Product ID string

        Returns:
            Product document or None if not found
        """
        try:
            from bson import ObjectId
            object_id = ObjectId(product_id)
            product = await self.db.products.find_one({"_id": object_id})
            return product
        except Exception as e:
            logger.warning(f"Error fetching product {product_id}: {e}")
            return None

    def _is_cache_valid(self, cache_key: str) -> bool:
        """
        Check if a cached result is still valid.

        Args:
            cache_key: Cache key to check

        Returns:
            True if cache is valid, False otherwise
        """
        if cache_key not in self._rapidfuzz_cache:
            return False

        if cache_key not in self._cache_timestamps:
            return False

        # Cache TTL: 5 minutes
        ttl_seconds = 300
        age = time.time() - self._cache_timestamps[cache_key]
        return age < ttl_seconds

    def clear_cache(self):
        """Clear the RapidFuzz cache."""
        self._rapidfuzz_cache.clear()
        self._cache_timestamps.clear()
        logger.info("RapidFuzz cache cleared")

# Convenience function for external use
async def search_products(
    db: AsyncIOMotorDatabase,
    query_text: str,
    limit: int = 20,
    vector_limit: int = 50
) -> List[Dict[str, Any]]:
    """
    Convenience function to execute the search pipeline.

    Args:
        db: MongoDB database connection
        query_text: User query string
        limit: Maximum number of final results to return
        vector_limit: Number of results to retrieve from vector search

    Returns:
        List of search results with detailed scoring information
    """
    pipeline = SearchPipeline(db)
    return await pipeline.search(query_text, limit, vector_limit)