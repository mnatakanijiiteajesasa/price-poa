"""
Query trend aggregation system using MongoDB aggregation pipelines.
Analyzes search queries to identify trending products, seasonal patterns, and basket analysis.
"""
import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from motor.motor_asyncio import AsyncIOMotorDatabase
import asyncio
from collections import Counter, defaultdict
import heapq

logger = logging.getLogger(__name__)


class QueryTrendAggregator:
    """
    Aggregates and analyzes query trends from user search logs.
    Provides insights for supermarket partnership pitches and inventory planning.
    """

    def __init__(self):
        """Initialize the query trend aggregator."""
        self.last_updated = None
        self.trends_cache = {}

    async def aggregate_query_trends(self, db: AsyncIOMotorDatabase,
                                   lookback_days: int = 7) -> Dict[str, Any]:
        """
        Run aggregated queries on query logs to extract trends.

        Args:
            db: MongoDB database connection
            lookback_days: Number of days of query logs to analyze

        Returns:
            Dictionary containing various trend analyses
        """
        try:
            logger.info(f"Aggregating query trends for last {lookback_days} days")

            cutoff_date = datetime.utcnow() - timedelta(days=lookback_days)
            query_logs_collection = db.query_logs

            # Run multiple aggregation pipelines in parallel
            tasks = [
                self._get_top_products_by_town(db, query_logs_collection, cutoff_date),
                self._get_query_volume_by_hour(db, query_logs_collection, cutoff_date),
                self._get_basket_size_distribution(db, query_logs_collection, cutoff_date),
                self._get_seasonal_patterns(db, query_logs_collection, cutoff_date),
                self._get_search_term_trends(db, query_logs_collection, cutoff_date)
            ]

            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Process results
            trends = {
                'top_products_by_town': {},
                'query_volume_by_hour': {},
                'basket_size_distribution': {},
                'seasonal_patterns': {},
                'search_term_trends': {},
                'metadata': {
                    'analysis_period_days': lookback_days,
                    'generated_at': datetime.utcnow(),
                    'data_quality': {}
                }
            }

            # Handle results
            trend_names = ['top_products_by_town', 'query_volume_by_hour',
                          'basket_size_distribution', 'seasonal_patterns', 'search_term_trends']

            for i, (trend_name, result) in enumerate(zip(trend_names, results)):
                if isinstance(result, Exception):
                    logger.error(f"Error in {trend_name}: {result}")
                    trends[trend_name] = {}
                    trends['metadata']['data_quality'][trend_name] = f"error: {str(result)}"
                else:
                    trends[trend_name] = result if result else {}
                    trends['metadata']['data_quality'][trend_name] = "success"

            self.trends_cache = trends
            self.last_updated = datetime.utcnow()

            logger.info("Query trend aggregation completed successfully")
            return trends

        except Exception as e:
            logger.error(f"Error aggregating query trends: {e}")
            return {}

    async def _get_top_products_by_town(self, db: AsyncIOMotorDatabase,
                                      collection, cutoff_date: datetime) -> Dict[str, List[Dict]]:
        """
        Get top 20 queried products per town.

        Returns:
            Dictionary mapping town names to lists of top products with counts
        """
        try:
            pipeline = [
                {"$match": {"timestamp": {"$gte": cutoff_date}}},
                {"$unwind": "$products"},  # Deconstruct products array
                {"$lookup": {
                    "from": "products",
                    "localField": "products",
                    "foreignField": "_id",
                    "as": "product_info"
                }},
                {"$unwind": "$product_info"},
                {"$group": {
                    "_id": {
                        "town": "$town",
                        "product_id": "$products",
                        "product_name": "$product_info.name"
                    },
                    "query_count": {"$sum": 1}
                }},
                {"$sort": {"_id.town": 1, "query_count": -1}},
                {"$group": {
                    "_id": "$_id.town",
                    "top_products": {
                        "$push": {
                            "product_id": "$_id.product_id",
                            "product_name": "$_id.product_name",
                            "query_count": "$query_count"
                        }
                    }
                }},
                {"$project": {
                    "_id": 0,
                    "town": "$_id",
                    "top_products": {"$slice": ["$top_products", 20]}  # Top 20 per town
                }}
            ]

            cursor = collection.aggregate(pipeline)
            results = await cursor.to_list(length=None)

            # Format results
            trends = {}
            for result in results:
                town = result.get('town', 'unknown')
                products = result.get('top_products', [])
                trends[town] = [
                    {
                        'product_id': str(p['product_id']),
                        'product_name': p['product_name'],
                        'query_count': p['query_count']
                    }
                    for p in products
                ]

            return trends

        except Exception as e:
            logger.error(f"Error in top products by town aggregation: {e}")
            return {}

    async def _get_query_volume_by_hour(self, db: AsyncIOMotorDatabase,
                                      collection, cutoff_date: datetime) -> Dict[str, Any]:
        """
        Get query volume distribution by hour of day.

        Returns:
            Dictionary with hourly counts and peak hours
        """
        try:
            pipeline = [
                {"$match": {"timestamp": {"$gte": cutoff_date}}},
                {"$project": {
                    "hour": {"$hour": "$timestamp"},
                    "day_of_week": {"$dayOfWeek": "$timestamp"}  # 1=Sunday, 7=Saturday
                }},
                {"$group": {
                    "_id": {
                        "hour": "$hour",
                        "day_of_week": "$day_of_week"
                    },
                    "query_count": {"$sum": 1}
                }},
                {"$sort": {"_id.hour": 1, "_id.day_of_week": 1}}
            ]

            cursor = collection.aggregate(pipeline)
            results = await cursor.to_list(length=None)

            # Process results into hourly patterns
            hourly_data = {}
            daily_patterns = {}

            for result in results:
                hour = result['_id']['hour']
                day_of_week = result['_id']['day_of_week']
                count = result['query_count']

                # Overall hourly average
                if hour not in hourly_data:
                    hourly_data[hour] = []
                hourly_data[hour].append(count)

                # Day of week patterns
                day_name = ["Sunday", "Monday", "Tuesday", "Wednesday",
                           "Thursday", "Friday", "Saturday"][day_of_week - 1]
                if day_name not in daily_patterns:
                    daily_patterns[day_name] = {}
                daily_patterns[day_name][hour] = count

            # Calculate averages
            hourly_averages = {
                hour: sum(counts) / len(counts) if counts else 0
                for hour, counts in hourly_data.items()
            }

            # Find peak hours
            sorted_hours = sorted(hourly_averages.items(), key=lambda x: x[1], reverse=True)
            peak_hours = [{'hour': hour, 'avg_queries': count}
                         for hour, count in sorted_hours[:5]]  # Top 5 peak hours

            return {
                'hourly_averages': hourly_averages,
                'daily_patterns': daily_patterns,
                'peak_hours': peak_hours,
                'total_queries': sum(hourly_averages.values()) * 24  # Rough estimate
            }

        except Exception as e:
            logger.error(f"Error in query volume by hour aggregation: {e}")
            return {}

    async def _get_basket_size_distribution(self, db: AsyncIOMotorDatabase,
                                          collection, cutoff_date: datetime) -> Dict[str, Any]:
        """
        Get distribution of basket sizes (number of products per query).

        Returns:
            Dictionary with basket size statistics and distribution
        """
        try:
            pipeline = [
                {"$match": {"timestamp": {"$gte": cutoff_date}}},
                {"$project": {
                    "basket_size": {"$size": {"$ifNull": ["$products", []]}}
                }},
                {"$group": {
                    "_id": "$basket_size",
                    "count": {"$sum": 1}
                }},
                {"$sort": {"_id": 1}}
            ]

            cursor = collection.aggregate(pipeline)
            results = await cursor.to_list(length=None)

            # Process results
            distribution = {}
            total_queries = 0
            total_products_in_baskets = 0

            for result in results:
                basket_size = result['_id']
                count = result['count']
                distribution[basket_size] = count
                total_queries += count
                total_products_in_baskets += basket_size * count

            # Calculate statistics
            avg_basket_size = (
                total_products_in_baskets / total_queries
                if total_queries > 0 else 0
            )

            # Categorize basket sizes
            small_baskets = sum(count for size, count in distribution.items() if size <= 2)
            medium_baskets = sum(count for size, count in distribution.items() if 3 <= size <= 5)
            large_baskets = sum(count for size, count in distribution.items() if size >= 6)

            return {
                'distribution': distribution,
                'total_queries': total_queries,
                'average_basket_size': round(avg_basket_size, 2),
                'basket_size_categories': {
                    'small_1_2_items': small_baskets,
                    'medium_3_5_items': medium_baskets,
                    'large_6_plus_items': large_baskets
                },
                'percentage_distribution': {
                    str(size): round((count / total_queries) * 100, 2)
                    for size, count in distribution.items()
                } if total_queries > 0 else {}
            }

        except Exception as e:
            logger.error(f"Error in basket size distribution aggregation: {e}")
            return {}

    async def _get_seasonal_patterns(self, db: AsyncIOMotorDatabase,
                                   collection, cutoff_date: datetime) -> Dict[str, Any]:
        """
        Get seasonal/weekly patterns in query volume.

        Returns:
            Dictionary with daily, weekly, and monthly patterns
        """
        try:
            pipeline = [
                {"$match": {"timestamp": {"$gte": cutoff_date}}},
                {"$project": {
                    "day_of_week": {"$dayOfWeek": "$timestamp"},
                    "week_of_year": {"$week": "$timestamp"},
                    "month": {"$month": "$timestamp"},
                    "day_of_month": {"$dayOfMonth": "$timestamp"}
                }},
                {"$group": {
                    "_id": {
                        "day_of_week": "$day_of_week",
                        "week_of_year": "$week_of_year",
                        "month": "$month"
                    },
                    "query_count": {"$sum": 1},
                    "unique_users": {"$addToSet": "$user_id"}  # Assuming user_id exists
                }},
                {"$sort": {"_id.year": 1, "_id.month": 1, "_id.day_of_week": 1}}
            ]

            # Note: We'll adjust for the actual date structure
            pipeline = [
                {"$match": {"timestamp": {"$gte": cutoff_date}}},
                {"$project": {
                    "day_of_week": {"$dayOfWeek": "$timestamp"},
                    "week_of_year": {"$week": "$timestamp"},
                    "month": {"$month": "$timestamp"}
                }},
                {"$group": {
                    "_id": {
                        "day_of_week": "$day_of_week",
                        "week_of_year": "$week_of_year",
                        "month": "$month"
                    },
                    "query_count": {"$sum": 1}
                }},
                {"$sort": {"_id.month": 1, "_id.week_of_year": 1, "_id.day_of_week": 1}}
            ]

            cursor = collection.aggregate(pipeline)
            results = await cursor.to_list(length=None)

            # Process results
            weekly_pattern = {}
            monthly_pattern = {}

            for result in results:
                day_of_week = result['_id']['day_of_week']
                week_of_year = result['_id']['week_of_year']
                month = result['_id']['month']
                count = result['query_count']

                day_name = ["Sunday", "Monday", "Tuesday", "Wednesday",
                           "Thursday", "Friday", "Saturday"][day_of_week - 1]

                # Weekly pattern (average by day of week)
                if day_name not in weekly_pattern:
                    weekly_pattern[day_name] = []
                weekly_pattern[day_name].append(count)

                # Monthly pattern
                month_name = ["January", "February", "March", "April", "May", "June",
                             "July", "August", "September", "October", "November", "December"][month - 1]
                if month_name not in monthly_pattern:
                    monthly_pattern[month_name] = []
                monthly_pattern[month_name].append(count)

            # Calculate averages
            weekly_avg = {
                day: sum(counts) / len(counts) if counts else 0
                for day, counts in weekly_pattern.items()
            }

            monthly_avg = {
                month: sum(counts) / len(counts) if counts else 0
                for month, counts in monthly_pattern.items()
            }

            return {
                'weekly_pattern': weekly_avg,
                'monthly_pattern': monthly_avg,
                'busiest_day': max(weekly_avg.items(), key=lambda x: x[1])[0] if weekly_avg else None,
                'quietest_day': min(weekly_avg.items(), key=lambda x: x[1])[0] if weekly_avg else None
            }

        except Exception as e:
            logger.error(f"Error in seasonal patterns aggregation: {e}")
            return {}

    async def _get_search_term_trends(self, db: AsyncIOMotorDatabase,
                                    collection, cutoff_date: datetime) -> Dict[str, Any]:
        """
        Get trending search terms and rising/falling queries.

        Returns:
            Dictionary with trending terms and momentum analysis
        """
        try:
            # Split the period into two halves to compare recent vs earlier trends
            midpoint = cutoff_date + (datetime.utcnow() - cutoff_date) / 2

            # First half (older)
            first_half_pipeline = [
                {"$match": {
                    "timestamp": {"$gte": cutoff_date, "$lt": midpoint}
                }},
                {"$unwind": "$products"},
                {"$lookup": {
                    "from": "products",
                    "localField": "products",
                    "foreignField": "_id",
                    "as": "product_info"
                }},
                {"$unwind": "$product_info"},
                {"$group": {
                    "_id": "$product_info.name",
                    "search_count": {"$sum": 1}
                }},
                {"$sort": {"search_count": -1}},
                {"$limit": 50}
            ]

            # Second half (recent)
            second_half_pipeline = [
                {"$match": {
                    "timestamp": {"$gte": midpoint, "$lt": datetime.utcnow()}
                }},
                {"$unwind": "$products"},
                {"$lookup": {
                    "from": "products",
                    "localField": "products",
                    "foreignField": "_id",
                    "as": "product_info"
                }},
                {"$unwind": "$product_info"},
                {"$group": {
                    "_id": "$product_info.name",
                    "search_count": {"$sum": 1}
                }},
                {"$sort": {"search_count": -1}},
                {"$limit": 50}
            ]

            # Execute both queries
            first_half_cursor = collection.aggregate(first_half_pipeline)
            second_half_cursor = collection.aggregate(second_half_pipeline)

            first_half_results = await first_half_cursor.to_list(length=None)
            second_half_results = await second_half_cursor.to_list(length=None)

            # Convert to dictionaries for easy comparison
            first_half_dict = {
                item['_id']: item['search_count']
                for item in first_half_results
            }

            second_half_dict = {
                item['_id']: item['search_count']
                for item in second_half_results
            }

            # Calculate growth rates
            trending_up = []  # Increasing searches
            trending_down = []  # Decreasing searches
            stable = []  # Stable searches

            all_terms = set(first_half_dict.keys()) | set(second_half_dict.keys())

            for term in all_terms:
                old_count = first_half_dict.get(term, 0)
                new_count = second_half_dict.get(term, 0)

                if old_count == 0 and new_count > 0:
                    # Newly appearing term
                    growth_rate = float('inf')
                elif old_count > 0:
                    growth_rate = (new_count - old_count) / old_count
                else:
                    growth_rate = 0

                if new_count >= 5:  # Minimum threshold for consideration
                    if growth_rate > 0.5:  # More than 50% increase
                        trending_up.append({
                            'search_term': term,
                            'previous_count': old_count,
                            'current_count': new_count,
                            'growth_rate': round(growth_rate, 2),
                            'absolute_change': new_count - old_count
                        })
                    elif growth_rate < -0.3:  # More than 30% decrease
                        trending_down.append({
                            'search_term': term,
                            'previous_count': old_count,
                            'current_count': new_count,
                            'growth_rate': round(growth_rate, 2),
                            'absolute_change': new_count - old_count
                        })
                    else:
                        stable.append({
                            'search_term': term,
                            'previous_count': old_count,
                            'current_count': new_count,
                            'growth_rate': round(growth_rate, 2),
                            'average_count': (old_count + new_count) / 2
                        })

            # Sort by magnitude of change
            trending_up.sort(key=lambda x: x['growth_rate'], reverse=True)
            trending_down.sort(key=lambda x: x['growth_rate'])
            stable.sort(key=lambda x: x['average_count'], reverse=True)

            return {
                'trending_up': trending_up[:20],  # Top 20 rising
                'trending_down': trending_down[:20],  # Top 20 falling
                'stable_high_volume': stable[:20],  # Top 20 stable high-volume
                'total_unique_terms': len(all_terms),
                'analysis_period': {
                    'first_half': f"{cutoff_date.strftime('%Y-%m-%d')} to {midpoint.strftime('%Y-%m-%d')}",
                    'second_half': f"{midpoint.strftime('%Y-%m-%d')} to {datetime.utcnow().strftime('%Y-%m-%d')}"
                }
            }

        except Exception as e:
            logger.error(f"Error in search term trends aggregation: {e}")
            return {}

    def get_cached_trends(self) -> Dict[str, Any]:
        """
        Get the last cached trends analysis.

        Returns:
            Dictionary with cached trend data or empty dict if none available
        """
        return self.trends_cache.copy() if self.trends_cache else {}

    def is_cache_fresh(self, max_age_hours: int = 24) -> bool:
        """
        Check if the cached trends are still fresh.

        Args:
            max_age_hours: Maximum age in hours before considering cache stale

        Returns:
            True if cache is fresh, False otherwise
        """
        if not self.last_updated:
            return False

        age_hours = (datetime.utcnow() - self.last_updated).total_seconds() / 3600
        return age_hours < max_age_hours


# Global trend aggregator instance
trend_aggregator = QueryTrendAggregator()


async def analyze_query_trends(db: AsyncIOMotorDatabase,
                             lookback_days: int = 7) -> Dict[str, Any]:
    """
    Analyze query trends from search logs.

    Args:
        db: MongoDB database connection
        lookback_days: Number of days of query logs to analyze

    Returns:
        Dictionary containing trend analysis results
    """
    global trend_aggregator
    return await trend_aggregator.aggregate_query_trends(db, lookback_days)


def get_cached_trend_analysis() -> Dict[str, Any]:
    """
    Get the last cached trend analysis.

    Returns:
        Dictionary with cached trend data
    """
    global trend_aggregator
    return trend_aggregator.get_cached_trends()


def is_trend_cache_fresh(max_age_hours: int = 24) -> bool:
    """
    Check if the trend cache is still fresh.

    Args:
        max_age_hours: Maximum age in hours before considering cache stale

    Returns:
        True if cache is fresh, False otherwise
    """
    global trend_aggregator
    return trend_aggregator.is_cache_fresh(max_age_hours)