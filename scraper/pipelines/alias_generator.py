"""
Alias generator for canonical products.
Generates alternative names and variations for products.
"""
from typing import List, Set
from dataclasses import dataclass
from .models import CanonicalProduct
from typing import Optional

@dataclass
class AliasGeneratorConfig:
    """Configuration for alias generation."""
    include_brand_combinations: bool = True
    include_category_combinations: bool = True
    include_size_combinations: bool = True
    include_flavour_variants: bool = True
    include_common_synonyms: bool = True
    max_aliases: int = 20
    language_variants: dict = None  # e.g., {'en': [], 'sw': ['maziwa'] for milk}


class AliasGenerator:
    """
    Generates aliases for canonical products.

    Responsibilities:
    - Generate alternative names from canonical product
    - Create variations with/without brand, size, etc.
    - Add multilingual aliases (Swahili, Sheng, etc.)
    - Generate common misspellings/variants
    - Ensure uniqueness and reasonable limits
    """

    def __init__(self, config: Optional[AliasGeneratorConfig] = None):
        self.config = config or AliasGeneratorConfig()

        # Common product synonyms (can be extended)
        self.common_synonyms = {
            'milk': ['maziwa', 'ziwa', 'chai ya ngombe'],
            'bread': ['mkate', 'bread'],
            'sugar':['sukari'],
            'flour': ['unga'],
            'water': ['maji', 'water'],
            'salt': ['chumvi'],
            'oil': ['muta', 'oil'],
            'tea': ['chai'],
            'coffee': ['kahawa', 'coffee'],
            'soap': ['sabon'],
            'phone': ['simu'],
        }

        # Initialize language mappings
        if self.config.language_variants is None:
            self.config.language_variants = {}

    def generate_aliases(self, product: CanonicalProduct) -> List[str]:
        """
        Generate aliases for a canonical product.

        Args:
            product: Canonical product to generate aliases for

        Returns:
            List of unique alias strings
        """
        aliases = set()

        # Add the canonical name itself
        if product.canonical_name:
            aliases.add(product.canonical_name.lower().strip())

        # Generate component-based aliases
        aliases.update(self._generate_component_aliases(product))

        # Generate synonym-based aliases
        if self.config.include_common_synonyms:
            aliases.update(self._generate_synonym_aliases(product))

        # Generate language variants
        aliases.update(self._generate_language_variants(product))

        # Clean and limit results
        cleaned_aliases = self._clean_aliases(aliases)
        final_aliases = list(cleaned_aliases)[:self.config.max_aliases]

        return sorted(final_aliases)

    def _generate_component_aliases(self, product: CanonicalProduct) -> Set[str]:
        """Generate aliases from product components."""
        aliases = set()

        # Brand combinations
        if self.config.include_brand_combinations and product.brand:
            brand_lower = product.brand.lower()
            aliases.add(brand_lower)

            # Brand + category
            if product.category:
                aliases.add(f"{brand_lower} {product.category.lower()}")

            # Brand + size
            if product.size is not None and product.unit:
                size_str = str(int(product.size)) if product.size == int(product.size) else str(product.size)
                brand_size = f"{brand_lower} {size_str}{product.unit}"
                aliases.add(brand_size)

        # Category combinations
        if self.config.include_category_combinations:
            if product.category:
                cat_lower = product.category.lower()
                aliases.add(cat_lower)

                # Category + size
                if product.size is not None and product.unit:
                    size_str = str(int(product.size)) if product.size == int(product.size) else str(product.size)
                    cat_size = f"{cat_lower} {size_str}{product.unit}"
                    aliases.add(cat_size)

                # Category + variant
                if product.variant:
                    aliases.add(f"{cat_lower} {product.variant.lower()}")

                # Category + flavour
                if product.flavour:
                    aliases.add(f"{cat_lower} {product.flavour.lower()}")

        # Size-based aliases
        if self.config.include_size_combinations and product.size is not None and product.unit:
            size_str = str(int(product.size)) if product.size == int(product.size) else str(product.size)
            size_unit = f"{size_str}{product.unit}"
            aliases.add(size_unit)

            # Size + category
            if product.category:
                aliases.add(f"{size_unit} {product.category.lower()}")

        return aliases

    def _generate_synonym_aliases(self, product: CanonicalProduct) -> Set[str]:
        """Generate aliases using synonym dictionaries."""
        aliases = set()

        # Check category synonyms
        if product.category:
            cat_lower = product.category.lower()
            if cat_lower in self.common_synonyms:
                for synonym in self.common_synonyms[cat_lower]:
                    aliases.add(synonym)
                    # Also create combinations with synonyms
                    if product.brand:
                        aliases.add(f"{product.brand.lower()} {synonym}")
                    if product.size is not None and product.unit:
                        size_str = str(int(product.size)) if product.size == int(product.size) else str(product.size)
                        aliases.add(f"{synonym} {size_str}{product.unit}")

        # Check brand synonyms (less common but possible)
        if product.brand:
            brand_lower = product.brand.lower()
            # Could add brand synonyms here if needed

        return aliases

    def _generate_language_variants(self, product: CanonicalProduct) -> Set[str]:
        """Generate language-specific variants (Swahili, Sheng, etc.)."""
        aliases = set()

        # Generate for each language in config
        for lang, variants in self.config.language_variants.items():
            if not variants:
                continue

            # Add direct language variants
            for variant in variants:
                aliases.add(variant.lower())

                # Combine with other attributes
                if product.brand:
                    aliases.add(f"{product.brand.lower()} {variant}")
                if product.category:
                    aliases.add(f"{variant} {product.category.lower()}")

        return aliases

    def _clean_aliases(self, aliases: set) -> Set[str]:
        """Clean and filter aliases."""
        cleaned = set()

        for alias in aliases:
            if not alias:
                continue

            # Normalize whitespace
            alias = ' '.join(alias.split())

            # Skip if too short or too long
            if len(alias) < 2 or len(alias) > 100:
                continue

            # Skip if it's just numbers
            if alias.replace(' ', '').isdigit():
                continue

            cleaned.add(alias)

        return cleaned