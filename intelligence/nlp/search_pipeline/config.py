"""
Configuration module for the search pipeline.
Contains configuration constants and settings for the improved search pipeline.
"""

import os
from typing import Dict, Any

# Normalization configuration
NORMALIZATION_CONFIG = {
    # Unit mappings
    'unit_mappings': {
        # Volume
        'ltr': 'L',
        'litre': 'L',
        'liter': 'L',
        'litres': 'L',
        'liters': 'L',
        'ml': 'ml',
        'milliliter': 'ml',
        'millilitre': 'ml',
        'milliliters': 'ml',
        'millilitres': 'ml',

        # Weight
        'kg': 'kg',
        'kgs': 'kg',
        'kilogram': 'kg',
        'kilograms': 'kg',
        'kilogramme': 'kg',
        'kilogrammes': 'kg',
        'g': 'g',
        'gram': 'g',
        'grams': 'g',
        'gramme': 'g',
        'grammes': 'g',
        'mg': 'mg',
        'milligram': 'mg',
        'milligrams': 'mg',

        # Count/pack
        'pc': 'pcs',
        'piece': 'pcs',
        'pieces': 'pcs',
        'pcs': 'pcs',
        'pack': 'pcs',
        'packs': 'pcs',
        'packet': 'pcs',
        'packets': 'pcs',

        # Other common units
        'dozen': 'dozen',
        'dozens': 'dozen',
        'dz': 'dozen',
        'bottle': 'btl',
        'bottles': 'btl',
        'btl': 'btl',
        'can': 'cn',
        'cans': 'cn',
        'cn': 'cn',
        'bag': 'bg',
        'bags': 'bg',
        'bg': 'bg',
        'box': 'bx',
        'boxes': 'bx',
        'bx': 'bx',
    },

    # Quantity normalization patterns
    'quantity_patterns': [
        (r'^(\d+)\.?(\d*)\s*kgs?$', r'\1.\2 kg'),  # 2kgs -> 2 kg
        (r'^(\d+)\.?(\d*)\s*kilo(gram)?s?$', r'\1.\2 kg'),  # 2 kilos -> 2 kg
        (r'^(\d+)\.?(\d*)\s*g$', r'\1.\2 g'),   # 500g -> 500 g
        (r'^(\d+)\.?(\d*)\s*grams?$', r'\1.\2 g'),  # 500 grams -> 500 g
        (r'^(\d+)\.?(\d*)\s*ltrs?$', r'\1.\2 L'),  # 2ltrs -> 2 L
        (r'^(\d+)\.?(\d*)\s*liters?$', r'\1.\2 L'),  # 2 liters -> 2 L
        (r'^(\d+)\.?(\d*)\s*litres?$', r'\1.\2 L'),  # 2 litres -> 2 L
        (r'^(\d+)\.?(\d*)\s*mls?$', r'\1.\2 ml'),   # 500mls -> 500 ml
        (r'^(\d+)\.?(\d*)\s*milliliters?$', r'\1.\2 ml'),  # 500 milliliters -> 500 ml
        (r'^(\d+)\.?(\d*)\s*millilitres?$', r'\1.\2 ml'),  # 500 millilitres -> 500 ml
        (r'^half\s*(kg|g|gms?|grams?)', r'0.5 \1'),  # half kg -> 0.5 kg
        (r'^half\s*(ltr|litre|liter|litres|liters)', r'0.5 L'),  # half litre -> 0.5 L
        (r'^half\s*(ml|milliliter|millilitre|milliliters|millilitres)', r'0.5 ml'),  # half ml -> 0.5 ml
        (r'^half\s*(pcs?|pieces?|pieces|packs?|packets?)', r'0.5 pcs'),  # half pcs -> 0.5 pcs
        (r'^half\s*(dozen|dozens)', r'0.5 dozen'),  # half dozen -> 0.5 dozen
        (r'^half\s*(bottle|bottles|btl)', r'0.5 btl'),  # half bottle -> 0.5 btl
        (r'^half\s*(can|cans|cn)', r'0.5 cn'),  # half can -> 0.5 cn
        (r'^half\s*(bag|bags|bg)', r'0.5 bg'),  # half bag -> 0.5 bg
        (r'^half\s*(box|boxes|bx)', r'0.5 bx'),  # half box -> 0.5 bx
    ],

    # Synonym mappings (can be loaded from file)
    'synonym_mappings': {},

    # Text normalization
    'text_normalization': {
        'lowercase': True,
        'remove_punctuation': True,
        'collapse_spaces': True,
        'remove_extra_whitespace': True
    }
}

