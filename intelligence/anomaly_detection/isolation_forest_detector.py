"""
Isolation Forest based anomaly detection for price anomalies.
Detects statistically anomalous prices before they are written to the database.
"""
import numpy as np
import logging
from typing import List, Dict, Any, Tuple, Optional
from datetime import datetime
from sklearn.ensemble import IsolationForest
import joblib
import os
from motor.motor_asyncio import AsyncIOMotorDatabase

logger = logging.getLogger(__name__)


class PriceAnomalyDetector:
    """
    Isolation Forest based anomaly detector for price data.
    Trained on historical price data to detect outliers.
    """

    def __init__(self, contamination: float = 0.05, n_estimators: int = 100):
        """
        Initialize the anomaly detector.

        Args:
            contamination: Expected proportion of outliers in the data (default: 5%)
            n_estimators: Number of base estimators in the ensemble
        """
        self.contamination = contamination
        self.n_estimators = n_estimators
        self.model = IsolationForest(
            contamination=contamination,
            n_estimators=n_estimators,
            random_state=42,
            n_jobs=-1
        )
        self.is_trained = False
        self.feature_names = ['price_kes', 'log_price']  # Features we use for detection
        self.model_path = None

    def _prepare_features(self, price_data: List[Dict[str, Any]]) -> np.ndarray:
        """
        Extract and prepare features from price data for anomaly detection.

        Args:
            price_data: List of price dictionaries with at least 'price_kes' field

        Returns:
            Numpy array of features for ML model
        """
        if not price_data:
            return np.array([]).reshape(0, 2)

        prices = []
        for item in price_data:
            price = float(item.get('price_kes', 0))
            if price <= 0:
                # Skip invalid prices
                continue
            prices.append(price)

        if not prices:
            return np.array([]).reshape(0, 2)

        prices_array = np.array(prices).reshape(-1, 1)

        # Features: raw price and log(price) to handle skew
        log_prices = np.log(prices_array + 1e-8)  # Add small epsilon to avoid log(0)
        features = np.hstack([prices_array, log_prices])

        return features

    async def train(self, db: AsyncIOMotorDatabase, lookback_days: int = 30) -> bool:
        """
        Train the isolation forest model on historical price data.

        Args:
            db: MongoDB database connection
            lookback_days: Number of days of historical data to use for training

        Returns:
            True if training successful, False otherwise
        """
        try:
            logger.info(f"Training anomaly detection model on last {lookback_days} days of price data")

            # Get historical price data
            from datetime import datetime, timedelta
            cutoff_date = datetime.utcnow() - timedelta(days=lookback_days)

            prices_collection = db.prices
            cursor = prices_collection.find(
                {"verified_at": {"$gte": cutoff_date}},
                {"price_kes": 1, "_id": 0}
            )

            price_data = await cursor.to_list(length=None)

            if len(price_data) < 50:
                logger.warning(f"Insufficient data for training: {len(price_data)} samples")
                return False

            # Prepare features
            features = self._prepare_features(price_data)

            if features.shape[0] < 10:
                logger.warning("Insufficient valid price data after preprocessing")
                return False

            # Train the model
            self.model.fit(features)
            self.is_trained = True

            logger.info(f"Anomaly detection model trained successfully on {features.shape[0]} samples")
            return True

        except Exception as e:
            logger.error(f"Error training anomaly detection model: {e}")
            return False

    def predict_anomaly(self, price_data: List[Dict[str, Any]]) -> List[bool]:
        """
        Predict whether each price point is an anomaly.

        Args:
            price_data: List of price dictionaries to check

        Returns:
            List of booleans where True indicates anomaly
        """
        if not self.is_trained:
            logger.warning("Model not trained yet, returning all False (no anomalies)")
            return [False] * len(price_data)

        if not price_data:
            return []

        try:
            features = self._prepare_features(price_data)

            if features.shape[0] == 0:
                return [False] * len(price_data)

            # IsolationForest returns -1 for anomalies, 1 for normal
            predictions = self.model.predict(features)
            # Convert to boolean: True for anomaly (-1), False for normal (1)
            return (predictions == -1).tolist()

        except Exception as e:
            logger.error(f"Error predicting anomalies: {e}")
            return [False] * len(price_data)

    def predict_anomaly_score(self, price_data: List[Dict[str, Any]]) -> List[float]:
        """
        Get anomaly scores for price points (lower = more anomalous).

        Args:
            price_data: List of price dictionaries to score

        Returns:
            List of anomaly scores
        """
        if not self.is_trained:
            logger.warning("Model not trained yet, returning neutral scores (0.5)")
            return [0.5] * len(price_data)

        if not price_data:
            return []

        try:
            features = self._prepare_features(price_data)

            if features.shape[0] == 0:
                return [0.5] * len(price_data)

            # IsolationForest decision_function: lower values = more anomalous
            scores = self.model.decision_function(features)
            # Convert to 0-1 range where 0 = most anomalous, 1 = least anomalous
            # Using sigmoid-like transformation for interpretability
            normalized_scores = 1 / (1 + np.exp(-scores))
            return normalized_scores.tolist()

        except Exception as e:
            logger.error(f"Error predicting anomaly scores: {e}")
            return [0.5] * len(price_data)

    async def save_model(self, db: AsyncIOMotorDatabase, model_id: str = "price_anomaly_detector") -> bool:
        """
        Save the trained model to MongoDB GridFS or filesystem.

        Args:
            db: MongoDB database connection
            model_id: Identifier for the model

        Returns:
            True if model saved successfully, False otherwise
        """
        if not self.is_trained:
            logger.warning("Cannot save untrained model")
            return False

        try:
            # For simplicity, we'll save to filesystem. In production, consider GridFS.
            model_dir = "/app/models/anomaly_detection"
            os.makedirs(model_dir, exist_ok=True)
            self.model_path = os.path.join(model_dir, f"{model_id}.joblib")

            joblib.dump(self.model, self.model_path)
            logger.info(f"Anomaly detection model saved to {self.model_path}")
            return True

        except Exception as e:
            logger.error(f"Error saving anomaly detection model: {e}")
            return False

    async def load_model(self, db: AsyncIOMotorDatabase, model_id: str = "price_anomaly_detector") -> bool:
        """
        Load a previously trained model.

        Args:
            db: MongoDB database connection
            model_id: Identifier for the model

        Returns:
            True if model loaded successfully, False otherwise
        """
        try:
            model_dir = "/app/models/anomaly_detection"
            model_path = os.path.join(model_dir, f"{model_id}.joblib")

            if os.path.exists(model_path):
                self.model = joblib.load(model_path)
                self.is_trained = True
                self.model_path = model_path
                logger.info(f"Anomaly detection model loaded from {model_path}")
                return True
            else:
                logger.warning(f"No saved model found at {model_path}")
                return False

        except Exception as e:
            logger.error(f"Error loading anomaly detection model: {e}")
            return False


