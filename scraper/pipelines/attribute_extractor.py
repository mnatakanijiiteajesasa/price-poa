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
        # Retailers / store brands
        "broadways", "naivas", "carrefour", "quickmart", "chandarana", "cleanshelf",
        "eastmatt", "greenspoon", "zucchini",

        # Dairy
        "brookside", "daima", "kcc", "new kcc", "delamere", "fresha", "githunguri",
        "mount kenya", "spin knit", "molo milk", "sameer", "ilara", "buzeki",

        # Cereals / flours / grains
        "kapa", "soko", "jogoo", "pembe", "exe", "mwea rice", "hulkani", "ndovu",
        "capital", "vuna", "supa", "unga", "kifaru", "amaica",

        # Beverages — hot/soft drinks
        "ketepa", "kericho gold", "mumias", "coca-cola", "pepsi", "sprite", "fanta",
        "7up", "mirinda", "krest", "tropical", "afia", "minute maid", "quencher",
        "delmonte", "picana", "keringet", "dasani", "aquamist", "quencher",

        # Alcohol
        "tusker", "eabl", "kenya cane", "chrome", "gilbeys", "kenya breweries",
        "sportsman", "guinness", "smirnoff", "johnnie walker", "black & white",
        "kibao", "vat 69", "ballantines", "hennessy", "richot",

        # Baby / hygiene / FMCG
        "pampers", "huggies", "mamy poko", "always", "molped", "dola",
        "dove", "lifebuoy", "sunlight", "geisha", "imperial leather", "protex",
        "detol", "savlon", "tide", "omo", "surf", "ariel", "persil", "airwick",
        "jik", "harpic", "mr muscle", "vim",

        # Oral / personal care
        "colgate", "pepsodent", "sensodyne", "closeup", "aquafresh", "listerine",
        "garnier", "nivea", "vaseline", "johnson & johnson", "himalaya",
        "herbal essences", "loreal", "maybelline", "revlon", "mac", "clinique",
        "estee lauder", "shiseido", "fair & lovely", "tropikal",

        # Confectionery / snacks
        "cadbury", "kelloggs", "candybury", "hershey's", "mars", "snickers",
        "twix", "kitkat", "bounty", "milky way", "m&m's", "oreo", "lays",
        "pringles", "doritos", "cheetos", "fritos", "tostitos", "hansa",
        "britania", "manji", "trufoods", "cafenaivas", "supa loaf", "festive",

        # Meat / poultry
        "farmers choice", "kenchic", "rina", "zuku foods", "tropical heat",
        "wamama", "kenafric",

        # Household electronics/appliances
        "sony", "samsung", "lg", "panasonic", "toshiba", "sharp", "philips",
        "beko", "haier", "whirlpool", "bosch", "electrolux", "miele", "smeg", "mikasa",
        "kenwood", "delonghi", "breville", "ramtons", "zenta", "von", "amtec",
        "bruhm", "tcl", "hisense", "nunix", "brands", "joerex", "midea"

        # Misc / catch-all
        "unilever", "nestle", "bic", "general meakins", "dairyland", "kasuku",
        "trust", "kiss", "rough rider", "duracell", "eveready",
    ])
    # Common categories
    known_categories: List[str] = field(default_factory=lambda: [
        # Staples
        "milk", "bread", "sugar", "maize flour", "wheat flour", "rice", "maize",
        "unga", "salt", "pasta", "noodles", "cereals", "beans", "peas", "lentils",
        "porridge flour", "baking flour", "cornflakes", "oats", "breakfast cereals", "cooking oil", "vegetable oil",
 
        # Alcohol / drinks
        "spirits", "wine", "beer", "cognac", "brandy", "whisky", "vodka", "gin", "bila shaka"
        "tea", "coffee", "soda", "water", "juice", "energy drinks", "yoghurt drink", "culemborg cape", "tusker"

        # Cleaning / household
        "soap", "detergent", "hand wash", "antiseptic", "bleach", "dish soap",
        "air freshener", "insecticide", "toilet cleaner", "fabric softener",

        # Cooking
        "oil", "fat", "cooking fat", "spices", "sauces", "condiments", "vinegar",
        "baking powder", "yeast", "spice", "soy sauce", "ketchup", "mustard", "mayonnaise", "chili sauce", "hot sauce",
        ""

        # Dairy / proteins / fresh
        "yoghurt", "icecream", "cheese", "butter", "cream", "eggs", "fish", "orange", 
        "chicken", "beef", "pork", "lamb", "turkey", "sausage", "bacon", "ham",
        "fruits", "vegetables", "cucumber", "tomato", "onion", "potato", "carrot", "spinach", "kale", "lettuce",

        # Personal care / health
        "medicine", "drugs", "pharmacy", "cosmetics", "beauty", "diaper", "baby lotion", "baby powder", "baby oil", "baby wipes", "baby shampoo", "baby soap",
        "sanitary pads", "condoms", "tissue paper", "toilet paper", "serviettes", "pads", "tampons", "sanitary napkins", "sanitary towels", "feminine hygiene products",
        "cotton wool", "shaving", "deodorant", "perfumes", "deodrant", "shampoo", "conditioner", "hair oil", "hair cream", "hair gel",
        "body spray", "body lotion", "face cream", "face wash", "toothpaste", "toothbrush", "mouthwash",

        # Snacks / confectionery
        "biscuits", "snacks", "chocolate", "crisps", "cake", "sweets", "candy", "ice cream", "popsicle", "lollipop", "gummies", "chewing gum", "cocoa", "chocolate spread", "peanut butter", "jam", "honey", "syrup", "marshmallow", "caramel", "toffee", "nougat", "fudge",
        "chicken nuggets", "french fries", "popcorn", "nachos", "pretzels", "waffles", "pancakes", "lemon", "watermelon", "grapes", "strawberries", "blueberries", "raspberries", "blackberries", "kiwi", "mango", "papaya", "pineapple", "coconut",

        # Tobacco
        "cigarettes", "tobacco", "lighter",

        # Electronics / appliances
        "electronics", "phones", "computers", "TV", "fridge", "washing machine",
        "microwave", "oven", "stove", "blender", "mixer", "toaster", "kettle", "cleaner", "air fryer", "grill", "pressure cooker", "slow cooker", "rice cooker",
        "iron", "vacuum cleaner", "air conditioner", "heater", "fan", "woofer", "dryer", "projector", "camera", "printer", "scanner", "router", "modem", "speaker", "headphones", "earphones", "battery", "charger",
        "soundbar", "speaker", "headphones", "earphones", "battery", "charger","tv", 
        "power bank", "adapter", "cable", "light bulb", "candle", "torch", "flask"

        # Home / other
        "clothing", "shoes", "bags", "beddings", "books", "stationary", "bucket", "pegs", "mop", "broom", "brush", "dustpan", "bin", "trash can", "laundry basket", "hanger", "curtain", "mat", "rug", "towel", "blanket", "pillow", "sheet", "duvet", "mattress protector",
        "hardware", "toys", "games", "furniture", "appliances", "kitchenware", "table tennis", "soccer ball", "basketball", "tennis racket", "golf club", "fishing rod", "camping gear", "hiking gear", "cycling gear", "swimming gear", "skiing gear", "snowboarding gear", "skateboarding gear", "rollerblading gear",
        "utensils", "tools", "accessories", "jewelry", "watches", "football", "cleanser", "shower", "photocopy paper", "printer paper", "notebook", "pen", "pencil", "marker", "highlighter", "eraser", "sharpener", "stapler", "tape", "glue", "scissors", "calculator", "folder", "binder", "envelope", "label", "sticky notes", 
        "volleyball", "bag", "scouring powder", "towel", "tissue", "sticky notes", "books", "condom", "calculator", "short hand book", "a4", "" 
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