"""
Natural Language Processing module for Product Matching.
Enhances product search with fuzzy matching, typo tolerance, and semantic understanding.
"""
import re
import logging
from typing import List, Dict, Any, Optional, Tuple
from difflib import SequenceMatcher
import jellyfish  # For phonetic matching
from motor.motor_asyncio import AsyncIOMotorDatabase

logger = logging.getLogger(__name__)


class ProductMatcher:
    """
    Enhanced product matcher that uses fuzzy matching, phonetic algorithms,
    and semantic understanding to find products even with typos or incomplete names.
    """

    def __init__(self, db: AsyncIOMotorDatabase):
        """
        Initialize the product matcher.

        Args:
            db: MongoDB database connection
        """
        self.db = db
        self._product_cache = {}  # Simple cache for product names
        self._cache_timeout = 300  # 5 minutes
        self._last_cache_update = 0

    async def _load_product_index(self) -> Dict[str, Dict]:
        """
        Load all product names and aliases into memory for fast matching.
        Includes name, swahili_aliases, and sheng_aliases.

        Returns:
            Dictionary mapping normalized product names to product documents
        """
        import time

        # Check if cache is still valid
        current_time = time.time()
        if (self._product_cache and
            (current_time - self._last_cache_update) < self._cache_timeout):
            return self._product_cache

        logger.info("Loading product index for fuzzy matching...")
        products_collection = self.db.products

        # Fetch all products with their names and aliases
        cursor = products_collection.find(
            {},
            {
                "_id": 1,
                "name": 1,
                "swahili_aliases": 1,
                "sheng_aliases": 1,
                "category": 1
            }
        )

        products = await cursor.to_list(length=None)

        # Build index
        index = {}
        for product in products:
            product_id = str(product["_id"])
            name = product.get("name", "").strip().lower()
            swahili_aliases = [alias.strip().lower() for alias in product.get("swahili_aliases", [])]
            sheng_aliases = [alias.strip().lower() for alias in product.get("sheng_aliases", [])]

            # Add main name
            if name:
                index[name] = {
                    "product_id": product_id,
                    "product_name": product["name"],
                    "match_type": "exact",
                    "confidence": 1.0
                }

            # Add Swahili aliases
            for alias in swahili_aliases:
                if alias:
                    index[alias] = {
                        "product_id": product_id,
                        "product_name": product["name"],
                        "match_type": "swahili_alias",
                        "confidence": 0.95
                    }

            # Add Sheng aliases
            for alias in sheng_aliases:
                    if alias:
                        index[alias] = {
                            "product_id": product_id,
                            "product_name": product["name"],
                            "match_type": "sheng_alias",
                            "confidence": 0.9
                        }

        self._product_cache = index
        self._last_cache_update = current_time
        logger.info(f"Loaded {len(index)} product name/alias entries into search index")

        return index

    def _calculate_similarity(self, str1: str, str2: str) -> float:
        """
        Calculate similarity between two strings using multiple methods.

        Args:
            str1: First string
            str2: Second string

        Returns:
            Similarity score between 0 and 1
        """
        if not str1 or not str2:
            return 0.0

        # Normalize strings
        s1 = str1.strip().lower()
        s2 = str2.strip().lower()

        # Exact match
        if s1 == s2:
            return 1.0

        # Check if one contains the other (for partial matches)
        if s1 in s2 or s2 in s1:
            shorter = min(len(s1), len(s2))
            longer = max(len(s1), len(s2))
            return 0.7 + (0.3 * shorter / longer)  # Base 0.7 + length ratio bonus

        # Use SequenceMatcher for similarity
        similarity = SequenceMatcher(None, s1, s2).ratio()

        # Boost score for matching first letters
        if s1[0] == s2[0]:
            similarity = min(1.0, similarity + 0.1)

        # Boost for similar length
        len_diff = abs(len(s1) - len(s2))
        max_len = max(len(s1), len(s2))
        if max_len > 0:
            length_penalty = len_diff / max_len
            similarity = max(0, similarity - (length_penalty * 0.3))

        return similarity

    def _phonetic_match(self, str1: str, str2: str) -> float:
        """
        Check phonetic similarity using Soundex and Metaphone.

        Args:
            str1: First string
            str2: Second string

        Returns:
            Phonetic similarity score between 0 and 1
        """
        if not str1 or not str2:
            return 0.0

        try:
            # Soundex comparison
            soundex1 = jellyfish.soundex(str1)
            soundex2 = jellyfish.soundex(str2)
            soundex_match = 1.0 if soundex1 == soundex2 else 0.0

            # Metaphone comparison
            metaphone1 = jellyfish.metaphone(str1)
            metaphone2 = jellyfish.metaphone(str2)
            metaphone_match = 1.0 if metaphone1 == metaphone2 else 0.0

            # Return average of phonetic matches
            return (soundex_match + metaphone_match) / 2.0
        except Exception as e:
            logger.warning(f"Error in phonetic matching: {e}")
            return 0.0

    async def find_product_fuzzy(self, query_text: str, threshold: float = 0.6) -> List[Dict[str, Any]]:
        """
        Find products using fuzzy matching against product names and aliases.

        Args:
            query_text: User's search query
            threshold: Minimum similarity score to consider a match (0-1)

        Returns:
            List of matched products sorted by confidence score
        """
        if not query_text or not query_text.strip():
            return []

        query_clean = query_text.strip().lower()
        product_index = await self._load_product_index()

        matches = []

        # Check each product in our index
        for indexed_term, product_info in product_index.items():
            # Calculate similarity scores
            similarity_score = self._calculate_similarity(query_clean, indexed_term)
            phonetic_score = self._phonetic_match(query_clean, indexed_term)

            # Combined score (weighted average)
            combined_score = (similarity_score * 0.7) + (phonetic_score * 0.3)

            # Boost score if it's an exact match type
            if product_info["match_type"] == "exact":
                combined_score = min(1.0, combined_score + 0.1)
            elif product_info["match_type"] in ["swahili_alias", "sheng_alias"]:
                combined_score = min(1.0, combined_score + 0.05)

            # Only include if above threshold
            if combined_score >= threshold:
                match_result = product_info.copy()
                match_result["confidence"] = round(combined_score, 3)
                match_result["matched_term"] = indexed_term
                match_result["query_term"] = query_clean
                matches.append(match_result)

        # Remove duplicates (same product matched via different aliases)
        # Keep the highest confidence match for each product
        unique_matches = {}
        for match in matches:
            pid = match["product_id"]
            if pid not in unique_matches or match["confidence"] > unique_matches[pid]["confidence"]:
                unique_matches[pid] = match

        # Sort by confidence score (highest first)
        sorted_matches = sorted(unique_matches.values(), key=lambda x: x["confidence"], reverse=True)

        return sorted_matches

    async def find_product_enhanced(self, query_text: str) -> Optional[Dict[str, Any]]:
        """
        Find a product using enhanced matching (exact + fuzzy).
        Returns the best match or None if no good match found.

        Args:
            query_text: User's search query

        Returns:
            Product document or None
        """
        if not query_text:
            return None

        # First try exact match using existing query engine logic
        from query_engine import find_product
        exact_match = await find_product(self.db, query_text)
        if exact_match:
            # Add metadata indicating exact match
            exact_match["_match_type"] = "exact"
            exact_match["_confidence"] = 1.0
            return exact_match

        # If no exact match, try fuzzy matching
        fuzzy_matches = await self.find_product_fuzzy(query_text, threshold=0.5)

        if fuzzy_matches:
            best_match = fuzzy_matches[0]  # Already sorted by confidence
            # Fetch the full product document
            from bson import ObjectId
            try:
                product = await self.db.products.find_one(
                    {"_id": ObjectId(best_match["product_id"])}
                )
                if product:
                    product["_match_type"] = best_match["match_type"]
                    product["_confidence"] = best_match["confidence"]
                    product["_matched_term"] = best_match["matched_term"]
                    return product
            except Exception as e:
                logger.error(f"Error fetching product {best_match['product_id']}: {e}")

        return None

    async def suggest_corrections(self, query_text: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Suggest alternative product names when no good match is found.

        Args:
            query_text: Original query that didn't match well
            limit: Maximum number of suggestions to return

        Returns:
            List of suggested corrections with confidence scores
        """
        if not query_text:
            return []

        query_clean = query_text.strip().lower()
        product_index = await self._load_product_index()

        suggestions = []

        # Get similarity scores for all products
        for indexed_term, product_info in product_index.items():
            similarity = self._calculate_similarity(query_clean, indexed_term)
            phonetic = self._phonetic_match(query_clean, indexed_term)
            combined = (similarity * 0.7) + (phonetic * 0.3)

            # Only suggest if reasonably similar but not excellent match
            if 0.3 <= combined < 0.8:
                suggestions.append({
                    "suggestion": product_info["product_name"],
                    "matched_term": indexed_term,
                    "similarity": round(similarity, 3),
                    "phonetic": round(phonetic, 3),
                    "combined_score": round(combined, 3),
                    "match_type": product_info["match_type"]
                })

        # Sort by combined score and remove duplicates
        seen_products = set()
        unique_suggestions = []
        for sugg in sorted(suggestions, key=lambda x: x["combined_score"], reverse=True):
            product_name = sugg["suggestion"]
            if product_name not in seen_products:
                seen_products.add(product_name)
                unique_suggestions.append(sugg)
                if len(unique_suggestions) >= limit:
                    break

        return unique_suggestions


# Global matcher instance (will be initialized with database connection)
_product_matcher = None


def get_product_matcher(db: AsyncIOMotorDatabase) -> ProductMatcher:
    """
    Get or create the global product matcher instance.

    Args:
        db: MongoDB database connection

    Returns:
        ProductMatcher instance
    """
    global _product_matcher
    if _product_matcher is None or _product_matcher.db is not db:
        _product_matcher = ProductMatcher(db)
    return _product_matcher


# Convenience functions for external use
async def find_product_fuzzy(db: AsyncIOMotorDatabase, query_text: str, threshold: float = 0.6) -> List[Dict[str, Any]]:
    """
    Find products using fuzzy matching.

    Args:
        db: MongoDB database connection
        query_text: User's search query
        threshold: Minimum similarity score (0-1)

    Returns:
        List of matched products sorted by confidence
    """
    matcher = get_product_matcher(db)
    return await matcher.find_product_fuzzy(query_text, threshold)


async def find_product_enhanced(db: AsyncIOMotorDatabase, query_text: str) -> Optional[Dict[str, Any]]:
    """
    Find a product using enhanced matching (exact + fuzzy + aliases).

    Args:
        db: MongoDB database connection
        query_text: User's search query

    Returns:
        Product document or None
    """
    matcher = get_product_matcher(db)
    return await matcher.find_product_enhanced(query_text)


async def suggest_product_corrections(db: AsyncIOMotorDatabase, query_text: str, limit: int = 5) -> List[Dict[str, Any]]:
    """
    Suggest alternative product names for a poorly matching query.

    Args:
        db: MongoDB database connection
        query_text: Original query
        limit: Maximum suggestions to return

    Returns:
        List of suggested corrections
    """
    matcher = get_product_matcher(db)
    return await matcher.suggest_corrections(query_text, limit)


def demonstrate_matching():
    """Demonstrate the fuzzy matching capabilities."""
    print("Product Matcher Demonstration")
    print("=" * 40)
    print("This module provides:")
    print("1. Fuzzy matching for typos (e.g., 'unga' -> 'unga')")
    print("2. Phonetic matching (e.g., 'unnga' -> 'unga')")
    print("3. Alias support (Swahili/Sheng names)")
    print("4. Confidence scoring for matches")
    print("5. Suggestion system for poor matches")
    print("\nExample matches:")
    print("  Query: 'tomaes' -> Product: 'Tomatoes' (confidence: 0.8)")
    print("  Query: 'michunga' -> Product: 'Unga' (Swahili alias)")
    print("  Query: 'breadd' -> Product: 'Bread' (typo tolerance)")
    print("  Query: 'ziwa' -> Product: 'Milk' (Swahili: maziwa)")


if __name__ == "__main__":
    demonstrate_matching()