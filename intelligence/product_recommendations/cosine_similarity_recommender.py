"""
Product recommendation system using cosine similarity on product co-occurrence.
Recommends products that are frequently bought or viewed together.
"""
import numpy as np
import logging
from typing import List, Dict, Any, Tuple, Optional, Dict as TDict
from collections import defaultdict
import asyncio
from motor.motor_asyncio import AsyncIOMotorDatabase
import json
import os
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class ProductRecommender:
    """
    Product recommendation system based on co-occurrence in user queries.
    Uses cosine similarity to find similar products and suggest alternatives.
    """

    def __init__(self, min_cooccurrence: int = 3):
        """
        Initialize the product recommender.

        Args:
            min_cooccurrence: Minimum number of times two products must co-occur
                            to be considered for similarity calculation
        """
        self.min_cooccurrence = min_cooccurrence
        self.product_vectors = {}  # product_id -> feature vector
        self.product_index = {}    # product_id -> index in matrix
        self.index_product = {}    # index -> product_id
        self.similarity_matrix = None  # Cosine similarity matrix
        self.is_trained = False
        self.last_updated = None

    def _build_cooccurrence_matrix(self, query_logs: List[Dict[str, Any]]) -> Tuple[np.ndarray, Dict[str, int], Dict[int, str]]:
        """
        Build a co-occurrence matrix from query logs.

        Args:
            query_logs: List of query log entries with 'products' field containing product IDs

        Returns:
            Tuple of (cooccurrence_matrix, product_to_index, index_to_product)
        """
        # Count product frequencies and co-occurrences
        product_counts = defaultdict(int)
        cooccurrence_counts = defaultdict(lambda: defaultdict(int))

        for log_entry in query_logs:
            products = log_entry.get('products', [])
            if not isinstance(products, list):
                continue

            # Count individual products
            for product_id in products:
                product_counts[product_id] += 1

            # Count co-occurrences (product pairs in same query)
            for i, product_id_1 in enumerate(products):
                for product_id_2 in products[i+1:]:
                    if product_id_1 != product_id_2:
                        cooccurrence_counts[product_id_1][product_id_2] += 1
                        cooccurrence_counts[product_id_2][product_id_1] += 1

        # Filter products by minimum occurrence
        frequent_products = {
            pid: count for pid, count in product_counts.items()
            if count >= self.min_cooccurrence
        }

        if len(frequent_products) < 2:
            return np.array([]), {}, {}

        # Create mapping
        product_list = sorted(frequent_products.keys())
        product_to_index = {pid: idx for idx, pid in enumerate(product_list)}
        index_to_product = {idx: pid for pid, idx in product_to_index.items()}

        # Initialize matrix
        n_products = len(product_list)
        cooccurrence_matrix = np.zeros((n_products, n_products), dtype=np.float64)

        # Fill matrix
        for pid_1, related_counts in cooccurrence_counts.items():
            if pid_1 not in product_to_index:
                continue
            idx_1 = product_to_index[pid_1]
            for pid_2, count in related_counts.items():
                if pid_2 not in product_to_index:
                    continue
                idx_2 = product_to_index[pid_2]
                cooccurrence_matrix[idx_1, idx_2] = count

        return cooccurrence_matrix, product_to_index, index_to_product

    def _compute_similarity(self, cooccurrence_matrix: np.ndarray) -> np.ndarray:
        """
        Compute cosine similarity from co-occurrence matrix.

        Args:
            cooccurrence_matrix: Matrix of co-occurrence counts

        Returns:
            Cosine similarity matrix
        """
        if cooccurrence_matrix.size == 0:
            return np.array([])

        # Normalize rows to unit vectors for cosine similarity
        norms = np.linalg.norm(cooccurrence_matrix, axis=1, keepdims=True)
        # Avoid division by zero
        norms = np.where(norms == 0, 1, norms)
        normalized = cooccurrence_matrix / norms

        # Compute cosine similarity
        similarity_matrix = np.dot(normalized, normalized.T)

        # Ensure diagonal is 1 (perfect self-similarity)
        np.fill_diagonal(similarity_matrix, 1.0)

        # Clip to valid range [-1, 1] due to potential floating point errors
        similarity_matrix = np.clip(similarity_matrix, -1.0, 1.0)

        return similarity_matrix

    async def train(self, db: AsyncIOMotorDatabase, lookback_days: int = 7) -> bool:
        """
        Train the recommendation model on recent query logs.

        Args:
            db: MongoDB database connection
            lookback_days: Number of days of query logs to use for training

        Returns:
            True if training successful, False otherwise
        """
        try:
            logger.info(f"Training product recommendation model on last {lookback_days} days of query logs")

            # Get recent query logs
            cutoff_date = datetime.utcnow() - timedelta(days=lookback_days)

            query_logs_collection = db.query_logs
            cursor = query_logs_collection.find(
                {"timestamp": {"$gte": cutoff_date}},
                {"products": 1, "_id": 0}
            )

            query_logs = await cursor.to_list(length=None)

            if len(query_logs) < 10:
                logger.warning(f"Insufficient query logs for training: {len(query_logs)} entries")
                return False

            # Build co-occurrence matrix
            cooccurrence_matrix, product_to_index, index_to_product = self._build_cooccurrence_matrix(query_logs)

            if cooccurrence_matrix.size == 0:
                logger.warning("No sufficient co-occurrence data for training")
                return False

            # Compute similarity matrix
            self.similarity_matrix = self._compute_similarity(cooccurrence_matrix)
            self.product_index = product_to_index
            self.index_product = index_to_product
            self.is_trained = True
            self.last_updated = datetime.utcnow()

            logger.info(f"Product recommendation model trained on {len(product_to_index)} products")
            return True

        except Exception as e:
            logger.error(f"Error training product recommendation model: {e}")
            return False

    def get_similar_products(self, product_id: str, top_k: int = 5) -> List[Tuple[str, float]]:
        """
        Get similar products based on cosine similarity.

        Args:
            product_id: ID of the product to find similarities for
            top_k: Number of similar products to return

        Returns:
            List of tuples (similar_product_id, similarity_score) sorted by similarity
        """
        if not self.is_trained or product_id not in self.product_index:
            logger.warning(f"Cannot get similar products for {product_id}: model not trained or product not found")
            return []

        try:
            product_idx = self.product_index[product_id]
            similarities = self.similarity_matrix[product_idx]

            # Get top-k most similar products (excluding self)
            similar_indices = np.argsort(similarities)[::-1][1:top_k+1]

            similar_products = []
            for idx in similar_indices:
                similar_product_id = self.index_product[idx]
                similarity_score = float(similarities[idx])
                similar_products.append((similar_product_id, similarity_score))

            return similar_products

        except Exception as e:
            logger.error(f"Error getting similar products for {product_id}: {e}")
            return []

    def get_product_recommendations(self, query_products: List[str],
                                  exclude_products: List[str] = None,
                                  top_k: int = 5) -> List[Tuple[str, float, str]]:
        """
        Get product recommendations based on a query containing multiple products.

        Args:
            query_products: List of product IDs in the current query
            exclude_products: List of product IDs to exclude from recommendations
            top_k: Number of recommendations to return

        Returns:
            List of tuples (recommended_product_id, similarity_score, reason)
        """
        if not self.is_trained:
            return []

        if exclude_products is None:
            exclude_products = []

        # Score products based on similarity to all query products
        product_scores = defaultdict(float)
        product_reasons = defaultdict(list)

        for query_product in query_products:
            if query_product not in self.product_index:
                continue

            similar_products = self.get_similar_products(query_product, top_k=20)
            for similar_product, similarity in similar_products:
                if similar_product in query_products or similar_product in exclude_products:
                    continue

                product_scores[similar_product] += similarity
                product_reasons[similar_product].append(f"Users who viewed {query_product} also viewed this")

        # Normalize scores by number of query products that contributed
        for product_id in list(product_scores.keys()):
            # Count how many query products contributed to this score
            contributor_count = 0
            for query_product in query_products:
                if query_product in self.product_index:
                    similar_products = self.get_similar_products(query_product, top_k=100)
                    if any(sp[0] == product_id for sp in similar_products):
                        contributor_count += 1

            if contributor_count > 0:
                product_scores[product_id] /= contributor_count
            else:
                product_scores[product_id] = 0.0

        # Sort by score and return top-k
        ranked_products = sorted(product_scores.items(), key=lambda x: x[1], reverse=True)[:top_k]

        recommendations = []
        for product_id, score in ranked_products:
            # Create a reason string
            reasons = product_reasons[product_id]
            reason = "; ".join(reasons[:2])  # Limit to 2 reasons
            if not reason:
                reason = "Frequently bought together"
            recommendations.append((product_id, score, reason))

        return recommendations

    def get_cheaper_alternative(self, product_id: str, db: AsyncIOMotorDatabase,
                              max_price_ratio: float = 0.85) -> Optional[Tuple[str, float, float]]:
        """
        Find a cheaper alternative product that's similar to the given product.
        NOTE: This method is synchronous because it's called from non-async contexts.
        For full async price comparison, use get_cheaper_substitute_async instead.

        Args:
            product_id: ID of the product to find alternatives for
            db: MongoDB database connection
            max_price_ratio: Maximum price ratio (alternative_price / original_price) to consider

        Returns:
            Tuple of (alternative_product_id, similarity_score, price_savings_percent) or None
            Note: price_savings_percent is 0.0 in this synchronous version as price checking
                  requires async database operations
        """
        if not self.is_trained:
            return None

        try:
            # Get similar products
            similar_products = self.get_similar_products(product_id, top_k=10)
            if not similar_products:
                return None

            # For synchronous version, we return the most similar product
            # Price checking requires async DB operations which we can't do here
            best_alternative = similar_products[0]  # Most similar
            alt_product_id, similarity = best_alternative

            return (alt_product_id, similarity, 0.0)  # Placeholder for actual price comparison

        except Exception as e:
            logger.error(f"Error finding cheaper alternative for {product_id}: {e}")
            return None