# Query Parser configuration
QUERY_PARSER_CONFIG = {
    # Brand patterns (common brands)
    'brand_patterns': [
        'broookside', 'brookeside', 'brookside',
        'daima', ' dairy',
        'jogoo', 'jogoo',
        'bidco', 'bidco oil refineries',
        "mumias", 'mumias sugar',
        'kericho gold', 'kericomb',
        'jangomba', 'jangomba tea',
        'ketepa', 'ketepa tea',
        'benson', 'benson & hedges',
        'safaricom',
        'coca cola', 'coca-cola',
        'pepsi',
        'nakumatt',
        'tuskys',
        'naivas',
        'chandarana',
        'quickmart',
        'chandarana foodplus',
    ],

    # Category patterns (common product categories)
    'category_patterns': [
        'milk', 'maziwa',
        'unga', 'flour', 'maize flour', 'wheat flour',
        'sugar', 'sukari',
        'oil', 'cooking oil', 'mixture', 'salad oil',
        'bread', 'breade',
        'rice', 'mchele',
        'beans', 'maharagwe',
        'tea', 'chai',
        'salt', 'chumvi',
        'soap', 'detergent',
        'toothpaste', 'tooth paste',
        'milk powder', 'powdered milk',
        'yogurt', 'yoghurt', 'malai',
        'butter',
        'cheese',
        'eggs', 'eggie',
        'meat', 'nyama',
        'chicken', 'kuku',
        'fish', 'samaki',
        'fruits', 'matunda',
        'vegetables', 'mboga',
        'potatoes', 'viazi',
        'tomatoes', 'nyanya',
        'onions', 'vyanguu',
    ],

    # Size/unit patterns
    'size_patterns': [
        r'(\d+(?:\.\d+)?)\s*(kg|g|mg)',  # weight
        r'(\d+(?:\.\d+)?)\s*(l|ltr|litre|liter|litres|liters|ml|milliliter|millilitre|milliliters|millilitres)',  # volume
        r'(\d+(?:\.\d+)?)\s*(pcs?|pieces?|packs?|packets?)',  # count
        r'(\d+(?:\.\d+)?)\s*(dozen|dozens|dz)',  # dozen
        r'(\d+(?:\.\d+)?)\s*(btl|bottle|bottles)',  # bottles
        r'(\d+(?:\.\d+)?)\s*(cn|can|cans)',  # cans
        r'(\d+(?:\.\d+)?)\s*(bg|bag|bags)',  # bags
        r'(\d+(?:\.\d+)?)\s*(bx|box|boxes)',  # boxes
    ]
}

# Vector Search configuration
VECTOR_SEARCH_CONFIG = {
    'model_name': os.getenv('VECTOR_MODEL_NAME', 'BAAI/bge-small-en-v1.5'),
    'vector_size': int(os.getenv('VECTOR_SIZE', '384')),  # BAAI/bge-small-en-v1.5 is 384 dim
    'collection_name': os.getenv('VECTOR_COLLECTION', 'product_embeddings'),
    'qdrant_host': os.getenv('QDRANT_HOST', 'host.docker.internal'),
    'qdrant_port': int(os.getenv('QDRANT_PORT', '6333')),
    'search_limit': int(os.getenv('VECTOR_SEARCH_LIMIT', '50')),
    'score_threshold': float(os.getenv('VECTOR_SCORE_THRESHOLD', '0.3')),
}

