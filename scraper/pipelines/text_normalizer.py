"""
Text normalization utilities for product data.
Handles text cleaning, normalization, and standardization.
"""
import re
import unicodedata
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field


@dataclass
class NormalizationRules:
    """Configuration for text normalization rules."""
    # Synonym dictionaries
    brand_synonyms: Dict[str, str] = field(default_factory=dict)
    category_synonyms: Dict[str, str] = field(default_factory=dict)
    unit_synonyms: Dict[str, str] = field(default_factory=dict)

    # Stopwords to remove (context-dependent)
    stopwords: Set[str] = field(default_factory=set)

    # Whether to apply various transformations
    lowercase: bool = True
    remove_punctuation: bool = True
    normalize_whitespace: bool = True
    normalize_unicode: bool = True
    expand_synonyms: bool = True
    remove_stopwords: bool = False  # Usually False for product names


class TextNormalizer:
    """
    Handles text normalization for product data.

    Responsibilities:
    - lowercase
    - punctuation removal
    - whitespace normalization
    - unicode normalization
    - quantity normalization
    - unit normalization
    - synonym expansion
    - stopword removal (where appropriate)
    """

    def __init__(self, rules: Optional[NormalizationRules] = None):
        self.rules = rules or NormalizationRules()

        # Initialize default synonyms if not provided
        if not self.rules.unit_synonyms:
            self.rules.unit_synonyms = {
                # Weight/mass
                'kg': 'kg', 'kgs': 'kg', 'kilogram': 'kg', 'kilograms': 'kg',
                'g': 'g', 'gram': 'g', 'grams': 'g', 'mg': 'mg', 'milligram': 'mg', 'milligrams': 'mg',

                # Volume
                'ml': 'ml', 'milliliter': 'ml', 'milliliters': 'ml', 'millilitre': 'ml', 'millilitres': 'ml',
                'l': 'l', 'ltr': 'l', 'litre': 'l', 'liters': 'l', 'litres': 'l',

                # Count
                'pcs': 'pcs', 'pc': 'pcs', 'piece': 'pcs', 'pieces': 'pcs', 'pack': 'pcs', 'packs': 'pcs'
            }

        if not self.rules.brand_synonyms:
            self.rules.brand_synonyms = {
                # Common variations/shorthands
                'broadways': 'broadways',
                'broadway': 'broadways',
            }

    def normalize_text(self, text: str) -> str:
        """
        General text normalization.

        Args:
            text: Raw text to normalize

        Returns:
            Normalized text
        """
        if not text:
            return ""

        result = text

        # Unicode normalization (NFKC for compatibility decomposition)
        if self.rules.normalize_unicode:
            result = unicodedata.normalize('NFKC', result)

        # Lowercase
        if self.rules.lowercase:
            result = result.lower()

        # Remove punctuation (keep letters, numbers, spaces)
        if self.rules.remove_punctuation:
            result = re.sub(r'[^\w\s]', '', result)

        # Normalize whitespace
        if self.rules.normalize_whitespace:
            result = re.sub(r'\s+', ' ', result).strip()

        # Expand synonyms
        if self.rules.expand_synonyms:
            result = self._expand_synonyms(result, self.rules.brand_synonyms)
            result = self._expand_synonyms(result, self.rules.category_synonyms)
            result = self._expand_synonyms(result, self.rules.unit_synonyms)

        # Remove stopwords (careful with product names - usually don't want this)
        if self.rules.remove_stopwords and self.rules.stopwords:
            words = result.split()
            filtered_words = [w for w in words if w.lower() not in self.rules.stopwords]
            result = ' '.join(filtered_words)

        return result

    def normalize_query(self, query: str) -> str:
        """
        Normalize a search query.
        Typically more aggressive than product normalization.
        """
        # For queries, we might want to remove more noise
        original_remove_stopwords = self.rules.remove_stopwords
        self.rules.remove_stopwords = True  # More aggressive for queries

        result = self.normalize_text(query)

        self.rules.remove_stopwords = original_remove_stopwords
        return result

    def normalize_product(self, product_text: str) -> str:
        """
        Normalize product text for matching/canonicalization.
        Less aggressive than query normalization.
        """
        # For product names, we usually want to keep descriptive words
        original_remove_stopwords = self.rules.remove_stopwords
        self.rules.remove_stopwords = False  # Keep descriptive words for products

        result = self.normalize_text(product_text)

        self.rules.remove_stopwords = original_remove_stopwords
        return result

    def _expand_synonyms(self, text: str, synonyms: dict) -> str:
        """Replace synonyms with their canonical forms."""
        if not synonyms:
            return text

        # Sort by length descending to replace longer matches first
        sorted_synonyms = sorted(synonyms.items(), key=lambda x: len(x[0]), reverse=True)

        result = text
        for variant, canonical in sorted_synonyms:
            # Use word boundaries to avoid partial matches
            pattern = r'\b' + re.escape(variant) + r'\b'
            result = re.sub(pattern, canonical, result, flags=re.IGNORECASE)

        return result

    def normalize_unit(self, unit: str) -> str:
        """
        Normalize unit to canonical form.

        Args:
            unit: Raw unit string

        Returns:
            Normalized unit
        """
        if not unit:
            return unit

        unit_lower = unit.lower().strip()
        return self.rules.unit_synonyms.get(unit_lower, unit_lower)
