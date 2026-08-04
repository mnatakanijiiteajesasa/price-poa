"""
Canonical product builder.
Converts extracted attributes into canonical product representation.
"""
from typing import List, Optional
from dataclasses import dataclass, field
from .models import CanonicalProduct, ExtractedAttributes


@dataclass
class CanonicalizationRules:
    """Rules for building canonical products."""
    # Default units for categories
    default_units: dict = field(default_factory=lambda: {
        'milk': 'ml',
        'bread': 'loaf',
        'sugar': 'kg',
        'flour': 'kg',
        'rice': 'kg',
        'salt': 'kg',
        'oil': 'ml',
        'tea': 'g',
        'coffee': 'g',
        'soda': 'ml',
        'water': 'ml',
        'juice': 'ml',
        'beer': 'ml',
    })

    # Words to ignore when building canonical name
    stopwords: List[str] = field(default_factory=lambda: [
        'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
        'of', 'with', 'by', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
        'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
        'should', 'may', 'might', 'must', 'can'
    ])

    # Maximum length for canonical name
    max_name_length: int = 100


class CanonicalProductBuilder:
    """
    Builds canonical product representations from extracted attributes.

    Responsibilities:
    - Convert extracted attributes to canonical product
    - Generate canonical name from attributes
    - Set default units when missing
    - Build standardized representation
    """

    def __init__(self, rules: Optional[CanonicalizationRules] = None):
        self.rules = rules or CanonicalizationRules()

    def build_canonical_product(self, attributes: ExtractedAttributes) -> CanonicalProduct:
        """
        Build a canonical product from extracted attributes.

        Args:
            attributes: Extracted attributes from raw product data

        Returns:
            CanonicalProduct object
        """
        # Determine final values with fallbacks
        brand = attributes.brand or "unknown"
        category = attributes.category or "general"
        subcategory = attributes.subcategory or "general"

        # Set unit - use extracted, or default for category, or None
        unit = attributes.unit
        if not unit and category in self.rules.default_units:
            unit = self.rules.default_units[category]

        # Build canonical name
        canonical_name = self._build_canonical_name(attributes)

        # Generate aliases
        aliases = self._generate_aliases(attributes, canonical_name)

        # Build embedding text (will be enhanced by EmbeddingTextBuilder)
        embedding_text = self._build_basic_embedding_text(attributes, canonical_name)

        return CanonicalProduct(
            canonical_name=canonical_name,
            brand=brand,
            category=category,
            subcategory=subcategory,
            size=attributes.size,
            unit=unit,
            package_type=attributes.package_type,
            variant=attributes.variant,
            flavour=attributes.flavour,
            aliases=aliases,
            embedding_text=embedding_text
        )

    def _build_canonical_name(self, attributes: ExtractedAttributes) -> str:
        """
        Build a canonical product name from attributes.

        Examples:
        - Brand: Brookside, Category: Milk, Size: 500, Unit: ml -> "Brookside Milk 500ml"
        - Brand: Bread, Category: Bread -> "Bread"
        """
        parts = []

        # Add brand if not generic
        if attributes.brand and attributes.brand.lower() != "unknown":
            parts.append(attributes.brand)

        # Add category
        if attributes.category:
            parts.append(attributes.category)

        # Add subcategory if different from category
        if attributes.subcategory and attributes.subcategory != attributes.category:
            parts.append(attributes.subcategory)

        # Add size and unit if available
        if attributes.size is not None and attributes.unit:
            # Format size nicely (remove .0 if integer)
            size_str = str(int(attributes.size)) if attributes.size == int(attributes.size) else str(attributes.size)
            parts.append(f"{size_str}{attributes.unit}")

        # Add variant if meaningful
        if attributes.variant and attributes.variant.lower() not in ['unknown', '']:
            parts.append(attributes.variant)

        # Add flavour if meaningful
        if attributes.flavour and attributes.flavour.lower() not in ['unknown', '']:
            parts.append(attributes.flavour)

        # Join parts and clean up
        name = " ".join(parts)

        # Remove extra whitespace and truncate if needed
        name = re.sub(r'\s+', ' ', name).strip()
        if len(name) > self.rules.max_name_length:
            name = name[:self.rules.max_name_length].rstrip()

        # If we ended up with empty name, fall back to cleaned text
        if not name and attributes.cleaned_text:
            name = attributes.cleaned_text[:self.rules.max_name_length]

        return name or "Unknown Product"

    def _generate_aliases(self, attributes: ExtractedAttributes, canonical_name: str) -> List[str]:
        """
        Generate alias variations for the canonical product.

        Examples:
        - Canonical: "Brookside Milk 500ml"
        - Aliases: ["brookside milk", "milk", "500ml milk", "broadside dairy"]
        """
        aliases = set()

        # Always add the canonical name (lowercased)
        if canonical_name:
            aliases.add(canonical_name.lower())

        # Add brand + category combinations
        if attributes.brand and attributes.category:
            brand_cat = f"{attributes.brand} {attributes.category}".lower()
            aliases.add(brand_cat)

        # Add category alone
        if attributes.category:
            aliases.add(attributes.category.lower())

        # Add brand alone
        if attributes.brand and attributes.brand.lower() != "unknown":
            aliases.add(attributes.brand.lower())

        # Add size + unit combinations
        if attributes.size is not None and attributes.unit:
            size_str = str(int(attributes.size)) if attributes.size == int(attributes.size) else str(attributes.size)
            size_unit = f"{size_str}{attributes.unit}"
            aliases.add(size_unit)

            # Size + category
            if attributes.category:
                aliases.add(f"{size_unit} {attributes.category}".lower())

        # Add flavour/variant combinations
        if attributes.flavour:
            aliases.add(attributes.flavour.lower())
            if attributes.category:
                aliases.add(f"{attributes.flavour} {attributes.category}".lower())
            if attributes.brand:
                aliases.add(f"{attributes.brand} {attributes.flavour}".lower())

        if attributes.variant:
            aliases.add(attributes.variant.lower())
            if attributes.category:
                aliases.add(f"{attributes.variant} {attributes.category}".lower())

        # Clean up aliases
        cleaned_aliases = set()
        for alias in aliases:
            alias = alias.strip()
            if alias and len(alias) > 1:  # Avoid single characters
                # Remove extra whitespace
                alias = re.sub(r'\s+', ' ', alias)
                cleaned_aliases.add(alias)

        return sorted(list(cleaned_aliases))

    def _build_basic_embedding_text(self, attributes: ExtractedAttributes, canonical_name: str) -> str:
        """
        Build basic embedding text (will be enhanced by EmbeddingTextBuilder).

        Args:
            attributes: Extracted attributes
            canonical_name: Canonical product name

        Returns:
            Basic embedding text string
        """
        parts = []

        if canonical_name:
            parts.append(f"Product Name: {canonical_name}")

        if attributes.brand:
            parts.append(f"Brand: {attributes.brand}")

        if attributes.category:
            parts.append(f"Category: {attributes.category}")

        if attributes.subcategory and attributes.subcategory != attributes.category:
            parts.append(f"Subcategory: {attributes.subcategory}")

        if attributes.size is not None and attributes.unit:
            size_str = str(int(attributes.size)) if attributes.size == int(attributes.size) else str(attributes.size)
            parts.append(f"Size: {size_str} {attributes.unit}")

        if attributes.package_type:
            parts.append(f"Package: {attributes.package_type}")

        if attributes.variant:
            parts.append(f"Variant: {attributes.variant}")

        if attributes.flavour:
            parts.append(f"Flavour: {attributes.flavour}")

        return "\n".join(parts)