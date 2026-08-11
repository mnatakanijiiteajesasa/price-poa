"""
Redis caching layer for PricePoa search system.
Provides caching for query understanding and search results with proper error handling.
"""
import json
import hashlib
import logging
from typing import Any, Optional, Union
import redis.asyncio as redis
from redis.exceptions import RedisError, ConnectionError as RedisConnectionError

logger = logging.getLogger("uvicorn.error")

class RedisCache:
    """Redis cache wrapper with graceful fallback and serialization."""

    def __init__(self, redis_url: str = None, default_ttl: int = 300):
        """
        Initialize Redis cache.

        Args:
            redis_url: Redis connection URL (defaults to REDIS_URL env var or localhost)
            default_ttl: Default time-to-live for cache entries in seconds
        """
        self.redis_url = redis_url or "redis://localhost:6379/0"
        self.default_ttl = default_ttl
        self._redis: Optional[redis.Redis] = None
        self._available = False

    async def initialize(self):
        """Initialize Redis connection."""
        try:
            self._redis = redis.from_url(self.redis_url, encoding="utf-8", decode_responses=True)
            # Test connection
            await self._redis.ping()
            self._available = True
            logger.info(f"Redis cache initialized successfully: {self.redis_url}")
        except (RedisConnectionError, RedisError) as e:
            logger.warning(f"Failed to initialize Redis cache: {e}. Caching disabled.")
            self._available = False
            self._redis = None
        except Exception as e:
            logger.warning(f"Unexpected error initializing Redis cache: {e}. Caching disabled.")
            self._available = False
            self._redis = None

    async def close(self):
        """Close Redis connection."""
        if self._redis:
            await self._redis.close()
            self._redis = None
            self._available = False

    def _is_available(self) -> bool:
        """Check if Redis is available."""
        return self._available and self._redis is not None

    def _make_key(self, prefix: str, identifier: str) -> str:
        """
        Create a namespaced cache key.

        Args:
            prefix: Key prefix (e.g., 'query:understanding')
            identifier: Unique identifier for the cached item

        Returns:
            Formatted cache key
        """
        return f"{prefix}:{identifier}"

    def _hash_key(self, data: dict) -> str:
        """
        Create a deterministic hash from dictionary data.

        Args:
            data: Dictionary to hash

        Returns:
            SHA-256 hex digest
        """
        # Sort keys for deterministic JSON serialization
        sorted_data = json.dumps(data, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(sorted_data.encode('utf-8')).hexdigest()

    async def get(self, key: str) -> Optional[Any]:
        """
        Get value from cache.

        Args:
            key: Cache key

        Returns:
            Cached value if found and valid, None otherwise
        """
        if not self._is_available():
            return None

        try:
            value = await self._redis.get(key)
            if value is None:
                logger.debug(f"Cache miss: {key}")
                return None

            # Try to deserialize JSON
            try:
                parsed_value = json.loads(value)
                logger.debug(f"Cache hit (deserialized): {key}")
                return parsed_value
            except json.JSONDecodeError:
                # Return raw string if not JSON
                logger.debug(f"Cache hit (raw string): {key}")
                return value

        except RedisError as e:
            logger.warning(f"Redis GET error for key {key}: {e}")
            return None
        except Exception as e:
            logger.warning(f"Unexpected error getting cache key {key}: {e}")
            return None

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """
        Set value in cache.

        Args:
            key: Cache key
            value: Value to cache (will be JSON serialized if possible)
            ttl: Time-to-live in seconds (uses default if not provided)

        Returns:
            True if successful, False otherwise
        """
        if not self._is_available():
            return False

        try:
            # Serialize value
            if isinstance(value, (str, int, float, bool)) or value is None:
                # Simple types can be stored as-is
                serialized_value = json.dumps(value)
            else:
                # Complex objects get JSON serialized
                serialized_value = json.dumps(value, default=str)

            # Set expiration
            expire_time = ttl if ttl is not None else self.default_ttl
            result = await self._redis.setex(key, expire_time, serialized_value)

            if result:
                logger.debug(f"Cache set: {key} (TTL: {expire_time}s)")
            else:
                logger.warning(f"Failed to set cache key: {key}")

            return bool(result)

        except RedisError as e:
            logger.warning(f"Redis SET error for key {key}: {e}")
            return False
        except Exception as e:
            logger.warning(f"Unexpected error setting cache key {key}: {e}")
            return False

    async def delete(self, key: str) -> bool:
        """
        Delete key from cache.

        Args:
            key: Cache key to delete

        Returns:
            True if key was deleted, False otherwise
        """
        if not self._is_available():
            return False

        try:
            result = await self._redis.delete(key)
            if result:
                logger.debug(f"Cache deleted: {key}")
            else:
                logger.debug(f"Cache key not found for deletion: {key}")
            return bool(result)
        except RedisError as e:
            logger.warning(f"Redis DELETE error for key {key}: {e}")
            return False
        except Exception as e:
            logger.warning(f"Unexpected error deleting cache key {key}: {e}")
            return False

    async def exists(self, key: str) -> bool:
        """
        Check if key exists in cache.

        Args:
            key: Cache key to check

        Returns:
            True if key exists, False otherwise
        """
        if not self._is_available():
            return False

        try:
            result = await self._redis.exists(key)
            return bool(result)
        except RedisError as e:
            logger.warning(f"Redis EXISTS error for key {key}: {e}")
            return False
        except Exception as e:
            logger.warning(f"Unexpected error checking cache key {key}: {e}")
            return False

# Global cache instance
redis_cache = RedisCache()

# Cache key prefixes
QUERY_UNDERSTANDING_PREFIX = "query:understanding"
SEARCH_RESULTS_PREFIX = "search:results"
PRODUCT_PREFIX = "product"
PRICES_PREFIX = "prices"

# Default TTL values (in seconds)
QUERY_UNDERSTANDING_TTL = 3600  # 1 hour
SEARCH_RESULTS_TTL = 300       # 5 minutes
PRODUCT_TTL = 900              # 15 minutes
PRICES_TTL = 300               # 5 minutes

async def init_redis_cache():
    """Initialize the global Redis cache."""
    global redis_cache
    # Try to get Redis URL from environment
    import os
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    redis_cache = RedisCache(redis_url=redis_url)
    await redis_cache.initialize()

async def close_redis_cache():
    """Close the global Redis cache."""
    global redis_cache
    await redis_cache.close()

def make_query_understanding_key(normalized_query: str, parsed_query_dict: dict) -> str:
    """
    Create cache key for query understanding.

    Args:
        normalized_query: Normalized query string
        parsed_query_dict: Parsed query as dictionary

    Returns:
        Cache key for query understanding
    """
    data = {
        "normalized_query": normalized_query,
        "parsed_query": parsed_query_dict
    }
    # Use a shared hasher instance for efficiency
    from redis_cache import RedisCache
    hasher = RedisCache()
    hash_suffix = hasher._hash_key(data)
    return hasher._make_key(QUERY_UNDERSTANDING_PREFIX, hash_suffix)

def make_search_results_key(
    normalized_query: str,
    parsed_query_dict: dict,
    limit: int = 20,
    **extra_params
) -> str:
    """
    Create cache key for search results.

    Args:
        normalized_query: Normalized query string
        parsed_query_dict: Parsed query as dictionary
        limit: Result limit
        **extra_params: Additional parameters that affect search results

    Returns:
        Cache key for search results
    """
    data = {
        "normalized_query": normalized_query,
        "parsed_query": parsed_query_dict,
        "limit": limit,
        **extra_params
    }
    from redis_cache import RedisCache
    hasher = RedisCache()
    hash_suffix = hasher._hash_key(data)
    return hasher._make_key(SEARCH_RESULTS_PREFIX, hash_suffix)

def make_product_key(product_id: str) -> str:
    """
    Create cache key for product data.

    Args:
        product_id: Product ID string

    Returns:
        Cache key for product
    """
    from redis_cache import RedisCache
    hasher = RedisCache()
    return hasher._make_key(PRODUCT_PREFIX, product_id)

def make_prices_key(product_id: str) -> str:
    """
    Create cache key for product prices.

    Args:
        product_id: Product ID string

    Returns:
        Cache key for prices
    """
    from redis_cache import RedisCache
    hasher = RedisCache()
    return hasher._make_key(PRICES_PREFIX, product_id)