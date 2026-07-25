"""
Intelligence Layer for PricePoa
Exports the main intelligence engine and convenience functions.
"""

# Main intelligence engine
from .intelligence_engine import (
    IntelligenceEngine,
    intelligence_engine,
    initialize_intelligence,
    run_intelligence_maintenance,
    analyze_price_anomalies,
    get_product_recommendations,
    get_cheaper_substitute,
    update_price_correlations,
    get_product_correlations,
    get_leader_follower_relationships,
    analyze_query_trends,
    get_cached_trend_analysis,
    is_trend_cache_fresh,
    get_intelligence_status
)

# Version information
__version__ = "1.0.0"
__author__ = "PricePoa Intelligence Team"
__description__ = "AI/ML intelligence layer for PricePoa price comparison platform"

# Define what gets imported with "from intelligence import *"
__all__ = [
    # Main engine
    'IntelligenceEngine',
    'intelligence_engine',

    # Initialization and maintenance
    'initialize_intelligence',
    'run_intelligence_maintenance',

    # Anomaly detection
    'analyze_price_anomalies',

    # Product recommendations
    'get_product_recommendations',
    'get_cheaper_substitute',

    # Price correlation
    'update_price_correlations',
    'get_product_correlations',
    'get_leader_follower_relationships',

    # Query trends
    'analyze_query_trends',
    'get_cached_trend_analysis',
    'is_trend_cache_fresh',

    # System status
    'get_intelligence_status',

    # Metadata
    '__version__',
    '__author__',
    '__description__'
]