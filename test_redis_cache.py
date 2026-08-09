"""
Test Redis caching functionality for PricePoa.
"""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.redis_cache import RedisCache, QUERY_UNDERSTANDING_PREFIX, SEARCH_RESULTS_PREFIX


@pytest.fixture
def redis_cache_instance():
    """Create a RedisCache instance for testing."""
    return RedisCache(redis_url="redis://localhost:6379/0", default_ttl=300)


@pytest.mark.asyncio
async def test_redis_cache_initialization():
    """Test Redis cache initialization."""
    cache = RedisCache()

    # Mock the redis connection
    with patch('redis.asyncio.from_url') as mock_from_url:
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock()
        mock_from_url.return_value = mock_redis

        await cache.initialize()

        assert cache._available == True
        assert cache._redis == mock_redis
        mock_redis.ping.assert_called_once()


@pytest.mark.asyncio
async def test_redis_cache_initialization_failure():
    """Test Redis cache initialization failure."""
    cache = RedisCache()

    # Mock the redis connection to raise an exception
    with patch('redis.asyncio.from_url') as mock_from_url:
        mock_from_url.side_effect = Exception("Connection failed")

        await cache.initialize()

        assert cache._available == False
        assert cache._redis is None


@pytest.mark.asyncio
async def test_redis_cache_get_set():
    """Test Redis cache get and set operations."""
    cache = RedisCache()

    # Mock the redis connection
    mock_redis = AsyncMock()
    cache._redis = mock_redis
    cache._available = True

    # Test set operation
    mock_redis.setex = AsyncMock(return_value=True)
    result = await cache.set("test_key", {"value": "test"}, ttl=60)
    assert result == True
    mock_redis.setex.assert_called_once_with("test_key", 60, '{"value": "test"}')

    # Test get operation (cache hit)
    mock_redis.get = AsyncMock(return_value='{"value": "test"}')
    result = await cache.get("test_key")
    assert result == {"value": "test"}
    mock_redis.get.assert_called_once_with("test_key")

    # Test get operation (cache miss)
    mock_redis.get = AsyncMock(return_value=None)
    result = await cache.get("nonexistent_key")
    assert result is None

    # Test get operation (invalid JSON)
    mock_redis.get = AsyncMock(return_value='invalid json')
    result = await cache.get("invalid_json_key")
    assert result == 'invalid json'


@pytest.mark.asyncio
async def test_redis_cache_delete():
    """Test Redis cache delete operation."""
    cache = RedisCache()

    # Mock the redis connection
    mock_redis = AsyncMock()
    cache._redis = mock_redis
    cache._available = True

    # Test delete operation
    mock_redis.delete = AsyncMock(return_value=1)
    result = await cache.delete("test_key")
    assert result == True
    mock_redis.delete.assert_called_once_with("test_key")

    # Test delete operation (key not found)
    mock_redis.delete = AsyncMock(return_value=0)
    result = await cache.delete("nonexistent_key")
    assert result == False


@pytest.mark.asyncio
async def test_redis_cache_unavailable():
    """Test Redis cache operations when unavailable."""
    cache = RedisCache()
    cache._available = False  # Simulate unavailable Redis

    # All operations should return False/None gracefully
    result = await cache.get("test_key")
    assert result is None

    result = await cache.set("test_key", "value")
    assert result == False

    result = await cache.delete("test_key")
    assert result == False


def test_make_query_understanding_key():
    """Test query understanding cache key generation."""
    from api.redis_cache import make_query_understanding_key

    normalized_query = "test query"
    parsed_query_dict = {"brand": "test", "category": "test"}

    key = make_query_understanding_key(normalized_query, parsed_query_dict)

    assert key.startswith(f"{QUERY_UNDERSTANDING_PREFIX}:")
    assert len(key) > len(QUERY_UNDERSTANDING_PREFIX) + 1  # colon + hash


def test_make_search_results_key():
    """Test search results cache key generation."""
    from api.redis_cache import make_search_results_key

    normalized_query = "test query"
    parsed_query_dict = {"brand": "test", "category": "test"}

    key = make_search_results_key(
        normalized_query=normalized_query,
        parsed_query_dict=parsed_query_dict,
        limit=10
    )

    assert key.startswith(f"{SEARCH_RESULTS_PREFIX}:")
    assert len(key) > len(SEARCH_RESULTS_PREFIX) + 1  # colon + hash


def test_make_product_key():
    """Test product cache key generation."""
    from api.redis_cache import make_product_key

    product_id = "test123"
    key = make_product_key(product_id)

    assert key == f"product:{product_id}"


def test_make_prices_key():
    """Test prices cache key generation."""
    from api.redis_cache import make_prices_key

    product_id = "test123"
    key = make_prices_key(product_id)

    assert key == f"prices:{product_id}"


if __name__ == "__main__":
    # Run the tests
    pytest.main([__file__, "-v"])