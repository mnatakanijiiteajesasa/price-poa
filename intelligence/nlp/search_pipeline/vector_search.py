"""
Enhanced vector search service for the search pipeline.
Uses BAAI/bge-small-en-v1.5 model and stores rich product payloads in Qdrant.
"""

import os
import logging
from typing import List, Dict, Any, Optional
from datetime, timezone
from dataclasses import asdict

from motor.motor_asyncio import AsyncIOMotorDatabase, TYPE_CHECKING

if TYPE_CHECKING:
    from qdrant_client import QdrantClient
    from qdrant_client.http import models as rest
    from qdrant_client.http.models import PointStruct
    from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

# Import config
try:
    from .config import get_vector_search_config
    VECTOR_CONFIG_AVAILABLE = True
except ImportError:
    VECTOR_CONFIG_AVAILABLE = False
    logger.warning("Vector search config not available, using defaults")

# Try to import required libraries
try:
    from qdrant_client import QdrantClient
    from qdrant_client.http import models as rest
    from qdrant_client.http.models import PointStruct
    from sentence_transformers import SentenceTransformer
    VECTOR_SEARCH_AVAILABLE = True
except ImportError as e:
    VECTOR_SEARCH_AVAILABLE = False
    logger.warning(f"Vector search dependencies not available: {e}")

