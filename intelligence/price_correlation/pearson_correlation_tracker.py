"""
Price correlation tracking system using Pearson correlation.
Tracks price correlations between same products across different stores over time.
"""
import numpy as np
import pandas as pd
import logging
from typing import List, Dict, Any, Tuple, Optional
from datetime import datetime, timedelta
from motor.motor_asyncio import AsyncIOMotorDatabase
import asyncio
from collections import defaultdict

logger = logging.getLogger(__name__)


class PriceCorrelationTracker:
    """
    Tracks price correlations between same products across different stores.
    Uses Pearson correlation to identify pricing leadership and follow patterns.
    """

    def __init__(self, min_data_points: int = 10):
        """
        Initialize the price correlation tracker.

        Args:
            min_data_points: Minimum number of data points required for correlation calculation
        """
        self.min_data_points = min_data_points
        self.price_data = {}  # product_id -> {store_id -> [timestamps, prices]}
        self.correlations = {}  # (product_id, store1_id, store2_id) -> correlation_data
        self.last_updated = None

    def _prepare_price_series(self, price_records: List[Dict[str, Any]]) -> Dict[str, Dict[str, List]]:
        """
        Organize price data by product and store for time series analysis.

        Args:
            price_records: List of price records from database

        Returns:
            Dictionary mapping product_id -> store_id -> {'timestamps': [...], 'prices': [...]}
        """
        organized_data = defaultdict(lambda: defaultdict(lambda: {'timestamps': [], 'prices': []}))

        for record in price_records:
            product_id = str(record.get('product_id'))
            store_id = str(record.get('store_id'))
            price = float(record.get('price_kes', 0))
            timestamp = record.get('verified_at')

            if price <= 0 or not timestamp:
                continue

            # Convert datetime to timestamp if needed
            if isinstance(timestamp, datetime):
                timestamp_val = timestamp.timestamp()
            else:
                # Assume it's already a timestamp or can be converted
                try:
                    timestamp_val = float(timestamp)
                except:
                    continue

            organized_data[product_id][store_id]['timestamps'].append(timestamp_val)
            organized_data[product_id][store_id]['prices'].append(price)

        # Sort each series by timestamp
        for product_id in organized_data:
            for store_id in organized_data[product_id]:
                # Combine and sort by timestamp
                combined = list(zip(organized_data[product_id][store_id]['timestamps'],
                                  organized_data[product_id][store_id]['prices']))
                combined.sort(key=lambda x: x[0])  # Sort by timestamp

                if combined:
                    timestamps, prices = zip(*combined)
                    organized_data[product_id][store_id]['timestamps'] = list(timestamps)
                    organized_data[product_id][store_id]['prices'] = list(prices)

        return organized_data

    def calculate_pearson_correlation(self, prices1: List[float], prices2: List[float]) -> Optional[float]:
        """
        Calculate Pearson correlation coefficient between two price series.

        Args:
            prices1: First price series
            prices2: Second price series

        Returns:
            Pearson correlation coefficient or None if insufficient data
        """
        if len(prices1) < self.min_data_points or len(prices2) < self.min_data_points:
            return None

        if len(prices1) != len(prices2):
            # Need to align the series by date/interpolation
            # For simplicity, we'll use the minimum length
            min_len = min(len(prices1), len(prices2))
            prices1 = prices1[-min_len:]
            prices2 = prices2[-min_len:]

        try:
            correlation = np.corrcoef(prices1, prices2)[0, 1]
            # Handle case where correlation is NaN (e.g., constant values)
            if np.isnan(correlation):
                return 0.0
            return float(correlation)
        except Exception as e:
            logger.warning(f"Error calculating Pearson correlation: {e}")
            return None

    def detect_lead_lag_relationship(self, prices1: List[float], prices2: List[float],
                                   timestamps1: List[float], timestamps2: List[float],
                                   max_lag_days: int = 5) -> Tuple[Optional[int], Optional[float]]:
        """
        Detect lead-lag relationship between two price series using cross-correlation.

        Args:
            prices1: First price series (potential leader)
            prices2: Second price series (potential follower)
            timestamps1: Timestamps for first series
            timestamps2: Timestamps for second series
            max_lag_days: Maximum lag to check in days

        Returns:
            Tuple of (lag_days, correlation_at_lag) or (None, None) if insufficient data
        """
        if len(prices1) < self.min_data_points or len(prices2) < self.min_data_points:
            return None, None

        # Convert timestamps to days for easier interpretation
        if not timestamps1 or not timestamps2:
            return None, None

        # For simplicity in this implementation, we'll assume regular intervals
        # A more sophisticated approach would use interpolation
        max_lag_points = min(len(prices1)//2, len(prices2)//2, 10)  # Limit lag search

        best_lag = 0
        best_correlation = -1

        for lag in range(-max_lag_points, max_lag_points + 1):
            if lag == 0:
                # No lag case
                corr = self.calculate_pearson_correlation(prices1, prices2)
                if corr is not None and abs(corr) > abs(best_correlation):
                    best_correlation = corr
                    best_lag = 0
            elif lag > 0:
                # prices1 leads prices2 by lag periods
                if len(prices1) > lag and len(prices2) > lag:
                    corr = self.calculate_pearson_correlation(prices1[:-lag], prices2[lag:])
                    if corr is not None and abs(corr) > abs(best_correlation):
                        best_correlation = corr
                        best_lag = lag
            else:  # lag < 0
                # prices2 leads prices1 by |lag| periods
                abs_lag = abs(lag)
                if len(prices1) > abs_lag and len(prices2) > abs_lag:
                    corr = self.calculate_pearson_correlation(prices1[abs_lag:], prices2[:-abs_lag])
                    if corr is not None and abs(corr) > abs(best_correlation):
                        best_correlation = corr
                        best_lag = lag

        if best_correlation is None or abs(best_correlation) < 0.1:  # Weak correlation threshold
            return None, None

        # Convert lag in points to approximate days (assuming daily data)
        # This is a simplification - in practice we'd use actual timestamps
        lag_days = best_lag  # Assuming daily data points
        return lag_days, best_correlation

    async def update_correlations(self, db: AsyncIOMotorDatabase,
                                lookback_days: int = 30) -> bool:
        """
        Update price correlations based on recent price data.

        Args:
            db: MongoDB database connection
            lookback_days: Number of days of historical data to use

        Returns:
            True if update successful, False otherwise
        """
        try:
            logger.info(f"Updating price correlations for last {lookback_days} days")

            # Get recent price data
            cutoff_date = datetime.utcnow() - timedelta(days=lookback_days)

            prices_collection = db.prices
            cursor = prices_collection.find(
                {"verified_at": {"$gte": cutoff_date}},
                {
                    "product_id": 1,
                    "store_id": 1,
                    "price_kes": 1,
                    "verified_at": 1,
                    "_id": 0
                }
            ).sort("verified_at", 1)  # Sort by time ascending

            price_records = await cursor.to_list(length=None)

            if len(price_records) < self.min_data_points * 2:  # Need reasonable amount of data
                logger.warning(f"Insufficient price data for correlation analysis: {len(price_records)} records")
                return False

            # Organize data by product and store
            organized_data = self._prepare_price_series(price_records)

            # Calculate correlations for each product pair
            new_correlations = {}

            for product_id, store_data in organized_data.items():
                store_ids = list(store_data.keys())

                # Need at least 2 stores to compare
                if len(store_ids) < 2:
                    continue

                # Compare each pair of stores
                for i, store1_id in enumerate(store_ids):
                    for store2_id in store_ids[i+1:]:
                        # Get price series for both stores
                        data1 = store_data[store1_id]
                        data2 = store_data[store2_id]

                        if len(data1['prices']) < self.min_data_points or len(data2['prices']) < self.min_data_points:
                            continue

                        # Calculate Pearson correlation
                        correlation = self.calculate_pearson_correlation(
                            data1['prices'], data2['prices']
                        )

                        if correlation is None:
                            continue

                        # Detect lead-lag relationship with recursion protection
                        try:
                            lag_days, lag_correlation = self.detect_lead_lag_relationship(
                                data1['prices'], data2['prices'],
                                data1['timestamps'], data2['timestamps']
                            )
                        except RecursionError:
                            logger.warning(f"Recursion error in detect_lead_lag_relationship for product {product_id}, stores {store1_id}-{store2_id}")
                            lag_days, lag_correlation = None, None

                        # Store correlation data
                        correlation_key = (product_id, store1_id, store2_id)
                        reverse_key = (product_id, store2_id, store1_id)

                        correlation_data = {
                            'product_id': product_id,
                            'store_a_id': store1_id,
                            'store_b_id': store2_id,
                            'pearson_correlation': correlation,
                            'lead_lag_days': lag_days,
                            'lag_correlation': lag_correlation,
                            'data_points_a': len(data1['prices']),
                            'data_points_b': len(data2['prices']),
                            'date_range_start': min(min(data1['timestamps']), min(data2['timestamps'])),
                            'date_range_end': max(max(data1['timestamps']), max(data2['timestamps'])),
                            'last_updated': datetime.utcnow()
                        }

                        new_correlations[correlation_key] = correlation_data
                        # Also store reverse relationship (negative lag)
                        if lag_days is not None:
                            reverse_data = correlation_data.copy()
                            reverse_data['store_a_id'] = store2_id
                            reverse_data['store_b_id'] = store1_id
                            reverse_data['lead_lag_days'] = -lag_days
                            new_correlations[reverse_key] = reverse_data

            self.correlations = new_correlations
            self.last_updated = datetime.utcnow()
            self.price_data = organized_data  # Keep for potential further analysis

            logger.info(f"Updated correlations for {len(new_correlations)} product-store pairs")
            return True

        except Exception as e:
            logger.error(f"Error updating price correlations: {e}")
            return False

    def get_product_correlations(self, product_id: str) -> List[Dict[str, Any]]:
        """
        Get all correlation data for a specific product.

        Args:
            product_id: ID of the product

        Returns:
            List of correlation dictionaries for the product
        """
        result = []
        for (pid, store1_id, store2_id), corr_data in self.correlations.items():
            if pid == product_id:
                result.append(corr_data)
        return result

    def get_store_pair_correlation(self, product_id: str, store1_id: str, store2_id: str) -> Optional[Dict[str, Any]]:
        """
        Get correlation data for a specific product and store pair.

        Args:
            product_id: ID of the product
            store1_id: ID of the first store
            store2_id: ID of the second store

        Returns:
            Correlation dictionary or None if not found
        """
        key = (product_id, store1_id, store2_id)
        return self.correlations.get(key)

    def get_leader_follower_relationships(self, product_id: str) -> List[Dict[str, Any]]:
        """
        Get identified leader-follower relationships for a product.

        Args:
            product_id: ID of the product

        Returns:
            List of dictionaries describing leader-follower relationships
        """
        relationships = []
        product_correlations = self.get_product_correlations(product_id)

        for corr_data in product_correlations:
            lag_days = corr_data.get('lead_lag_days')
            lag_correlation = corr_data.get('lag_correlation')

            # Look for significant lead-lag relationships
            if lag_days is not None and lag_correlation is not None:
                # Consider it a leadership relationship if:
                # 1. Lag correlation is significantly higher than zero-lag correlation
                # 2. Absolute lag correlation > 0.3 (moderate correlation)
                # 3. Lag is non-zero (one leads the other)
                zero_lag_corr = corr_data.get('pearson_correlation', 0)
                if (abs(lag_correlation) > abs(zero_lag_corr) + 0.1 and
                    abs(lag_correlation) > 0.3 and
                    lag_days != 0):

                    leader_store = corr_data['store_b_id'] if lag_days > 0 else corr_data['store_a_id']
                    follower_store = corr_data['store_a_id'] if lag_days > 0 else corr_data['store_b_id']
                    abs_lag = abs(lag_days)

                    relationships.append({
                        'product_id': product_id,
                        'leader_store': leader_store,
                        'follower_store': follower_store,
                        'lag_days': abs_lag,
                        'confidence': abs(lag_correlation),
                        'zero_lag_correlation': zero_lag_corr,
                        'lag_correlation': lag_correlation
                    })

        return relationships


# Global correlation tracker instance
correlation_tracker = PriceCorrelationTracker()


async def update_price_correlations(db: AsyncIOMotorDatabase,
                                  lookback_days: int = 30) -> bool:
    """
    Update price correlations based on recent price data.

    Args:
        db: MongoDB database connection
        lookback_days: Number of days of historical data to use

    Returns:
        True if update successful, False otherwise
    """
    global correlation_tracker
    return await correlation_tracker.update_correlations(db, lookback_days)


def get_product_correlations(product_id: str) -> List[Dict[str, Any]]:
    """
    Get all correlation data for a specific product.

    Args:
        product_id: ID of the product

    Returns:
        List of correlation dictionaries for the product
    """
    global correlation_tracker
    return correlation_tracker.get_product_correlations(product_id)


def get_store_pair_correlation(product_id: str, store1_id: str, store2_id: str) -> Optional[Dict[str, Any]]:
    """
    Get correlation data for a specific product and store pair.

    Args:
        product_id: ID of the product
        store1_id: ID of the first store
        store2_id: ID of the second store

    Returns:
        Correlation dictionary or None if not found
    """
    global correlation_tracker
    return correlation_tracker.get_store_pair_correlation(product_id, store1_id, store2_id)


def get_leader_follower_relationships(product_id: str) -> List[Dict[str, Any]]:
    """
    Get identified leader-follower relationships for a product.

    Args:
        product_id: ID of the product

    Returns:
        List of dictionaries describing leader-follower relationships
    """
    global correlation_tracker
    return correlation_tracker.get_leader_follower_relationships(product_id)