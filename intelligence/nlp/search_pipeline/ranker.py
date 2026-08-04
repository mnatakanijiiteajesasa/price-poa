"""
Business ranker module for the search pipeline.
Implements hybrid scoring combining vector similarity, fuzzy matching, and business rules.
"""

from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
import logging
import math

from .config import get_ranker_config

logger = logging.getLogger(__name__)

@dataclass
class RankingScore:
    """Individual score components for a product."""
    vector_score: float = 0.0
    fuzzy_score: float = 0.0
    brand_score: float = 0.0
    category_score: float = 0.0
    quantity_score: float = 0.0
    alias_score: float = 0.0
    final_score: float = 0.0

    def to_dict(self) -> Dict[str, float]:
        """Convert to dictionary."""
        return {
            "vector_score": self.vector_score,
            "fuzzy_score": self fuzzy_score,
            "brand_score": self.brand_score,
            "category_score": self.category_score,
            "quantity_score": self.quantity_score,
            "alias_score": self.alias_score,
            "final_score": self.final_score
        }

@dataclass
class RankedResult:
    """A search result with ranking scores."""
    product_id: str
    product_name: str
    scores: RankingScore
    payload: Dict[str, Any] = field(default_factory=dict)
    rank: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "product_id": self.product_id,
            "product_name": self.product_name,
            "scores": self.scores.to_dict(),
            "payload": self.payload,
            "rank": self.rank
        }

