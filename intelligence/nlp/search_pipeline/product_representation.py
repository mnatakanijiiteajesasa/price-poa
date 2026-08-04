"""
Product representation module for the search pipeline.
Creates structured embedding documents from product attributes instead of just product names.
"""

from typing import Dict, List, Any, Optional
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)

@dataclass
class ProductEmbeddingDocument:
    """
    Structured document for product embedding generation.
    Contains all relevant product information for creating rich embeddings.
    """
    # Core identifiers
    product_id: str
    product_name: str

    # Structured attributes
    brand: Optional[str] = None
    category: Optional[str] = None
    size: Optional[float] = None
    unit: Optional[str] = None

    # Text fields for embedding
    description: Optional[str] = None
    aliases: List[str] = None

    # Metadata
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.aliases is None:
            self.aliases = []
        if self.metadata is None:
            self.metadata = {}

    def to_embedding_text(self) -> str:
        """
        Convert the product to a text string suitable for embedding generation.
        This creates a rich, structured representation that captures all important
        aspects of the product.

        Returns:
            Text string for embedding generation
        """
        # Build structured text with clear section headers
        parts = []

        # Product name
        if self.product_name:
            parts.append(f"Product Name:\n{self.product_name}")

        # Brand
        if self.brand:
            parts.append(f"Brand:\n{self.brand}")

        # Category
        if self.category:
            parts.append(f"Category:\n{self.category}")

        # Size/Unit (Volume/Weight)
        if self.size is not None and self.unit:
            # Format size appropriately
            size_str = f"{self.size:g}"  # Removes trailing zeros
            # Handle unit formatting
            unit_str = self.unit
            if unit_str == 'L':
                unit_display = 'L'
            elif unit_str == 'ml':
                unit_display = 'ml'
            elif unit_str == 'g':
                unit_display = 'g'
            elif unit_str == 'kg':
                unit_display = 'kg'
            else:
                unit_display = self.unit

            parts.append(f"Volume:\n{size_str} {unit_display}")

        # Description (if available)
        if self.description:
            parts.append(f"Description:\n{self.description}")

        # Aliases
        if self.aliases:
            # Filter out empty aliases and join
            valid_aliases = [alias.strip() for alias in self.aliases if alias and alias.strip()]
            if valid_aliases:
                parts.append(f"Aliases:\n{', '.join(valid_aliases)}")

        # Join all parts with double newlines for clear separation
        return '\n\n'.join(parts)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            'product_id': self.product_id,
            'product_name': self.product_name,
            'brand': self.brand,
            'category': self.category,
            'size': self.size,
            'unit': self.unit,
            'description': self.description,
            'aliases': self.aliases,
            'metadata': self.metadata,
            'embedding_text': self.to_embedding_text()
        }