class EnhancedVectorSearchService:
    """
    Enhanced service for handling vector-based product search using Qdrant.
    Uses BAAI/bge-small-en-v1.5 model and stores rich product payloads.
    """

    _model = None  # Class-level cache for the sentence transformer model
    _model_name = None

    def __init__(self):
        """Initialize the enhanced vector search service."""
        if not VECTOR_SEARCH_AVAILABLE:
            raise ImportError("Vector search dependencies not available")

        self.client = None
        self.collection_name = "product_embeddings"
        self.vector_size = 384  # BAAI/bge-small-en-v1.5 dimension
        self._initialize_client()
        self._initialize_model()

    def _get_config(self) -> dict:
        """Get vector search configuration."""
        if VECTOR_CONFIG_AVAILABLE:
            return get_vector_search_config()
        return {}

    def _initialize_client(self):
        """Initialize Qdrant client connection."""
        try:
            config = self._get_config()

            qdrant_host = config.get('qdrant_host', os.getenv('QDRANT_HOST', 'host.docker.internal'))
            qdrant_port = int(config.get('qdrant_port', os.getenv('QDRANT_PORT', '6333')))
            self.collection_name = config.get('collection_name', os.getenv('VECTOR_COLLECTION', 'product_embeddings'))
            self.vector_size = int(config.get('vector_size', os.getenv('VECTOR_SIZE', '384')))

            self.client = QdrantClient(host=qdrant_host, port=qdrant_port)

            # Try to get collection info, create if doesn't exist
            try:
                self.client.get_collection(self.collection_name)
                logger.info(f"Connected to existing Qdrant collection: {self.collection_name}")
            except Exception:
                # Collection doesn't exist, create it
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=rest.VectorParams(
                        size=self.vector_size,
                        distance=rest.Distance.COSINE
                    )
                )
                logger.info(f"Created new Qdrant collection: {self.collection_name}")

        except Exception as e:
            logger.warning(f"Failed to initialize Qdrant client: {e}")
            self.client = None

    def _initialize_model(self):
        """Initialize sentence transformer model for text encoding."""
        if EnhancedVectorSearchService._model is not None:
            return

        try:
            config = self._get_config()
            model_name = config.get('model_name', os.getenv('VECTOR_MODEL_NAME', 'BAAI/bge-small-en-v1.5'))

            # Only reload model if model name changed
            if EnhancedVectorSearchService._model_name != model_name:
                EnhancedVectorSearchService._model = SentenceTransformer(model_name)
                EnhancedVectorSearchService._model_name = model_name
                logger.info(f"Loaded sentence transformer model: {model_name}")

        except Exception as e:
            logger.warning(f"Failed to load sentence transformer model: {e}")
            EnhancedVectorSearchService._model = None

    @property
    def model(self):
        """Get the sentence transformer model."""
        if EnhancedVectorSearchService._model is None:
            self._initialize_model()
        return EnhancedVectorSearchService._model

    async def search_similar_products(
        self,
        query_text: str,
        limit: int = 50,
        score_threshold: float = 0.3
    ) -> List[Dict[str, Any]]:
        """
        Search for similar products using vector embeddings.

        Args:
            query_text: Text to search for
            limit: Maximum number of results to return
            score_threshold: Minimum similarity score threshold

        Returns:
            List of product matches with scores and payloads
        """
        if not self.client or self.model is None:
            logger.warning("Qdrant client or sentence transformer model not available for vector search")
            return []

        try:
            # Encode the query text to a vector
            vector = self.model.encode([query_text])[0].tolist()

            # Search in Qdrant
            search_result = self.client.query_points(
                collection_name=self.collection_name,
                query=vector,
                limit=limit,
                score_threshold=score_threshold,
                with_payload=True  # We need the payload to get product info
            ).points

            # Format results
            results = []
            for point in search_result:
                payload = point.payload or {}
                product_id = payload.get("product_id")
                if product_id:
                    results.append({
                        "product_id": product_id,
                        "score": point.score,
                        "payload": payload  # Include full payload for potential future use
                    })

            logger.info(f"Vector search for '{query_text}' returned {len(results)} results")
            return results

        except Exception as e:
            logger.error(f"Error performing vector search: {e}")
            return []

    async def index_product(
        self,
        product_data: Dict[str, Any],
        embedding_text: Optional[str] = None
    ) -> bool:
        """
        Index a single product in the vector database.

        Args:
            product_data: Product document from MongoDB
            embedding_text: Optional pre-generated embedding text. If not provided,
                           it will be generated from the product data.

        Returns:
            True if successful, False otherwise
        """
        if not self.client or self.model is None:
            logger.warning("Vector search service not available for indexing")
            return False

        try:
            # Generate embedding text if not provided
            if embedding_text is None:
                from .product_representation import product_to_embedding_text
                embedding_text = product_to_embedding_text(product_data)

            if not embedding_text or not embedding_text.strip():
                logger.warning(f"No valid embedding text for product {product_data.get('_id')}")
                return False

            # Encode the text to get vector
            vector = self.model.encode([embedding_text])[0].tolist()

            # Generate point ID
            product_id = str(product_data.get('_id', ''))
            if not product_id:
                logger.warning("Product missing _id, cannot index")
                return False

            # Create point ID from product ID and text hash
            import hashlib
            combined = f"{product_id}_{hashlib.md5(embedding_text.encode()).hexdigest()[:8]}"
            point_id = abs(hash(combined)) % (2**63 - 1)  # Ensure positive 64-bit int

            # Prepare payload with rich product information
            payload = {
                "product_id": product_id,
                "text": embedding_text,
                "indexed_at": datetime.now(timezone.utc).isoformat()
            }

            # Add structured data from product for reranking
            from .product_representation import ProductRepresentationBuilder
            builder = ProductRepresentationBuilder()
            doc = builder.build_from_product_dict(product_data)

            # Add structured fields to payload for use in reranking
            payload.update({
                "product_name": doc.product_name,
                "brand": doc.brand,
                "category": doc.category,
                "size": doc.size,
                "unit": doc.unit,
                "aliases": doc.aliases
            })

            # Upsert point to Qdrant
            self.client.upsert(
                collection_name=self.collection_name,
                points=[PointStruct(
                    id=point_id,
                    vector=vector,
                    payload=payload
                )]
            )

            logger.debug(f"Indexed product {product_id} in vector store")
            return True

        except Exception as e:
            logger.error(f"Error indexing product {product_data.get('_id')}: {e}")
            return False

    async def index_products_batch(
        self,
        products: List[Dict[str, Any]]
    ) -> int:
        """
        Index a batch of products in the vector database.

        Args:
            products: List of product documents from MongoDB

        Returns:
            Number of products successfully indexed
        """
        if not self.client or self.model is None:
            logger.warning("Vector search service not available for batch indexing")
            return 0

        if not products:
            return 0

        try:
            points = []
            successful_count = 0

            for product in products:
                product_id = str(product.get('_id', ''))
                if not product_id:
                    logger.warning("Skipping product missing _id")
                    continue

                try:
                    # Generate embedding text
                    from .product_representation import product_to_embedding_text
                    embedding_text = product_to_embedding_text(product)

                    if not embedding_text or not embedding_text.strip():
                        logger.warning(f"No valid embedding text for product {product_id}")
                        continue

                    # Encode the text to get vector
                    vector = self.model.encode([embedding_text])[0].tolist()

                    # Generate point ID
                    import hashlib
                    combined = f"{product_id}_{hashlib.md5(embedding_text.encode()).hexdigest()[:8]}"
                    point_id = abs(hash(combined)) % (2**63 - 1)

                    # Build product document for rich payload
                    from .product_representation import ProductRepresentationBuilder
                    builder = ProductRepresentationBuilder()
                    doc = builder.build_from_product_dict(product)

                    # Prepare payload
                    payload = {
                        "product_id": product_id,
                        "text": embedding_text,
                        "indexed_at": datetime.now(timezone.utc).isoformat(),
                        "product_name": doc.product_name,
                        "brand": doc.brand,
                        "category": doc.category,
                        "size": doc.size,
                        "unit": doc.unit,
                        "aliases": doc.aliases
                    }

                    points.append(PointStruct(
                        id=point_id,
                        vector=vector,
                        payload=payload
                    ))
                    successful_count += 1

                except Exception as e:
                    logger.error(f"Error preparing product {product_id} for indexing: {e}")
                    continue

            # Upsert batch to Qdrant
            if points:
                self.client.upsert(
                    collection_name=self.collection_name,
                    points=points
                )
                logger.info(f"Indexed batch of {len(points)} products ({successful_count} successful)")

            return successful_count

        except Exception as e:
            logger.error(f"Error indexing product batch: {e}")
            return 0

    def get_collection_info(self) -> Optional[dict]:
        """
        Get information about the vector collection.

        Returns:
            Dictionary with collection info or None if error
        """
        if not self.client:
            return None

        try:
            info = self.client.get_collection(self.collection_name)
            return {
                "name": config.result.params.config.params.vectors.size if hasattr(config.result.params.config, 'params') else self.vector_size,
                "vectors_count": str(getattr(config.result, 'vectors_count', 'unknown')),
                "indexed_vectors_count": str(getattr(config.result, 'indexed_vectors_count', 'unknown')),
                "points_count": str(getattr(config.result, 'points_count', 'unknown')),
                "status": str(getattr(config.result, 'status', 'unknown'))
            }
        except Exception as e:
            logger.error(f"Error getting collection info: {e}")
            return None

    def health_check(self) -> bool:
        """
        Check if the vector search service is healthy.

        Returns:
            True if healthy, False otherwise
        """
        try:
            if not self.client:
                return False

            # Try to get collections
            self.client.get_collections()

            # Try to get collection info
            self.get_collection_info()

            # Try to check if model is loaded
            _ = self.model

            return True
        except Exception as e:
            logger.warning(f"Vector search health check failed: {e}")
            return False

# Convenience function for external use
async def get_vector_search_service() -> EnhancedVectorSearchService:
    """
    Get or create the vector search service instance.

    Returns:
        EnhancedVectorSearchService instance
    """
    return EnhancedVectorSearchService()