"""
Natural Language Processing Package for Product Matching
"""

from .product_matcher import (
    ProductMatcher,
    get_product_matcher,
    find_product_fuzzy,
    find_product_enhanced,
    suggest_product_corrections
)

__all__ = [
    'ProductMatcher',
    'get_product_matcher',
    'find_product_fuzzy',
    'find_product_enhanced',
    'suggest_product_corrections'
]