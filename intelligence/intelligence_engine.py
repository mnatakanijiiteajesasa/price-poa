# THIS IS THE ACTUAL FILE BEING USED - VERIFY THIS APPEARS IN ERRORS
"""
Intelligence Layer Coordinator
Orchestrates the four intelligence components: anomaly detection, product recommendations,
price correlation tracking, and query trend aggregation.
"""
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from motor.motor_asyncio import AsyncIOMotorDatabase
import asyncio

# Import the intelligence components
from anomaly_detection.isolation_forest_detector import (
    check_price_anomalies
)
from product_recommendations.cosine_similarity_recommender import (
    get_product_recommendations_for_query,
    get_cheaper_substitute,
    product_recommender
)
from price_correlation.pearson_correlation_tracker import (
    update_price_correlations,
    get_product_correlations,
    get_leader_follower_relationships,
    correlation_tracker
)
from query_trends.aggregation_pipeline import (
    analyze_query_trends,
    get_cached_trend_analysis,
    is_trend_cache_fresh,
    trend_aggregator
)

logger = logging.getLogger(__name__)