"""
Attribute extraction for product data.
Extracts structured attributes from raw product text.
"""
import re
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field
from .models import ExtractedAttributes


@dataclass
class ExtractionRules:
    """Configuration for attribute extraction."""
    # Known brands for detection
    known_brands: List[str] = field(default_factory=lambda: [
        "broadways", "bidco", "brookside", "naivas", "carrefour", "quickmart",
        "daisy", "kelloggs", "nestle", "pampers", "huggies", "unilever", "cadbury",
        "kapa", "soko", "jogoo", "pembe", "exe", "chapa mandashi", "ketepa", "kericho gold", "umoja"
        "mumias", "sony", "samsung", "lg", "nestle", "coca-cola", "pepsi", "daima", "always", "dola",
        "dove", "fair & lovely", "lifebuoy", "sunlight", "tide", "omo", "surf", "airwick", "persil", "ballantines",
        "colgate", "pepsodent", "sensodyne", "closeup", "aquafresh", "listerine", "garnier", "nivea", "pishori", "teepee", "trufoods", "cafenaivas"
        "vaseline", "johnson & johnson", "pampers", "huggies", "mamy poko", "himalaya", "herbal essences", "minute maid", "club", "fanta", "sprite", "pepsi", "coca-cola", "7up", "mirinda", "tropicana",
        "tropical", "nivea", "loreal", "maybelline", "revlon", "mac", "clinique", "estee lauder", "shiseido", "premier", "dove", "lux", "sunlight", "lifebuoy", "tide", "omo", "surf", "airwick", "persil",
        "candybury", "hershey's", "mars", "snickers", "twix", "kitkat", "bounty", "milky way", "m&m's", "cadbury dairy milk", ""
        "oreo", "lays", "pringles", "doritos", "cheetos", "fritos", "tostitos", "cheetos", "cheetos puffs", "cheetos crunchy", "cheetos flamin' hot", "cheetos cheesy",
        "cheetos jalapeno", "cheetos spicy", "cheetos sweet", "cheetos sour cream", "cheetos barbecue", "cheetos ranch", "cheetos buffalo", "cheetos honey mustard", "bic", "von", "pepsodent", "colgate", "sensodyne", "closeup", "aquafresh", "listerine", "garnier", "nivea", "pishori", "teepee", "trufoods", "cafenaivas",
        "cheetos garlic parmesan", "cheetos chili lime", "cheetos nacho cheese", "cheetos cheddar", "cheetos mozzarella", "cheetos pepper jack", "cheetos smoked gouda", "cheetos truffle", "cheetos white cheddar",
        "farmers choice", "LG", "Ex", "Mwea rice", "Kapa", "Soko", "Pembe", "Chapa Mandashi", "Ketepa", "Kericho Gold", "Delamere", "Arla", "Kenchic", "Tusker", "Chrome", "ramtons",
        "General Meakins", "Kenya Cane", "Eabl", "dairyland", "Kasuku", "Trust", "KCC", "Kiss", "Rough rider", "amtec", "samsung", "sony", "lg", "panasonic", "toshiba", "sharp", "philips", "beko", "haier", "whirlpool", "bosch", "electrolux", "miele", "smeg", "kenwood", "delonghi", "breville",
    ])

    # Common categories
    known_categories: List[str] = field(default_factory=lambda: [
        "milk", "bread", "sugar", "maize flour", "rice", "maize", "unga", "salt", "spirits", "wine", "beer", "cognac", "brandy", "whisky", "vodka",
        "soap", "detergent", "oil", "fat", "tea", "coffee", "soda", "water", "juice", "energy drinks", "woofer", "soundber", "TV", "fridge", "washing machine", "microwave", "oven", 
        "stove", "blender", "mixer", "toaster", "kettle", "iron", "vacuum cleaner", "dry cleaner", "air conditioner", "heater", "fan", "lamp", "light bulb", "candle", "torch", "battery", "charger", "power bank", "adapter", "cable", "headphones", "earphones", "speaker",
        "juice", "beer", "wine", "spirits", "cigarettes", "tobacco", "yoghurt", "icecream", "handwash", "sausage", "bacon", "ham", "cheese", "butter", "cream", "eggs", "fish", "chicken", "beef", "pork", "lamb", "turkey", "lighter"
        "medicine", "drugs", "pharmacy", "cosmetics", "beauty", "Wheat flour", "pasta", "noodles", "cereals", "biscuits", "snacks", "chocolate", "whisky"
        "electronics", "phones", "computers", "clothing", "shoes", "bags", "beddings", "beans", "peas", "fruits", "cosmetics", "vegetables", "meat", "spices", "diaper",
        "books", "stationary", "hardware", "condoms", "toys", "games", "furniture", "appliances", "kitchenware", "utensils", "tools", "accessories", "jewelry", "watches", "perfumes", "sauces", "condiments"
    ])

    # Unit patterns
    unit_patterns: List[str] = field(default_factory=lambda: [
        r'kg', r'g', r'mg',                    # weight
        r'ml', r'l',                            # volume
        r'pcs?', r'packs?',                     # count
        r'inch', r'ft', r'feet',               # length
    ])


