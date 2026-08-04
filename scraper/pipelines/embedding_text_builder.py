"""
Embedding text builder for product data.
Creates rich semantic text for embedding models.
"""
from typing import List, Optional
from dataclasses import dataclass, field
from .models import CanonicalProduct


@dataclass
class EmbeddingTextBuilderConfig:
    """Configuration for embedding text generation."""
    include_product_name: bool = True
    include_brand: bool = True
    include_category: bool = True
    include_subcategory: bool = True
    include_size_unit: bool = True
    include_package_type: bool = True
    include_variant: bool = True
    include_flavour: bool = True
    include_aliases: bool = True
    max_aliases: int = 5
    include_keywords: bool = True
    keyword_sources: List[str] = field(default_factory=lambda: ['category', 'brand', 'category'])
    language: str = 'en'  # For language-specific templates


class EmbeddingTextBuilder:
    """
    Builds rich semantic text for product embeddings.

    Responsibilities:
    - Create descriptive text combining product attributes
    - Format text for optimal embedding model performance
    - Include aliases and keywords for better semantic matching
    - Support multilingual templates
    - Generate consistent, structured output
    """

    def __init__(self, config: Optional[EmbeddingTextBuilderConfig] = None):
        self.config = config or EmbeddingTextBuilderConfig()

        # Language-specific templates
        self.templates = {
            'en': {
                'product_name': "Product Name: {value}",
                'brand': "Brand: {value}",
                'category': "Category: {value}",
                'subcategory': "Subcategory: {value}",
                'size_unit': "Size: {value}",
                'package_type': "Package Type: {value}",
                'variant': "Variant: {value}",
                'flavour': "Flavour: {value}",
                'aliases': "Aliases: {value}",
                'keywords': "Keywords: {value}"
            },
            'sw': {
                'product_name': "Jina la Bidhaa: {value}",
                'brand': "Jakara: {value}",
                'category': "Kategoria: {value}",
                'subcategory': "Kategoria kachache: {value}",
                'size_unit': "Ukubwa: {value}",
                'package_type': "Aina ya Paketi: {value}",
                'variant': "Mabadiliko: {value}",
                'flavour': "Mazaji: {value}",
                'aliases': "Majina Alternatibu: {value}",
                'keywords': "Maneno Muhimu: {value}"
            }
        }

    def build_embedding_text(self, product: CanonicalProduct) -> str:
        """
        Build embedding text for a canonical product.

        Args:
            product: Canonical product to build text for

        Returns:
            Formatted string suitable for embedding
        """
        parts = []

        # Add sections in a consistent order
        if self.config.include_product_name and product.canonical_name:
            parts.append(self._format_field('product_name', product.canonical_name))

        if self.config.include_brand and product.brand:
            parts.append(self._format_field('brand', product.brand))

        if self.config.include_category and product.category:
            parts.append(self._format_field('category', product.category))

        if self.config.include_subcategory and product.subcategory:
            parts.append(self._format_field('subcategory', product.subcategory))

        if self.config.include_size_unit and product.size is not None and product.unit:
            size_str = str(int(product.size)) if product.size == int(product.size) else str(product.size)
            size_value = f"{size_str} {product.unit}"
            parts.append(self._format_field('size_unit', size_value))

        if self.config.include_package_type and product.package_type:
            parts.append(self._format_field('package_type', product.package_type))

        if self.config.include_variant and product.variant:
            parts.append(self._format_field('variant', product.variant))

        if self.config.include_flavour and product.flavour:
            parts.append(self._format_field('flavour', product.flavour))

        if self.config.include_aliases and product.aliases:
            # Limit number of aliases to avoid overly long text
            aliases_to_show = product.aliases[:self.config.max_aliases]
            aliases_str = ", ".join(aliases_to_show)
            parts.append(self._format_field('aliases', aliases_str))

        if self.config.include_keywords:
            keywords = self._extract_keywords(product)
            if keywords:
                keywords_str = ", ".join(keywords)
                parts.append(self._format_field('keywords', keywords_str))

        return "\n".join(parts)

    def _format_field(self, field_key: str, value: str) -> str:
        """Format a field according to language template."""
        template = self.templates.get(self.config.language, self.templates['en']).get(
            field_key, "{value}")
        return template.format(value=value)

    def _extract_keywords(self, product: CanonicalProduct) -> List[str]:
        """Extract keywords from product attributes."""
        keywords = set()

        # Add category and subcategory as keywords
        if self.config.include_category and product.category:
            keywords.add(product.category.lower())
        if self.config.include_subcategory and product.subcategory:
            keywords.add(product.subcategory.lower())

        # Add brand as keyword
        if self.config.include_brand and product.brand:
            keywords.add(product.brand.lower())

        # Add descriptive words from variant/flavour
        if self.config.include_variant and product.variant:
            keywords.add(product.variant.lower())
        if self.config.include_flavour and product.flavour:
            keywords.add(product.flavour.lower())

        # Add individual words from aliases (limited)
        if self.config.include_aliases and product.aliases:
            for alias in product.aliases[:3]:  # Just first few aliases
                words = alias.lower().split()
                # Add meaningful words (longer than 2 chars)
                for word in words:
                    if len(word) > 2 and word.isalpha():
                        keywords.add(word)

        # Convert to list and sort for consistency
        return sorted(list(keywords))[:10]  # Limit to top 10 keywords