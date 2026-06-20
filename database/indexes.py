"""
Index management for PricePoa database collections.
Handles creation and maintenance of database indexes for performance.
"""
from typing import List, Tuple, Dict, Any
from motor.motor_asyncio import AsyncIOMotorDatabase
import logging

from .models import PRODUCT_INDEXES, STORE_INDEXES, PRICE_INDEXES

logger = logging.getLogger(__name__)


async def create_collection_indexes(db: AsyncIOMotorDatabase) -> None:
    """
    Create all necessary indexes for PricePoa collections.
    Should be called during application startup or database initialization.
    """
    try:
        # Create indexes for products collection
        await _create_indexes_for_collection(
            db, "products", PRODUCT_INDEXES
        )
        logger.info("Created indexes for products collection")

        # Create indexes for stores collection
        await _create_indexes_for_collection(
            db, "stores", STORE_INDEXES
        )
        logger.info("Created indexes for stores collection")

        # Create indexes for prices collection
        await _create_indexes_for_collection(
            db, "prices", PRICE_INDEXES
        )
        logger.info("Created indexes for prices collection")

        # Create time series collection for prices if it doesn't exist
        await _create_price_time_series_collection(db)
        logger.info("Ensured price time series collection exists")

    except Exception as e:
        logger.error(f"Error creating database indexes: {e}")
        raise


async def _create_indexes_for_collection(
    db: AsyncIOMotorDatabase,
    collection_name: str,
    index_definitions: List[Tuple[List[Tuple[str, int]], Dict[str, Any]]]
) -> None:
    """
    Create indexes for a specific collection.

    Args:
        db: Motor database instance
        collection_name: Name of the collection
        index_definitions: List of (keys, options) tuples
    """
    collection = db[collection_name]

    # Get existing indexes to avoid recreating them
    existing_indexes = await collection.index_information()
    existing_index_names = set(existing_indexes.keys())

    for keys, options in index_definitions:
        # Generate index name from keys
        index_name = "_".join([f"{key}_{direction}" for key, direction in keys])

        # Skip if index already exists
        if index_name in existing_index_names:
            logger.debug(f"Index {index_name} already exists on {collection_name}")
            continue

        try:
            await collection.create_index(keys, **options)
            logger.debug(f"Created index {index_name} on {collection_name}")
        except Exception as e:
            logger.warning(f"Failed to create index {index_name} on {collection_name}: {e}")


async def _create_price_time_series_collection(db: AsyncIOMotorDatabase) -> None:
    """
    Create time series collection for efficient price history queries.
    Time series collections are optimized for storing data over time.
    """
    collection_name = "prices_timeseries"

    # Check if collection already exists
    collection_names = await db.list_collection_names()
    if collection_name in collection_names:
        logger.debug(f"Time series collection {collection_name} already exists")
        return

    try:
        # Create time series collection
        await db.create_collection(
            collection_name,
            timeseries={
                "timeField": "verified_at",
                "metaField": "product_store_id",  # Combination of product_id and store_id
                "granularity": "hours"  # Aggregate data by hour
            }
        )

        # Create indexes on the time series collection
        timeseries_db = db[collection_name]
        await timeseries_db.create_index([("product_store_id", 1)])
        await timeseries_db.create_index([("verified_at", -1)])

        logger.info(f"Created time series collection: {collection_name}")

    except Exception as e:
        # Time series collections require MongoDB 5.0+
        # Fall back to regular collection with indexes if time series not supported
        logger.warning(f"Could not create time series collection (may require MongoDB 5.0+): {e}")
        logger.info("Falling back to regular collection for price time series")

        # Create regular collection with appropriate indexes
        if collection_name not in await db.list_collection_names():
            await db.create_collection(collection_name)

        timeseries_db = db[collection_name]
        await timeseries_db.create_index([("product_store_id", 1), ("verified_at", -1)])
        await timeseries_db.create_index([("verified_at", -1)])


async def validate_indexes(db: AsyncIOMotorDatabase) -> Dict[str, Any]:
    """
    Validate that all expected indexes exist and return status.

    Returns:
        Dictionary with validation results for each collection
    """
    results = {}

    collections_to_check = [
        ("products", PRODUCT_INDEXES),
        ("stores", STORE_INDEXES),
        ("prices", PRICE_INDEXES)
    ]

    for collection_name, index_definitions in collections_to_check:
        try:
            collection = db[collection_name]
            existing_indexes = await collection.index_information()

            expected_count = len(index_definitions)
            actual_count = len([idx for idx in existing_indexes.keys() if idx != "_id_"])

            results[collection_name] = {
                "expected_indexes": expected_count,
                "actual_indexes": actual_count,
                "status": "ok" if actual_count >= expected_count else "missing_indexes",
                "missing": expected_count - actual_count if actual_count < expected_count else 0
            }

        except Exception as e:
            results[collection_name] = {
                "status": "error",
                "error": str(e)
            }

    return results


def get_index_definitions() -> Dict[str, List[Tuple[List[Tuple[str, int]], Dict[str, Any]]]]:
    """
    Get all index definitions for documentation or debugging purposes.

    Returns:
        Dictionary mapping collection names to their index definitions
    """
    return {
        "products": PRODUCT_INDEXES,
        "stores": STORE_INDEXES,
        "prices": PRICE_INDEXES
    }