# Global detector instance
anomaly_detector = PriceAnomalyDetector()


async def check_price_anomalies(db: AsyncIOMotorDatabase, price_records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Check a batch of price records for anomalies and flag them.

    Args:
        db: MongoDB database connection
        price_records: List of price records to check

    Returns:
        List of price records with anomaly flags added
    """
    global anomaly_detector

    # Ensure model is trained
    if not anomaly_detector.is_trained:
        await anomaly_detector.train(db)

    # Get anomaly predictions
    is_anomaly = anomaly_detector.predict_anomaly(price_records)
    anomaly_scores = anomaly_detector.predict_anomaly_score(price_records)

    # Flag anomalies in the records
    flagged_records = []
    for i, record in enumerate(price_records):
        record_copy = record.copy()
        record_copy['is_anomaly'] = bool(is_anomaly[i])
        record_copy['anomaly_score'] = float(anomaly_scores[i])
        flagged_records.append(record_copy)

    # Log any anomalies found
    for record in flagged_records:
        if record['is_anomaly']:
            logger.warning(
                f"Price anomaly detected: "
                f"product_id={record.get('product_id')}, "
                f"store_id={record.get('store_id')}, "
                f"price={record.get('price_kes')} KES, "
                f"score={record['anomaly_score']:.3f}"
            )

    return flagged_records