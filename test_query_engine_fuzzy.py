#!/usr/bin/env python3
"""
Test script to verify that the query_engine.py modifications work correctly
with the fuzzy matching from product_matcher module.
"""

import asyncio
import sys
import os
from unittest.mock import Mock, AsyncMock, patch

# Add the project root to the path so we can import modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

async def test_query_engine_fuzzy_matching():
    """Test that query_engine uses fuzzy matching correctly"""

    # Import the module we modified
    from api.query_engine import find_product, get_product_prices, query_single_product

    # Create a mock database
    mock_db = Mock()
    mock_products = Mock()
    mock_prices = Mock()
    mock_stores = Mock()

    mock_db.products = mock_products
    mock_db.prices = mock_prices
    mock_db.stores = mock_stores

    # Mock product data
    mock_product = {
        "_id": "product123",
        "name": "Unga",
        "category": "Grains",
        "swahili_aliases": ["unga"],
        "sheng_aliases": ["mother"]
    }

    # Mock price data
    mock_price = {
        "_id": "price123",
        "product_id": "product123",
        "store_id": "store123",
        "price_kes": 120.50,
        "source": "test",
        "verified_at": "2026-07-30T10:00:00Z",
        "is_promotional": False
    }

    # Mock store data
    mock_store = {
        "_id": "store123",
        "chain_name": "Test Store",
        "branch_name": "Main Branch",
        "town": "Nairobi",
        "county": "Nairobi"
    }

    # Configure the mocks
    mock_products.find_one = AsyncMock()
    mock_prices.find = AsyncMock()
    mock_stores.find = AsyncMock()

    # Test Case 1: Exact match should work
    print("Testing exact match...")
    mock_products.find_one.return_value = mock_product
    mock_prices.find.return_value.to_list = AsyncMock(return_value=[mock_price])
    mock_stores.find.return_value.to_list = AsyncMock(return_value=[mock_store])

    result = await find_product(mock_db, "Unga")
    assert result is not None
    assert result["name"] == "Unga"
    print("✓ Exact match works")

    # Test Case 2: Fuzzy match should work (simulating typo)
    print("Testing fuzzy match with typo...")
    # For this test, we'll mock the find_product_enhanced function directly
    with patch('api.query_engine.find_product_enhanced') as mock_fuzzy:
        mock_fuzzy.return_value = mock_product
        mock_prices.find.return_value.to_list = AsyncMock(return_value=[mock_price])
        mock_stores.find.return_value.to_list = AsyncMock(return_value=[mock_store])

        result = await find_product(mock_db, "unga")  # lowercase - should still match via fuzzy
        assert result is not None
        assert result["name"] == "Unga"
        mock_fuzzy.assert_called_once_with(mock_db, "unga")
        print("✓ Fuzzy match works")

    # Test Case 3: Empty query should return None
    print("Testing empty query...")
    result = await find_product(mock_db, "")
    assert result is None
    print("✓ Empty query returns None")

    # Test Case 4: Whitespace only query should return None
    print("Testing whitespace-only query...")
    result = await find_product(mock_db, "   ")
    assert result is None
    print("✓ Whitespace-only query returns None")

    # Test Case 5: Query with town filter
    print("Testing query with town filter...")
    mock_products.find_one.return_value = mock_product
    mock_prices.find.return_value.to_list = AsyncMock(return_value=[mock_price])
    mock_stores.find.return_value.to_list = AsyncMock(return_value=[mock_store])

    result = await query_single_product(mock_db, "Unga", town="Nairobi")
    assert result is not None
    assert result["product_name"] == "Unga"
    assert len(result["stores"]) == 1
    assert result["stores"][0]["name"] == "Test Store - Main Branch"
    print("✓ Query with town filter works")

    print("\n✅ All tests passed! The query_engine correctly uses fuzzy matching.")

if __name__ == "__main__":
    asyncio.run(test_query_engine_fuzzy_matching())