# Global recommender instance
product_recommender = ProductRecommender()


async def get_product_recommendations_for_query(db: AsyncIOMotorDatabase,
                                              query_products: List[str],
                                              limit: int = 5) -> List[Dict[str, Any]]:
    """
    Get product recommendations for a user query.

    Args:
        db: MongoDB database connection
        query_products: List of product IDs mentioned in the query
        limit: Maximum number of recommendations to return

    Returns:
        List of recommendation dictionaries
    """
    global product_recommender

    # Ensure model is trained
    if not product_recommender.is_trained:
        await product_recommender.train(db)

    # Get recommendations
    recommendations = product_recommender.get_product_recommendations(
        query_products,
        top_k=limit
    )

    # Format results
    results = []
    for product_id, similarity, reason in recommendations:
        # Get product details
        try:
            # Try to handle both string and ObjectId formats
            query = {"_id": product_id}
            if not (isinstance(product_id, str) and len(product_id) == 24):
                try:
                    from bson import ObjectId
                    query["_id"] = ObjectId(product_id)
                except:
                    pass

            product_obj = await db.products.find_one(
                query,
                {"name": 1, "brand": 1, "category": 1}
            )

            if product_obj:
                results.append({
                    "product_id": str(product_obj["_id"]),
                    "product_name": product_obj.get("name", "Unknown Product"),
                    "brand": product_obj.get("brand", ""),
                    "category": product_obj.get("category", ""),
                    "similarity_score": similarity,
                    "reason": reason,
                    "recommendation_type": "also_viewed"
                })
        except Exception as e:
            logger.warning(f"Could not fetch product details for {product_id}: {e}")

    return results