class ProductRepresentationBuilder:
    """
    Builds structured product representation documents for embedding generation.
    """

    def __init__(self):
        """Initialize the product representation builder."""
        pass

    def build_from_product_dict(self, product_data: Dict[str, Any]) -> ProductEmbeddingDocument:
        """
        Build a ProductEmbeddingDocument from a product dictionary (typically from MongoDB).

        Args:
            product_data: Product document from MongoDB

        Returns:
            ProductEmbeddingDocument
        """
        # Extract core fields
        product_id = str(product_data.get('_id', ''))
        product_name = product_data.get('name', '').strip()

        # Extract structured attributes
        brand = product_data.get('brand')
        if brand:
            brand = brand.strip() if brand else None

        category = product_data.get('category')
        if category:
            category = category.strip() if category else None

        # Extract size and variant information
        size, unit = self._extract_size_unit(product_data)

        # Build description from available fields
        description_parts = []

        # Add brand/category context if not already captured separately
        if brand and category:
            description_parts.append(f"{brand} {category}")

        # Add sizes_variants if available
        sizes_variants = product_data.get('sizes_variants', [])
        if sizes_variants:
            valid_sizes = [str(v).strip() for v in sizes_variants if v]
            if valid_sizes:
                description_parts.append(f"Available sizes: {', '.join(valid_sizes)}")

        # Join description parts
        description = '. '.join(filter(None, description_parts)) if description_parts else None

        # Collect aliases
        swahili_aliases = product_data.get('swahili_aliases', [])
        sheng_aliases = product_data.get('sheng_aliases', [])
        all_aliases = []

        if swahili_aliases:
            all_aliases.extend([str(alias).strip() for alias in swahili_aliases if alias])
        if sheng_aliases:
            all_aliases.extend([str(alias).strip() for alias in sheng_aliases if alias])

        # Build metadata
        metadata = {
            'indexed_at': product_data.get('updated_at') or product_data.get('created_at'),
            'source_collection': 'products',
            'has_swahili_aliases': len(swahili_aliases) > 0,
            'has_sheng_aliases': len(sheng_aliases) > 0,
            'has_sizes_variants': len(sizes_variants) > 0
        }

        # Add any additional fields that might be useful
        for field in ['source', 'verified_at']:
            if field in product_data:
                metadata[field] = product_data[field]

        return ProductEmbeddingDocument(
            product_id=product_id,
            product_name=product_name,
            brand=brand,
            category=category,
            size=size,
            unit=unit,
            description=description,
            aliases=all_aliases,
            metadata=metadata
        )

    def _extract_size_unit(self, product_data: Dict[str, Any]) -> tuple[Optional[float], Optional[str]]:
        """
        Extract size and unit from product data.

        Looks for size information in:
        1. sizes_variants array
        2. Product name (parsing)
        3. Other fields

        Returns:
            Tuple of (size: float, unit: str)
        """
        # Try to extract from sizes_variants first
        sizes_variants = product_data.get('sizes_variants', [])
        if sizes_variants:
            # Take the first variant and try to parse it
            first_variant = str(sizes_variants[0]).strip()
            size, unit = self._parse_size_unit_string(first_variant)
            if size is not None and unit is not None:
                return size, unit

        # Try to extract from product name
        product_name = product_data.get('name', '')
        if product_name:
            size, unit = self._parse_size_unit_string(product_name)
            if size is not None and unit is not None:
                return size, unit

        # Try to extract from brand or category fields (less common but possible)
        for field in ['brand', 'category']:
            field_value = product_data.get(field, '')
            if field_value:
                size, unit = self._parse_size_unit_string(str(field_value))
                if size is not None and unit is not None:
                    return size, unit

        # Return None if not found
        return None, None

    def _parse_size_unit_string(self, text: str) -> tuple[Optional[float], Optional[str]]:
        """
        Parse a size and unit from a string.

        Examples:
        "500ml" -> (500.0, "ml")
        "1 L" -> (1.0, "L")
        "2kg" -> (2.0, "kg")
        "1.5 Litre" -> (1.5, "L")
        "half kg" -> (0.5, "kg")

        Args:
            text: Input text to parse

        Returns:
            Tuple of (size: float, unit: str) or (None, None) if not found
        """
        if not text or not isinstance(text, str):
            return None, None

        text = text.strip()

        # Patterns for size + unit
        patterns = [
            # Standard format: number + space + unit
            (r'(\d+(?:\.\d+)?)\s*(kg|kgs?|kilogram|kilograms|g|grams?|gram|ml|milliliters?|millilitres?l|ltr|litre|liter|litres|liters|oz|ounces?|lb|lbs?|pound|pounds)\r?\n?', 'standard'),
            # Compact format: number + unit (no space)
            (r'(\d+(?:\.\d+)?)(kg|kgs?|kilogram|kilograms|g|grams?|gram|ml|milliliters?|millilitres?l|ltr|litre|liter|litres|liters|oz|ounces?|lb|lbs?|pound|pounds)\r?\n?', 'compact'),
            # Fraction format: half/quarter + unit
            (r'(half|quarter)\s+(kg|kgs?|kilogram|kilograms|g|grams?|gram|ml|milliliters?|millilitres?l|ltr|litre|liter|litres|liters|oz|ounces?|lb|lbs?|pound|pounds)\r?\n?', 'fraction'),
        ]

        for pattern, pattern_type in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    if pattern_type == 'standard':
                        size_str = match.group(1)
                        unit_str = match.group(2)
                    elif pattern_type == 'compact':
                        size_str = match.group(1)
                        unit_str = match.group(2)
                    elif pattern_type == 'fraction':
                        fraction_word = match.group(1).lower()
                        unit_str = match.group(2)
                        # Convert fraction to number
                        fraction_map = {'half': 0.5, 'quarter': 0.25}
                        if fraction_word in fraction_map:
                            size_str = str(fraction_map[fraction_word])
                        else:
                            continue  # Skip if not a recognized fraction
                    else:
                        continue

                    # Convert size to float
                    size = float(size_str)

                    # Normalize unit
                    unit = self._normalize_unit(unit_str)

                    return size, unit

                except (ValueError, IndexError):
                    continue  # Try next pattern

        return None, None

    def _normalize_unit(self, unit: str) -> str:
        """
        Normalize unit to standard form.

        Args:
            unit: Unit string to normalize

        Returns:
            Normalized unit string
        """
        unit_lower = unit.lower().strip()

        unit_mapping = {
            # Mass/Weight
            'kg': 'kg',
            'kgs': 'kg',
            'kilogram': 'kg',
            'kilograms': 'kg',
            'g': 'g',
            'gram': 'g',
            'grams': 'g',

            # Volume
            'ml': 'ml',
            'milliliter': 'ml',
            'milliliters': 'ml',
            'millilitre': 'ml',
            'millilitres': 'ml',
            'ltr': 'L',
            'litre': 'L',
            'liter': 'L',
            'litres': 'L',
            'liters': 'L',

            # Other units
            'oz': 'oz',
            'ounce': 'oz',
            'ounces': 'oz',
            'lb': 'lb',
            'pound': 'lb',
            'pounds': 'lb',
        }

        return unit_mapping.get(unit_lower, unit_lower.upper() if len(unit_lower) <= 2 else unit_lower)

# Convenience functions
def build_product_embedding_document(product_data: Dict[str, Any]) -> ProductEmbeddingDocument:
    """
    Convenience function to build a product embedding document.

    Args:
        product_data: Product document from MongoDB

    Returns:
        ProductEmbeddingDocument
    """
    builder = ProductRepresentationBuilder()
    return builder.build_from_product_dict(product_data)

def product_to_embedding_text(product_data: Dict[str, Any]) -> str:
    """
    Convenience function to convert product data directly to embedding text.

    Args:
        product_data: Product document from MongoDB

    Returns:
        Text string for embedding generation
    """
    doc = build_product_embedding_document(product_data)
    return doc.to_embedding_text()