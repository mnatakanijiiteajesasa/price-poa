"""
Product embedding indexing module for the intelligence service.
Updated to use the enhanced search pipeline with rich product representations.
"""

import os
import logging
from typing import List, Dict, Any
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logger = logging.getLogger(__name__)

# Configuration
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://host.docker.internal:27017")
MONGODB_DB = os.getenv("MONGODB_DB", "pricepoa")

async def index_products_with_enhanced_pipeline():
    """
    Index products using the enhanced search pipeline with rich representations.
    This is the recommended approach for the new search system.
    """
    try:
        # Import the enhanced vector search service
        from intelligence.nlp.search_pipeline.vector_search import EnhancedVectorSearchService

        # Connect to MongoDB
        mongo_client = AsyncIOMotorClient(MONGODB_URI)
        db = mongo_client[MONGODB_DB]

        # Test connections
        await mongo_client.admin.command('ping')
        logger.info(f"Connected to MongoDB: {MONGODB_URI}")

        # Initialize the enhanced vector search service
        vector_service = EnhancedVectorSearchService()

        # Verify service health
        if not vector_service.health_check():
            logger.warning("Vector search service health check failed - checking components individually")

        # Fetch all products
        products = await db.products.find({}).to_list(length=None)
        logger.info(f"Fetched {len(products)} products from MongoDB")

        if not products:
            logger.warning("No products found to index")
            await mongo_client.close()
            return 0

        # Index products using the enhanced service
        indexed_count = await vector_service.index_products_batch(products)
        logger.info(f"Successfully indexed {indexed_count} out of {len(products)} products")

        # Get collection info for verification
        collection_info = vector_service.get_collection_info()
        if collection_info:
            logger.info(f"Collection info: {collection_info}")

        # Cleanup
        mongo_client.close()
        return indexed_count

    except Exception as e:
        logger.error(f"Error in enhanced indexing process: {e}")
        raise

# Legacy function kept for backward compatibility (uses old approach)
async def index_product_embeddings():
    """
    Legacy indexing function - kept for backward compatibility.
    For new implementations, use index_products_with_enhanced_pipeline().
    """
    logger.warning("Using legacy indexing function. Consider upgrading to index_products_with_enhanced_pipeline()")

    # Import here to avoid circular imports if modules aren't available
    import asyncio
    import hashlib
    from datetime import datetime, timezone

    from motor.motor_asyncio import AsyncIOMotorClient
    from qdrant_client import QdrantClient
    from qdrant_client.http import models as rest
    from qdrant_client.http.models import PointStruct
    from sentence_transformers import SentenceTransformer
    from dotenv import load_dotenv

    load_dotenv()

    logger = logging.getLogger(__name__)

# Configuration
MONGODB_URI = os.getenv("MONGODB_URI")
MONGODB_DB = os.getenv("MONGODB_DB")
QDRANT_HOST = os.getenv("QDRANT_HOST")
QDRANT_PORT = int(os.getenv("QDRANT_PORT"))
COLLECTION_NAME = "product_embeddings"
VECTOR_SIZE = 384  # all-MiniLM-L6-v2 dimension
MODEL_NAME = 'all-MiniLM-L6-v2'
BATCH_SIZE = 100

    try:
        # Initialize connections
        mongo_client = AsyncIOMotorClient(MONGODB_URI)
        db = mongo_client[MONGODB_DB]
        await mongo_client.admin.command('ping')
        logger.info(f"Connected to MongoDB: {MONGODB_URI}")

        qdrant_client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
        qdrant_client.get_collections()
        logger.info(f"Connected to Qdrant: {QDRANT_HOST}:{QDRANT_PORT}")

        # Ensure collection exists
        collections = qdrant_client.get_collections().collections
        collection_names = [col.name for col in collections]

        if COLLECTION_NAME not in collection_names:
            qdrant_client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=rest.VectorParams(
                    size=VECTOR_SIZE,
                    distance=rest.Distance.COSINE
                )
            )
            logger.info(f"Created Qdrant collection: {COLLECTION_NAME}")
        else:
            logger.info(f"Using existing Qdrant collection: {COLLECTION_NAME}")

        # Load model
        model = SentenceTransformer(MODEL_NAME)
        logger.info(f"Loaded sentence transformer model: {MODEL_NAME}")

        # Fetch products
        products = await db.products.find({}).to_list(length=None)
        logger.info(f"Fetched {len(products)} products from MongoDB")

        if not products:
            logger.warning("No products found to index")
            return 0

        total_indexed = 0

        # Process in batches
        for i in range(0, len(products), BATCH_SIZE):
            batch = products[i:i + BATCH_SIZE]
            points = []

            for product in batch:
                try:
                    product_id = str(product.get('_id'))
                    if not product_id:
                        logger.warning(f"Product missing _id: {product}")
                        continue

                    # Generate text variants (legacy approach)
                    def generate_variants(prod):
                        variants = []
                        if prod.get('name'):
                            variants.append(prod['name'].strip())

                        for alias in prod.get('swahili_aliases', []):
                            if alias and alias.strip():
                                variants.append(alias.strip())

                        for alias in prod.get('sheng_aliases', []):
                            if alias and alias.strip():
                                variants.append(alias.strip())

                        seen = set()
                        unique_variants = []
                        for v in variants:
                            if v not in seen:
                                seen.add(v)
                                unique_variants.append(v)
                        return unique_variants

                    variants = generate_variants(product)
                    if not variants:
                        logger.warning(f"No text variants for product {product_id}")
                        continue

                    # Encode vectors
                    vectors = model.encode(variants)

                    # Create points
                    for variant, vector in zip(variants, vectors):
                        combined = f"{product_id}_{hashlib.md5(variant.encode()).hexdigest()}"
                        point_id = abs(hash(combined)) % (2**63 - 1)

                        point = PointStruct(
                            id=point_id,
                            vector=vector.tolist(),
                            payload={
                                "product_id": product_id,
                                "text": variant,
                                "product_name": product.get('name', ''),
                                "indexed_at": datetime.now(timezone.utc).isoformat()
                            }
                        )
                        points.append(point)

                except Exception as e:
                    logger.error(f"Error processing product {product.get('_id')}: {e}")
                    continue

            # Upsert batch
            if points:
                qdrant_client.upsert(
                    collection_name=COLLECTION_NAME,
                    points=points
                )
                total_indexed += len(points)
                logger.info(f"Indexed batch of {len(points)} vectors (total: {total_indexed})")

        logger.info(f"Legacy indexing complete. Total vectors indexed: {total_indexed}")
        return total_indexed

    except Exception as e:
        logger.error(f"Error in legacy indexing process: {e}")
        raise
    finally:
        if 'mongo_client' in locals():
            mongo_client.close()

# Main entry point - use enhanced pipeline by default
async def index_products():
    """
    Main indexing function - uses the enhanced search pipeline.
    """
    return await index_products_with_enhanced_pipeline()

if __name__ == "__main__":
    import asyncio
    logging.basicConfig(level=logging.INFO)
    asyncio.run(index_products())