# Business Ranker configuration
RANKER_CONFIG = {
    'weights': {
        'vector': float(os.getenv('RANKER_WEIGHT_VECTOR', '0.45')),
        'fuzzy': float(os.getenv('RANKER_WEIGHT_FUZZY', '0.25')),
        'brand': float(os.getenv('RANKER_WEIGHT_BRAND', '0.15')),
        'category': float(os.getenv('RANKER_WEIGHT_CATEGORY', '0.10')),
        'quantity': float(os.getenv('RANKER_WEIGHT_QUANTITY', '0.10')),
        'alias': float(os.getenv('RANKER_WEIGHT_ALIAS', '0.05'))
    },
    # Boost values for exact matches
    'boosts': {
        'brand_exact': float(os.getenv('RANKER_BOOST_BRAND_EXACT', '0.2')),
        'category_exact': float(os.getenv('RANKER_BOOST_CATEGORY_EXACT', '0.15')),
        'quantity_exact': float(os.getenv('RANKER_BOOST_QUANTITY_EXACT', '0.1')),
    },
    # Minimum score thresholds
    'min_scores': {
        'vector': float(os.getenv('RANKER_MIN_VECTOR_SCORE', '0.1')),
        'fuzzy': float(os.getenv('RANKER_MIN_FUZZY_SCORE', '0.1')),
    }
}

# RapidFuzz configuration
RAPIDFUZZ_CONFIG = {
    'cache_ttl_seconds': int(os.getenv('RAPIDFUZZ_CACHE_TTL', '300')),  # 5 minutes
    'score_cutoff': int(os.getenv('RAPIDFUZZ_SCORE_CUTOFF', '60')),
    'limit_multiplier': int(os.getenv('RAPIDFUZZ_LIMIT_MULTIPLIER', '2')),
    'scorer': 'WRatio',  # Options: ratio, partial_ratio, token_sort_ratio, token_set_ratio, WRatio, QRatio
}

# Hybrid Retrieval configuration
HYBRID_RETRIEVAL_CONFIG = {
    'vector_limit': int(os.getenv('HYBRID_VECTOR_LIMIT', '50')),  # Top K from vector search
    'final_limit': int(os.getenv('HYBRID_FINAL_LIMIT', '20')),   # Final results to return
    'enable_reranking': os.getenv('HYBRID_ENABLE_RERANKING', 'true').lower() == 'true',
    'enable_business_ranking': os.getenv('HYBRID_ENABLE_BUSINESS_RANKING', 'true').lower() == 'true',
}

def get_config() -> Dict[str, Any]:
    """Get all configuration as a dictionary."""
    return {
        'normalization': NORMALIZATION_CONFIG,
        'query_parser': QUERY_PARSER_CONFIG,
        'vector_search': VECTOR_SEARCH_CONFIG,
        'ranker': RANKER_CONFIG,
        'rapidfuzz': RAPIDFUZZ_CONFIG,
        'hybrid_retrieval': HYBRID_RETRIEVAL_CONFIG
    }

def get_normalization_config() -> Dict[str, Any]:
    """Get normalization configuration."""
    return NORMALIZATION_CONFIG

def get_query_parser_config() -> Dict[str, Any]:
    """Get query parser configuration."""
    return QUERY_PARSER_CONFIG

def get_vector_search_config() -> Dict[str, Any]:
    """Get vector search configuration."""
    return VECTOR_SEARCH_CONFIG

def get_ranker_config() -> Dict[str, Any]:
    """Get ranker configuration."""
    return RANKER_CONFIG

def get_rapidfuzz_config() -> Dict[str, Any]:
    """Get RapidFuzz configuration."""
    return RAPIDFUZZ_CONFIG

def get_hybrid_retrieval_config() -> Dict[str, Any]:
    """Get hybrid retrieval configuration."""
    return HYBRID_RETRIEVAL_CONFIG