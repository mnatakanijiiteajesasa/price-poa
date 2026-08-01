"""
Product embedding indexing module for the intelligence service.
Handles indexing of product names and aliases into Qdrant vector database.
"""

import os
import logging
from typing import List, Dict, Any
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorClient
from qdrant_client import QdrantClient
from qdrant_client.http import models as rest
from qdrant_client.http.models import PointStruct
from sentence_transformers import SentenceTransformer
from dotenv import load_dotenv
import asyncio
import hashlib

# Load environment variables
load_dotenv()

# Configure logging
logger = logging.getLogger(__name__)

# Configuration
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://host.docker.internal:27017")
MONGODB_DB = os.getenv("MONGODB_DB", "pricepoa")
QDRANT_HOST = os.getenv("QDRANT_HOST", "host.docker.internal")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
COLLECTION_NAME = "product_embeddings"
VECTOR_SIZE = 384  # all-MiniLM-L6-v2 dimension
MODEL_NAME = 'all-MiniLM-L6-v2'
BATCH_SIZE = 100

class ProductEmbeddingIndexer:
    def __init__(self):
        self.mongo_client = None
        self.db = None
        self.qdrant_client = None
        self.model = None

    async def initialize(self):
        """Initialize MongoDB, Qdrant connections and load model."""
        try:
            # Initialize MongoDB
            self.mongo_client = AsyncIOMotorClient(MONGODB_URI)
            self.db = self.mongo_client[MONGODB_DB]
            # Test connection
            await self.mongo_client.admin.command('ping')
            logger.info(f"Connected to MongoDB: {MONGODB_URI}")

            # Initialize Qdrant
            self.qdrant_client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
            # Test connection
            self.qdrant_client.get_collections()
            logger.info(f"Connected to Qdrant: {QDRANT_HOST}:{QDRANT_PORT}")

            # Ensure collection exists
            self._ensure_collection()

            # Load sentence transformer model
            self.model = SentenceTransformer(MODEL_NAME)
            logger.info(f"Loaded sentence transformer model: {MODEL_NAME}")

        except Exception as e:
            logger.error(f"Failed to initialize connections: {e}")
            raise

    def _ensure_collection(self):
        """Ensure Qdrant collection exists with proper configuration."""
        try:
            collections = self.qdrant_client.get_collections().collections
            collection_names = [col.name for col in collections]

            if COLLECTION_NAME not in collection_names:
                self.qdrant_client.create_collection(
                    collection_name=COLLECTION_NAME,
                    vectors_config=rest.VectorParams(
                        size=VECTOR_SIZE,
                        distance=rest.Distance.COSINE
                    )
                )
                logger.info(f"Created Qdrant collection: {COLLECTION_NAME}")
            else:
                logger.info(f"Using existing Qdrant collection: {COLLECTION_NAME}")

        except Exception as e:
            logger.error(f"Error ensuring Qdrant collection: {e}")
            raise

    async def fetch_products(self) -> List[Dict[str, Any]]:
        """Fetch all products from MongoDB."""
        try:
            products = await self.db.products.find({}).to_list(length=None)
            logger.info(f"Fetched {len(products)} products from MongoDB")
            return products
        except Exception as e:
            logger.error(f"Error fetching products from MongoDB: {e}")
            raise

    def generate_variants(self, product: Dict[str, Any]) -> List[str]:
        """
        Generate text variants for embedding from product data.
        Includes product name, swahili_aliases, and sheng_aliases.
        """
        variants = []

        # Add product name
        if product.get('name'):
            variants.append(product['name'].strip())

        # Add Swahili aliases
        swahili_aliases = product.get('swahili_aliases', [])
        for alias in swahili_aliases:
            if alias and alias.strip():
                variants.append(alias.strip())

        # Add Sheng aliases
        sheng_aliases = product.get('sheng_aliases', [])
        for alias in sheng_aliases:
            if alias and alias.strip():
                variants.append(alias.strip())

        # Remove duplicates while preserving order
        seen = set()
        unique_variants = []
        for variant in variants:
            if variant not in seen:
                seen.add(variant)
                unique_variants.append(variant)

        return unique_variants

    def _generate_point_id(self, product_id: str, text: str) -> int:
        """
        Generate a deterministic point ID from product_id and text.
        Uses hash of the combination to ensure uniqueness.
        """
        combined = f"{product_id}_{text}"
        # Use hash to generate a consistent integer ID
        hash_object = hashlib.md5(combined.encode())
        # Convert to integer within Qdrant's ID range
        return int(hash_object.hexdigest(), 16) % (2**63 - 1)

    async def index_products(self):
        """Main indexing process."""
        try:
            # Initialize connections
            await self.initialize()

            # Fetch products
            products = await self.fetch_products()

            if not products:
                logger.warning("No products found to index")
                return 0

            total_vectors = 0
            processed_products = 0

            # Process in batches to avoid memory issues
            for i in range(0, len(products), BATCH_SIZE):
                batch = products[i:i + BATCH_SIZE]
                points = []

                for product in batch:
                    product_id = str(product.get('_id'))
                    if not product_id:
                        logger.warning(f"Product missing _id: {product}")
                        continue

                    # Generate text variants
                    variants = self.generate_variants(product)

                    if not variants:
                        logger.warning(f"No text variants for product {product_id}")
                        continue

                    # Encode all variants for this product
                    try:
                        vectors = self.model.encode(variants)

                        # Create a point for each variant
                        for variant, vector in zip(variants, vectors):
                            point_id = self._generate_point_id(product_id, variant)
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
                        logger.error(f"Error encoding variants for product {product_id}: {e}")
                        continue

                # Upsert batch to Qdrant
                if points:
                    try:
                        self.qdrant_client.upsert(
                            collection_name=COLLECTION_NAME,
                            points=points
                        )
                        total_vectors += len(points)
                        processed_products += len(batch)
                        logger.info(f"Upserted batch of {len(points)} vectors (total: {total_vectors})")
                    except Exception as e:
                        logger.error(f"Error upserting batch to Qdrant: {e}")
                        continue

            logger.info(f"Indexing complete. Total vectors indexed: {total_vectors}, Products processed: {processed_products}")
            return total_vectors

        except Exception as e:
            logger.error(f"Error during indexing process: {e}")
            raise
        finally:
            # Cleanup
            if self.mongo_client:
                self.mongo_client.close()

# Convenience function for external calling
async def index_product_embeddings():
    """
    Convenience function to index product embeddings.
    Can be called by scheduler or other services.
    """
    indexer = ProductEmbeddingIndexer()
    return await indexer.index_products()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(index_product_embeddings())