class AttributeExtractor:
    """
    Extracts structured attributes from raw product data.

    Responsibilities:
    - Extract brand
    - Extract category/subcategory
    - Extract size/unit/quantity
    - Extract variant/flavour
    - Extract package type
    - Extract colour (where applicable)
    """

    def __init__(self, rules: Optional[ExtractionRules] = None):
        self.rules = rules or ExtractionRules()

        # Compile regex patterns for efficiency
        self._size_pattern = re.compile(
            r'(\d+(?:\.\d+)?)\s*(' + '|'.join(self.rules.unit_patterns) + r')\b',
            re.IGNORECASE
        )

        # Brand pattern (will be built dynamically)
        self._brand_pattern = None
        self._rebuild_brand_pattern()

    def _rebuild_brand_pattern(self):
        """Rebuild the brand regex pattern from known brands."""
        if self.rules.known_brands:
            escaped_brands = [re.escape(brand) for brand in self.rules.known_brands]
            pattern = r'\b(' + '|'.join(escaped_brands) + r')\b'
            self._brand_pattern = re.compile(pattern, re.IGNORECASE)
        else:
            self._brand_pattern = None

    def extract_attributes(self, raw_text: str) -> ExtractedAttributes:
        """
        Extract attributes from raw product text.

        Args:
            raw_text: Raw product title/description

        Returns:
            ExtractedAttributes object with discovered attributes
        """
        attrs = ExtractedAttributes(raw_text=raw_text)

        if not raw_text:
            return attrs

        # Clean text for processing
        cleaned = re.sub(r'\s+', ' ', raw_text.strip())
        attrs.cleaned_text = cleaned

        # Extract size and unit
        size_match = self._size_pattern.search(cleaned)
        if size_match:
            attrs.size = float(size_match.group(1))
            attrs.unit = size_match.group(2).lower()

        # Extract brand
        attrs.brand = self._extract_brand(cleaned)

        # Extract category/subcategory
        attrs.category, attrs.subcategory = self._extract_category(cleaned)

        # Extract variant/flavour
        attrs.variant, attrs.flavour = self._extract_variant_flavour(cleaned, attrs.brand, attrs.category)

        # Extract package type
        attrs.package_type = self._extract_package_type(cleaned)

        # Extract colour
        attrs.colour = self._extract_colour(cleaned)

        return attrs

    def _extract_brand(self, text: str) -> Optional[str]:
        """Extract brand from text."""
        if not self._brand_pattern:
            return None

        match = self._brand_pattern.search(text)
        if match:
            # Return the brand as found in known_brands (proper casing)
            matched_text = match.group(0).lower()
            for brand in self.rules.known_brands:
                if brand.lower() == matched_text:
                    return brand
            return matched_text  # fallback
        return None


    def _extract_category(self, text: str) -> tuple[Optional[str], Optional[str]]:
        if not text:
            return None, None

        text_lower = text.lower()

        matches = []
        for category in self.rules.known_categories:
            pattern = r'\b' + re.escape(category) + r'\b'
            if re.search(pattern, text_lower):
                matches.append(category)

        if not matches:
            return None, None

        # Longest match wins as primary category (handles "maize flour" vs "maize")
        category = max(matches, key=len)
        subcategory = None
        for subcat in matches:
            if subcat != category and subcat not in category and category not in subcat:
                subcategory = subcat
                break

        return category, subcategory


    def _extract_variant_flavour(self, text: str, brand: Optional[str], category: Optional[str]) -> tuple[Optional[str], Optional[str]]:
        """
        Extract variant and flavour from text.

        This is heuristic-based - looks for descriptive terms after removing
        brand, size, unit, and category.
        """
        if not text:
            return None, None

        # Start with cleaned text
        working_text = text.lower()

        # Remove brand if found
        if brand:
            brand_pattern = re.compile(r'\b' + re.escape(brand.lower()) + r'\b')
            working_text = brand_pattern.sub('', working_text)

        # Remove size/unit patterns
        working_text = self._size_pattern.sub('', working_text)

        # Remove category if found
        if category:
            category_pattern = re.compile(r'\b' + re.escape(category.lower()) + r'\b')
            working_text = category_pattern.sub('', working_text)

        # Clean up extra spaces
        working_text = re.sub(r'\s+', ' ', working_text).strip()

        # Common flavour/variant indicators
        flavour_indicators = [
            'chocolate', 'vanilla', 'strawberry', 'banana', 'mango', 'pineapple',
            'lemon', 'lime', 'orange', 'apple', 'blackcurrant', 'raspberry',
            'mint', 'menthol', 'plain', 'flavoured', 'flavored', 'sweetened',
            'unsweetened', 'low-fat', 'fat-free', 'skim', 'whole', 'semi-skimmed'
        ]

        variant_indicators = [
            'loaf', 'bun', 'roll', 'slice', 'granulated', 'brown', 'white',
            'pure', 'natural', 'organic', 'premium', 'standard', 'economy',
            'family', 'pack', 'bundle', 'twin', 'triple'
        ]

        flavour = None
        variant = None

        # Check for flavours
        for indicator in flavour_indicators:
            if indicator in working_text:
                flavour = indicator
                # Remove from text to avoid double-counting
                working_text = working_text.replace(indicator, '')
                break

        # Check for variants
        for indicator in variant_indicators:
            if indicator in working_text:
                variant = indicator
                # Remove from text to avoid double-counting
                working_text = working_text.replace(indicator, '')
                break

        # Clean up again
        if flavour or variant:
            working_text = re.sub(r'\s+', ' ', working_text).strip()

        # Remaining text might be additional descriptor
        if working_text and len(working_text) > 2:
            if not variant:
                variant = working_text
            elif not flavour:
                flavour = working_text

        return variant, flavour

    def _extract_package_type(self, text: str) -> Optional[str]:
        """Extract package type from text."""
        if not text:
            return None

        text_lower = text.lower()

        package_types = [
            'bottle', 'can', 'packet', 'pack', 'box', 'carton', 'jar', 'tin',
            'pouch', 'sachet', 'wrapper', 'bag', 'sack', 'crate', 'barrel',
            'container', 'wrapper', 'film', 'wrap'
        ]

        for ptype in package_types:
            if ptype in text_lower:
                return ptype

        return None

    def _extract_colour(self, text: str) -> Optional[str]:
        """Extract colour from text."""
        if not text:
            return None

        text_lower = text.lower()

        colours = [
            'white', 'black', 'red', 'blue', 'green', 'yellow', 'brown', 'orange',
            'purple', 'pink', 'grey', 'gray', 'silver', 'gold', 'transparent',
            'clear', 'natural'
        ]

        for colour in colours:
            if colour in text_lower:
                return colour

        return None