async def get_cheaper_substitute(db: AsyncIOMotorDatabase,
                               product_id: str,
                               max_price_ratio: float = 0.85) -> Optional[Dict[str, Any]]:
    """
    Get a cheaper substitute for a product.

    Args:
        db: MongoDB database connection
        product_id: ID of the product to find substitute for
        max_price_ratio: Maximum price ratio for considering a "cheaper" substitute

    Returns:
        Dictionary with substitute information or None if not found
    """
    global product_recommender

    # Get alternative from recommender (synchronous version)
    alternative = product_recommender.get_cheaper_alternative(product_id, db, max_price_ratio)
    if not alternative:
        return None

    alt_product_id, similarity, _ = alternative

    try:
        from bson import ObjectId
        # Get product details for both products
        query = {"_id": alt_product_id}
        if not (isinstance(alt_product_id, str) and len(alt_product_id) == 24):
            try:
                query["_id"] = ObjectId(alt_product_id)
            except:
                pass

        alt_product = await db.products.find_one(
            query,
            {"name": 1, "brand": 1, "category": 1}
        )

        if not alt_product:
            return None

        # Get average prices for comparison
        cutoff_date = datetime.utcnow() - timedelta(days=7)

        # Original product price
        orig_price_cursor = db.prices.aggregate([
            {"$match": {
                "product_id": product_id if isinstance(product_id, str) and len(product_id) == 24
                            else str(ObjectId(product_id)) if isinstance(product_id, str) else product_id,
                "verified_at": {"$gte": cutoff_date}
            }},
            {"$group": {
                "_id": None,
                "avg_price": {"$avg": "$price_kes"},
                "sample_count": {"$sum": 1}
            }}
        ])
        orig_price_result = await orig_price_cursor.to_list(length=1)

        # Alternative product price
        alt_price_cursor = db.prices.aggregate([
            {"$match": {
                "product_id": alt_product_id if isinstance(alt_product_id, str) and len(alt_product_id) == 24
                            else str(ObjectId(alt_product_id)) if isinstance(alt_product_id, str) else alt_product_id,
                "verified_at": {"$gte": cutoff_date}
            }},
            {"$group": {
                "_id": None,
                "avg_price": {"$avg": "$price_kes"},
                "sample_count": {"$sum": 1}
            }}
        ])
        alt_price_result = await alt_price_cursor.to_list(length=1)

        if not orig_price_result or not alt_price_result:
            # Fallback if price data insufficient
            orig_price = 0
            alt_price = 0
        else:
            orig_price = orig_price_result[0]["avg_price"]
            alt_price = alt_price_result[0]["avg_price"]

        if orig_price <= 0:
            savings_percent = 0
        else:
            savings_percent = ((orig_price - alt_price) / orig_price) * 100

        return {
            "product_id": str(alt_product["_id"]),
            "product_name": alt_product.get("name", "Unknown Product"),
            "brand": alt_product.get("brand", ""),
            "category": alt_product.get("category", ""),
            "similarity_score": similarity,
            "original_price_kes": round(orig_price, 2),
            "alternative_price_kes": round(alt_price, 2),
            "savings_percent": round(savings_percent, 1),
            "recommendation_type": "cheaper_alternative"
        }

    except Exception as e:
        logger.error(f"Error getting cheaper substitute for {product_id}: {e}")
        return None