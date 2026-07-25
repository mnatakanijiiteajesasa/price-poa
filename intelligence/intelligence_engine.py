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
from intelligence.anomaly_detection.isolation_forest_detector import (
    check_price_anomalies
)
from intelligence.product_recommendations.cosine_similarity_recommender import (
    get_product_recommendations_for_query,
    get_cheaper_substitute,
    product_recommender
)
from intelligence.price_correlation.pearson_correlation_tracker import (
    update_price_correlations,
    get_product_correlations,
    get_leader_follower_relationships,
    correlation_tracker
)
from intelligence.query_trends.aggregation_pipeline import (
    analyze_query_trends,
    get_cached_trend_analysis,
    is_trend_cache_fresh,
    trend_aggregator
)

logger = logging.getLogger(__name__)


class IntelligenceEngine:
    """
    Main intelligence engine that coordinates all AI/ML components.
    Provides a unified interface for the application to access intelligence features.
    """

    def __init__(self):
        """Initialize the intelligence engine."""
        self.last_maintenance_run = None
        self.maintenance_interval_hours = 6  # Run maintenance every 6 hours
        # Reference to the global recommender instance
        self.product_recommender = product_recommender

    async def initialize_models(self, db: AsyncIOMotorDatabase) -> Dict[str, bool]:
        """
        Initialize/train all ML models with initial data.

        Args:
            db: MongoDB database connection

        Returns:
            Dictionary indicating success/failure of each component initialization
        """
        logger.info("Initializing intelligence models...")

        results = {}

        # Initialize anomaly detection model (will train on first use)
        try:
            # Just verify we can access the class - actual training happens on first use
            from intelligence.anomaly_detection.isolation_forest_detector import PriceAnomalyDetector
            detector = PriceAnomalyDetector()
            # Don't train yet - train on first use to avoid slowing startup
            results['anomaly_detection'] = True
            logger.info("Anomaly detection module ready (will train on first use)")
        except Exception as e:
            logger.error(f"Error preparing anomaly detection: {e}")
            results['anomaly_detection'] = False

        # Initialize product recommendation model
        try:
            results['product_recommendations'] = await self.product_recommender.train(db, lookback_days=7)
            if results['product_recommendations']:
                logger.info("Product recommendation model initialized successfully")
            else:
                logger.warning("Failed to initialize product recommendation model")
        except Exception as e:
            logger.error(f"Error initializing product recommendations: {e}")
            results['product_recommendations'] = False

        # Price correlation tracker is ready to use (computes on demand)
        try:
            from intelligence.price_correlation.pearson_correlation_tracker import PriceCorrelationTracker
            tracker = PriceCorrelationTracker()
            results['price_correlation'] = True
            logger.info("Price correlation tracker ready")
        except Exception as e:
            logger.error(f"Error preparing price correlation: {e}")
            results['price_correlation'] = False

        # Query trend aggregator is ready to use
        try:
            from intelligence.query_trends.aggregation_pipeline import QueryTrendAggregator
            aggregator = QueryTrendAggregator()
            results['query_trends'] = True
            logger.info("Query trend aggregator ready")
        except Exception as e:
            logger.error(f"Error preparing query trends: {e}")
            results['query_trends'] = False

        self.last_maintenance_run = datetime.utcnow()
        return results

    async def run_maintenance(self, db: AsyncIOMotorDatabase) -> Dict[str, Any]:
        """
        Run periodic maintenance tasks for all intelligence components.

        Args:
            db: MongoDB database connection

        Returns:
            Dictionary with results of maintenance operations
        """
        logger.info("Running intelligence maintenance tasks...")
        maintenance_start = datetime.utcnow()
        results = {}

        try:
            # Update anomaly detection model
            try:
                from intelligence.anomaly_detection.isolation_forest_detector import PriceAnomalyDetector
                detector = PriceAnomalyDetector()
                results['anomaly_detection_update'] = await detector.train(db, lookback_days=30)
                if results['anomaly_detection_update']:
                    logger.info("Anomaly detection model updated")
                else:
                    logger.warning("Failed to update anomaly detection model")
            except Exception as e:
                logger.error(f"Error updating anomaly detection: {e}")
                results['anomaly_detection_update'] = False

            # Update product recommendation model
            try:
                results['product_recommendations_update'] = await self.product_recommender.train(db, lookback_days=7)
                if results['product_recommendations_update']:
                    logger.info("Product recommendation model updated")
                else:
                    logger.warning("Failed to update product recommendation model")
            except Exception as e:
                logger.error(f"Error updating product recommendations: {e}")
                results['product_recommendations_update'] = False

            # Update price correlations
            try:
                results['price_correlation_update'] = await update_price_correlations(db, lookback_days=30)
                if results['price_correlation_update']:
                    logger.info("Price correlations updated")
                else:
                    logger.warning("Failed to update price correlations")
            except Exception as e:
                logger.error(f"Error updating price correlations: {e}")
                results['price_correlation_update'] = False

            # Note: Query trends are updated on-demand via analyze_query_trends
            results['query_trends_available'] = True

            self.last_maintenance_run = datetime.utcnow()
            maintenance_duration = (datetime.utcnow() - maintenance_start).total_seconds()

            results['maintenance_duration_seconds'] = round(maintenance_duration, 2)
            results['maintenance_timestamp'] = self.last_maintenance_run.isoformat()
            results['overall_success'] = all([
                results.get('anomaly_detection_update', False),
                results.get('product_recommendations_update', False),
                results.get('price_correlation_update', False)
            ])

            logger.info(f"Maintenance completed in {maintenance_duration:.2f}s")
            return results

        except Exception as e:
            logger.error(f"Error during intelligence maintenance: {e}")
            return {
                'error': str(e),
                'maintenance_timestamp': datetime.utcnow().isoformat(),
                'overall_success': False
            }

    async def analyze_price_anomalies(self, db: AsyncIOMotorDatabase,
                                    price_records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Analyze price records for anomalies using the isolation forest model.

        Args:
            db: MongoDB database connection
            price_records: List of price dictionaries to analyze

        Returns:
            List of price records with anomaly flags added
        """
        try:
            return await check_price_anomalies(db, price_records)
        except Exception as e:
            logger.error(f"Error analyzing price anomalies: {e}")
            # Return original records with no anomalies flagged
            for record in price_records:
                if isinstance(record, dict):
                    record['is_anomaly'] = False
                    record['anomaly_score'] = 0.5
            return price_records

    async def get_product_recommendations(self, db: AsyncIOMotorDatabase,
                                        query_products: List[str],
                                        limit: int = 5) -> List[Dict[str, Any]]:
        """
        Get product recommendations for a user query.

        Args:
            db: MongoDB database connection
            query_products: List of product IDs mentioned in the query
            limit: Maximum number of recommendations to return

        Returns:
            List of recommendation dictionaries
        """
        try:
            return await get_product_recommendations_for_query(db, query_products, limit)
        except Exception as e:
            logger.error(f"Error getting product recommendations: {e}")
            return []

    async def get_cheaper_substitute(self, db: AsyncIOMotorDatabase,
                                   product_id: str,
                                   max_price_ratio: float = 0.85) -> Optional[Dict[str, Any]]:
        """
        Get a cheaper substitute for a product.

        Args:
            db: MongoDB database connection
            product_id: ID of the product to find substitute for
            max_price_ratio: Maximum price ratio for considering a "cheaper" substitute

        Returns:
            Dictionary with substitute information or None if not found
        """
        try:
            return await get_cheaper_substitute(db, product_id, max_price_ratio)
        except Exception as e:
            logger.error(f"Error getting cheaper substitute: {e}")
            return None

    async def update_price_correlations(self, db: AsyncIOMotorDatabase,
                                      lookback_days: int = 30) -> bool:
        """
        Update price correlation calculations.

        Args:
            db: MongoDB database connection
            lookback_days: Number of days of historical data to use

        Returns:
            True if update successful, False otherwise
        """
        try:
            return await update_price_correlations(db, lookback_days)
        except Exception as e:
            logger.error(f"Error updating price correlations: {e}")
            return False

    def get_product_correlations(self, product_id: str) -> List[Dict[str, Any]]:
        """
        Get correlation data for a product.

        Args:
            product_id: ID of the product

        Returns:
            List of correlation dictionaries for the product
        """
        try:
            return get_product_correlations(product_id)
        except Exception as e:
            logger.error(f"Error getting product correlations: {e}")
            return []

    def get_leader_follower_relationships(self, product_id: str) -> List[Dict[str, Any]]:
        """
        Get identified leader-follower relationships for a product.

        Args:
            product_id: ID of the product

        Returns:
            List of dictionaries describing leader-follower relationships
        """
        try:
            return get_leader_follower_relationships(product_id)
        except Exception as e:
            logger.error(f"Error getting leader-follower relationships: {e}")
            return []

    async def analyze_query_trends(self, db: AsyncIOMotorDatabase,
                                 lookback_days: int = 7) -> Dict[str, Any]:
        """
        Analyze query trends from search logs.

        Args:
            db: MongoDB database connection
            lookback_days: Number of days of query logs to analyze

        Returns:
            Dictionary containing trend analysis results
        """
        try:
            return await analyze_query_trends(db, lookback_days)
        except Exception as e:
            logger.error(f"Error analyzing query trends: {e}")
            return {}

    def get_cached_trend_analysis(self) -> Dict[str, Any]:
        """
        Get the last cached trends analysis.

        Returns:
            Dictionary with cached trend data or empty dict if none available
        """
        return get_cached_trend_analysis()

    def is_trend_cache_fresh(self, max_age_hours: int = 24) -> bool:
        """
        Check if the trend cache is still fresh.

        Args:
            max_age_hours: Maximum age in hours before considering cache stale

        Returns:
            True if cache is fresh, False otherwise
        """
        return is_trend_cache_fresh(max_age_hours)

    def get_system_status(self) -> Dict[str, Any]:
        """
        Get the current status of all intelligence components.

        Returns:
            Dictionary with status information for each component
        """
        try:
            # Check anomaly detection status
            anomaly_status = {
                'model_trained': False,
                'last_trained': None,
                'ready': True
            }
            try:
                from intelligence.anomaly_detection.isolation_forest_detector import anomaly_detector
                anomaly_status['model_trained'] = getattr(anomaly_detector, 'is_trained', False)
                anomaly_status['last_trained'] = getattr(anomaly_detector, 'last_updated', None)
                anomaly_status['ready'] = True
            except:
                anomaly_status['ready'] = False

            # Check product recommendations status
            rec_status = {
                'model_trained': False,
                'last_trained': None,
                'ready': True
            }
            try:
                rec_status['model_trained'] = getattr(self.product_recommender, 'is_trained', False)
                rec_status['last_trained'] = getattr(self.product_recommender, 'last_updated', None)
                rec_status['ready'] = True
            except:
                rec_status['ready'] = False

            # Check price correlation status
            corr_status = {
                'ready': True,
                'last_updated': None
            }
            try:
                corr_status['last_updated'] = getattr(correlation_tracker, 'last_updated', None)
                corr_status['ready'] = True
            except:
                corr_status['ready'] = False

            # Check query trends status
            trend_status = {
                'cache_available': False,
                'last_updated': None,
                'ready': True
            }
            try:
                cached = get_cached_trend_analysis()
                trend_status['cache_available'] = bool(cached)
                trend_status['last_updated'] = getattr(trend_aggregator, 'last_updated', None)
                trend_status['ready'] = True
            except:
                trend_status['ready'] = False

            return {
                'anomaly_detection': anomaly_status,
                'product_recommendations': rec_status,
                'price_correlation': corr_status,
                'query_trends': trend_status,
                'last_maintenance': self.last_maintenance_run.isoformat() if self.last_maintenance_run else None,
                'timestamp': datetime.utcnow().isoformat()
            }

        except Exception as e:
            logger.error(f"Error getting system status: {e}")
            return {
                'error': str(e),
                'timestamp': datetime.utcnow().isoformat()
            }


# Global instance for easy access
intelligence_engine = IntelligenceEngine()


# Convenience functions for external use
async def initialize_intelligence(db: AsyncIOMotorDatabase) -> Dict[str, bool]:
    """Initialize all intelligence components."""
    return await intelligence_engine.initialize_models(db)


async def run_intelligence_maintenance(db: AsyncIOMotorDatabase) -> Dict[str, Any]:
    """Run maintenance on all intelligence components."""
    return await intelligence_engine.run_maintenance(db)


async def analyze_price_anomalies(db: AsyncIOMotorDatabase,
                                price_records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Analyze price records for anomalies."""
    return await intelligence_engine.analyze_price_anomalies(db, price_records)


async def get_product_recommendations(db: AsyncIOMotorDatabase,
                                    query_products: List[str],
                                    limit: int = 5) -> List[Dict[str, Any]]:
    """Get product recommendations for a query."""
    return await intelligence_engine.get_product_recommendations(db, query_products, limit)


async def get_cheaper_substitute(db: AsyncIOMotorDatabase,
                               product_id: str,
                               max_price_ratio: float = 0.85) -> Optional[Dict[str, Any]]:
    """Get a cheaper substitute for a product."""
    return await intelligence_engine.get_cheaper_substitute(db, product_id, max_price_ratio)


async def update_price_correlations(db: AsyncIOMotorDatabase,
                                  lookback_days: int = 30) -> bool:
    """Update price correlation calculations."""
    return await intelligence_engine.update_price_correlations(db, lookback_days)


def get_product_correlations(product_id: str) -> List[Dict[str, Any]]:
    """Get correlation data for a product."""
    return intelligence_engine.get_product_correlations(product_id)


def get_leader_follower_relationships(product_id: str) -> List[Dict[str, Any]]:
    """Get leader-follower relationships for a product."""
    return intelligence_engine.get_leader_follower_relationships(product_id)


async def analyze_query_trends(db: AsyncIOMotorDatabase,
                             lookback_days: int = 7) -> Dict[str, Any]:
    """Analyze query trends from search logs."""
    return await intelligence_engine.analyze_query_trends(db, lookback_days)


def get_cached_trend_analysis() -> Dict[str, Any]:
    """Get cached trend analysis."""
    return intelligence_engine.get_cached_trend_analysis()


def is_trend_cache_fresh(max_age_hours: int = 24) -> bool:
    """Check if trend cache is fresh."""
    return intelligence_engine.is_trend_cache_fresh(max_age_hours)


def get_intelligence_status() -> Dict[str, Any]:
    """Get overall intelligence system status."""
    return intelligence_engine.get_system_status()