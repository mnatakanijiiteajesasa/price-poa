"""
Test script for PricePoa Phase 1 implementation.
Verifies database connection, seed data loading, and basic operations.
"""
import asyncio
import logging
import sys
import os

# Add project root to path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)
sys.path.insert(0, os.path.dirname(current_dir))

from database.connection import get_database
from database.seed_data import load_products_from_json, load_stores_from_json, seed_database
from database.indexes import create_collection_indexes, validate_indexes

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


async def test_database_connection():
    """Test MongoDB connection."""
    logger.info("Testing MongoDB connection...")
    try:
        db = await get_database()
        # Test ping
        await db.client.admin.command('ping')
        logger.info("✓ MongoDB connection successful")
        return db
    except Exception as e:
        logger.error(f"✗ MongoDB connection failed: {e}")
        return None


async def test_seed_loading():
    """Test loading seed data."""
    logger.info("Testing seed data loading...")
    try:
        # Test products seeding
        products_file = "database/seeds/products_seed.json"
        product_count = await load_products_from_json(products_file)
        logger.info(f"✓ Loaded {product_count} products")

        # Test stores seeding
        stores_file = "database/seeds/stores_seed.json"
        store_count = await load_stores_from_json(stores_file)
        logger.info(f"✓ Loaded {store_count} stores")

        return product_count > 0 and store_count > 0
    except Exception as e:
        logger.error(f"✗ Seed data loading failed: {e}")
        return False


async def test_index_creation():
    """Test index creation."""
    logger.info("Testing index creation...")
    try:
        db = await get_database()
        await create_collection_indexes(db)
        logger.info("✓ Indexes created successfully")

        # Validate indexes
        validation_results = await validate_indexes(db)
        logger.info(f"Index validation results: {validation_results}")

        # Check that we have indexes
        total_indexes = sum(
            result.get('actual_indexes', 0)
            for result in validation_results.values()
            if isinstance(result, dict) and 'actual_indexes' in result
        )
        logger.info(f"Total indexes created: {total_indexes}")
        return total_indexes > 0
    except Exception as e:
        logger.error(f"✗ Index creation failed: {e}")
        return False


async def test_basic_queries():
    """Test basic database queries."""
    logger.info("Testing basic queries...")
    try:
        db = await get_database()

        # Count documents
        products_count = await db.products.count_documents({})
        stores_count = await db.stores.count_documents({})
        prices_count = await db.prices.count_documents({})

        logger.info(f"Document counts - Products: {products_count}, Stores: {stores_count}, Prices: {prices_count}")

        # Test finding a product
        sample_product = await db.products.find_one(
            {"name": "Maize Flour (Unga)"},
            {"_id": 0, "name": 1, "category": 1, "brand": 1}
        )
        if sample_product:
            logger.info(f"✓ Found sample product: {sample_product}")
        else:
            logger.warning("⚠ Sample product not found")

        # Test finding stores in Nairobi
        nairobi_stores = await db.stores.count_documents({"town": "Nairobi"})
        logger.info(f"✓ Found {nairobi_stores} stores in Nairobi")

        # Test finding stores in Nyeri
        nyeri_stores = await db.stores.count_documents({"town": "Nyeri"})
        logger.info(f"✓ Found {nyeri_stores} stores in Nyeri")

        return products_count > 0 and stores_count > 0
    except Exception as e:
        logger.error(f"✗ Basic queries failed: {e}")
        return False


async def run_all_tests():
    """Run all tests."""
    logger.info("Starting PricePoa Phase 1 implementation tests...")
    logger.info("=" * 50)

    tests = [
        ("Database Connection", test_database_connection),
        ("Seed Data Loading", test_seed_loading),
        ("Index Creation", test_index_creation),
        ("Basic Queries", test_basic_queries)
    ]

    results = {}

    for test_name, test_func in tests:
        logger.info(f"\nRunning test: {test_name}")
        try:
            if test_name == "Database Connection":
                result = await test_func()
                results[test_name] = result is not None
            else:
                result = await test_func()
                results[test_name] = bool(result)
        except Exception as e:
            logger.error(f"Test {test_name} failed with exception: {e}")
            results[test_name] = False

    # Summary
    logger.info("\n" + "=" * 50)
    logger.info("TEST RESULTS SUMMARY:")
    logger.info("=" * 50)

    passed = 0
    total = len(tests)

    for test_name, result in results.items():
        status = "PASS" if result else "FAIL"
        logger.info(f"{test_name:<25} {status}")
        if result:
            passed += 1

    logger.info("-" * 50)
    logger.info(f"TOTAL: {passed}/{total} tests passed")

    if passed == total:
        logger.info("🎉 All tests passed!")
        return True
    else:
        logger.error(f"❌ {total - passed} test(s) failed")
        return False


def main():
    """Main entry point."""
    try:
        result = asyncio.run(run_all_tests())
        sys.exit(0 if result else 1)
    except KeyboardInterrupt:
        logger.info("\nTests interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()