class BusinessRanker:
    """
    Implements business rule ranking for search results.
    Combines vector similarity, fuzzy matching, and attribute matching scores.
    """

    def __init__(self):
        """Initialize the business ranker."""
        self.config = get_ranker_config()
        self.weights = self.config.get('weights', {
            'vector': 0.45,
            'fuzzy': 0.25,
            'brand': 0.15,
            'category': 0.10,
            'quantity': 0.05,
            'alias': 0.05
        })

        # Validate weights sum to 1.0 (approximately)
        total_weight = sum(self.weights.values())
        if not math.isclose(total_weight, 1.0, rel_tol=1e-9):
            logger.warning(f"Weights sum to {total_weight}, normalizing to 1.0")
            # Normalize weights
            for key in self.weights:
                self.weights[key] /= total_weight

        logger.info(f"Business ranker initialized with weights: {self.weights}")

    def rank_results(
        self,
        vector_results: List[Dict[str, Any]],
        fuzzy_results: List[Dict[str, Any]],
        parsed_query: Optional[Any] = None
    ) -> List[RankedResult]:
        """
        Rank search results using hybrid scoring.

        Args:
            vector_results: Results from vector search
            fuzzy_results: Results from fuzzy matching
            parsed_query: Parsed query object with extracted attributes

        Returns:
            List of ranked results sorted by final score
        """
        # Build a map of product ID to result data
        results_map: dict[str, dict] = {}

        # Process vector results
        for result in vector_results:
            product_id = result.get("product_id")
            if not product_id:
                continue

            if product_id not in results_map:
                results_map[product_id] = {
                    "product_id": product_id,
                    "product_name": "",
                    "vector_score": 0.0,
                    "fuzzy_score": 0.0,
                    "brand_score": 0.0,
                    "category_score": 0.0,
                    "quantity_score": 0.0,
                    "alias_score": 0.0,
                    "payload": {}
                }

            # Update vector score (keep highest)
            vector_score = result.get("score", 0.0)
            results_map[product_id]["vector_score"] = max(
                results_map[product_id]["vector_score"],
                vector_score
            )

            # Merge payload data
            payload = result.get("payload", {})
            results_map[product_id]["payload"].update(payload)

            # Extract product name from payload if available
            if "product_name" in payload and not results_map[product_id]["product_name"]:
                results_map[product_id]["product_name"] = payload["product_name"]

        # Process fuzzy results
        for result in fuzzy_results:
            product_id = result.get("product_id")
            if not product_id:
                continue

            if product_id not in results_map:
                results_map[product_id] = {
                    "product_id": product_id,
                    "product_name": "",
                    "vector_score": 0.0,
                    "fuzzy_score": 0.0,
                    "brand_score": 0.0,
                    "category_score": 0.0,
                    "quantity_score": 0.0,
                    "alias_score": 0.0,
                    "payload": {}
                }

            # Update fuzzy score (keep highest)
            fuzzy_score = result.get("confidence", result.get("score", 0.0))
            results_map[product_id]["fuzzy_score"] = max(
                results_map[product_id]["fuzzy_score"],
                fuzzy_score
            )

            # Merge payload data
            payload = {
                "product_name": result.get("product_name", ""),
                "match_type": result.get("match_type", ""),
                "matched_term": result.get("matched_term", "")
            }
            results_map[product_id]["payload"].update(payload)

            # Extract product name if not already set
            if "product_name" in payload and not results_map[product_id]["product_name"]:
                results_map[product_id]["product_name"] = payload["product_name"]

        # Calculate business rule scores for each result
        ranked_results: list[RankedResult] = []
        for product_id, data in results_map.items():
            # Calculate individual score components
            scores = RankingScore(
                vector_score=self._normalize_score(data["vector_score"]),
                fuzzy_score=self._normalize_score(data["fuzzy_score"]),
                brand_score=self._calculate_brand_score(data, parsed_query),
                category_score=self._calculate_category_score(data, parsed_query),
                quantity_score=self._calculate_quantity_score(data, parsed_query),
                alias_score=self._calculate_alias_score(data, parsed_query)
            )

            # Calculate final weighted score
            scores.final_score = (
                scores.vector_score * self.weights['vector'] +
                scores.fuzzy_score * self.weights['fuzzy'] +
                scores.brand_score * self.weights['brand'] +
                scores.category_score * self.weights['category'] +
                scores.quantity_score * self.weights['quantity'] +
                scores.alias_score * self.weights['alias']
            )

            # Create ranked result
            ranked_result = RankedResult(
                product_id=product_id,
                product_name=data["product_name"] or f"Product {product_id}",
                scores=scores,
                payload=data["payload"]
            )

            ranked_results.append(ranked_result)

        # Sort by final score (descending)
        ranked_results.sort(key=lambda x: x.scores.final_score, reverse=True)

        # Assign ranks
        for i, result in enumerate(ranked_results):
            result.rank = i + 1

        return ranked_results

    def _normalize_score(self, score: float) -> float:
        """
        """
        return max(0, min(1, score))

    def _calculate_brand_score(self, data: dict, parsed_query: Optional[Any]) -> float:
        if not parsed_query:
            return 0.0

        query_brand = getattr(parsed_query, 'brand', None)
        if not query_brand:
            return 0.0

        product_brand = data.get('payload', {}).get('brand', '')
        if not product_brand:
            return 0.0

        # Exact match gets full score
        if query_brand.lower() == product_brand.lower():
            return 1.0

        # Partial match gets partial score
        if query_brand.lower() in product_brand.lower() or product_brand.lower() in query_brand.lower():
            return 0.5

        return 0.0

    def _calculate_category_score(self, data: dict, parsed_query: Optional[Any]) -> float:
        if not parsed_query:
            return 0.0

        query_category = getattr(parsed_query, 'category', None)
        if not query_category:
            return 0.0

        product_category = data.get('payload', {}).get('category', '')
        if not product_category:
            return 0.0

        # Exact match gets full score
        if query_category.lower() == product_category.lower():
            return 1.0

        # Partial match gets partial score
        if query_category.lower() in product_category.lower() or product_category.lower() in query_category.lower():
            return 0.5

        return 0.0

    def _calculate_quantity_score(self, data: dict, parsed_query: Optional[Any]) -> float:
        if not parsed_query:
            return 0.0

        query_size = getattr(parsed_query, 'size', None)
        query_unit = getattr(parsed_query, 'unit', None)
        if query_size is None or not query_unit:
            return 0.0

        product_size = data.get('payload', {}).get('size')
        product_unit = data.get('payload', {}).get('unit')

        if product_size is None or not product_unit:
            return 0.0

        # Convert units for comparison if needed
        try:
            # Normalize units to base units for comparison
            q_size_norm = self._normalize_to_base_units(float(query_size), str(query_unit))
            p_size_norm = self._normalize_to_base_units(float(product_size), str(product_unit))

            if q_size_norm is None or p_size_norm is None:
                return 0.0

            # Exact match
            if math.isclose(q_size_norm, p_size_norm, rel_tol=1e-9):
                return 1.0

            # Close match (within 10%)
            diff_ratio = abs(q_size_norm - p_size_norm) / max(q_size_norm, p_size_norm)
            if diff_ratio <= 0.1:  # Within 10%
                return 0.5

            return 0.0
        except (ValueError, TypeError):
            return 0.0

    def _normalize_to_base_units(self, value: float, unit: str) -> Optional[float]:
        """Convert value to base units for comparison."""
        unit_lower = unit.lower().strip()

        # Weight conversions (to grams)
        if unit_lower in ['kg', 'kgs', 'kilogram', 'kilograms']:
            return value * 1000
        elif unit_lower in ['g', 'gram', 'grams']:
            return value
        elif unit_lower in ['mg', 'milligram', 'milligrams']:
            return value / 1000

        # Volume conversions (to milliliters)
        elif unit_lower in ['ml', 'milliliter', 'milliliters', 'millilitre', 'millilitres']:
            return value
        elif unit_lower in ['ltr', 'litre', 'liter', 'litres', 'liters']:
            return value * 1000

        # Other units (no conversion)
        else:
            return value  # Assume already in base unit or incomparable

    def _calculate_alias_score(self, data: dict, parsed_query: Optional[Any]) -> float:
        if not parsed_query:
            return 0.0

        # Get search terms from parsed query
        search_terms = []
        if hasattr(parsed_query, 'keywords') and parsed_query.keywords:
            search_terms.extend(parsed_query.keywords)
        if hasattr(parsed_query, 'brand') and parsed_query.brand:
            search_terms.append(parsed_query.brand)
        if hasattr(parsed_query, 'category') and parsed_query.category:
            search_terms.append(parsed_query.category)

        if not search_terms:
            return 0.0

        # Get product aliases
        product_aliases = data.get('payload', {}).get('aliases', [])
        if not product_aliases:
            return 0.0

        # Check if any search term matches any alias (case-insensitive)
        search_terms_lower = [term.lower().strip() for term in search_terms if term]
        aliases_lower = [alias.lower().strip() for alias in product_aliases if alias]

        for term in search_terms_lower:
            if any(term in alias or alias in term for alias in aliases_lower):
                return 1.0  # Found match in aliases

        return 0.0

def rank_search_results(
    vector_results: List[Dict[str, Any]],
    fuzzy_results: List[Dict[str, Any]],
    parsed_query: Optional[Any] = None
) -> List[RankedResult]:
    """
    Convenience function to rank search results.

    Args:
        vector_results: Results from vector search
        fuzzy_results: Results from fuzzy matching
        parsed_query: Parsed query object with extracted attributes

    Returns:
        List of ranked results sorted by final score
    """
    ranker = BusinessRanker()
    return ranker.rank_results(vector_results, fuzzy_results, parsed_query)