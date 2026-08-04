"""
ProductEmbedder
---------------
Encodes a product document into text variants, embeds them with
sentence-transformers, and upserts/deletes the resulting vectors in Qdrant.

All Qdrant point IDs are deterministic hashes of (product_id, variant), which
is what makes outbox processing idempotent: re-running the same product write
recreates the exact same points, and upserting is safe to repeat.
"""
import os
import hashlib
import asyncio
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Tuple, Optional

from qdrant_client import QdrantClient
from qdrant_client.http import models as rest
from qdrant_client.http.models import PointStruct

logger = logging.getLogger(__name__)

QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
COLLECTION_NAME = "product_embeddings"
VECTOR_SIZE = 384  # all-MiniLM-L6-v2 dimension
MODEL_NAME = "all-MiniLM-L6-v2"


class ProductEmbedder:
    """Builds and pushes product embedding points into Qdrant."""

    _model = None  # process-wide cache for the sentence transformer

    def __init__(self):
        self.qdrant: Optional[QdrantClient] = None

    def ensure_connection(self):
        if self.qdrant is None:
            self.qdrant = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
        collections = [c.name for c in self.qdrant.get_collections().collections]
        if COLLECTION_NAME not in collections:
            self.qdrant.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=rest.VectorParams(size=VECTOR_SIZE, distance=rest.Distance.COSINE),
            )
            logger.info(f"Created Qdrant collection {COLLECTION_NAME}")
        else:
            logger.debug(f"Using existing Qdrant collection {COLLECTION_NAME}")

    def get_model(self):
        if ProductEmbedder._model is None:
            from sentence_transformers import SentenceTransformer
            ProductEmbedder._model = SentenceTransformer(MODEL_NAME)
            logger.info(f"Loaded sentence transformer model: {MODEL_NAME}")
        return ProductEmbedder._model

    # --- text / vector helpers ---------------------------------------------

    def generate_variants(self, product_doc: Optional[Dict[str, Any]]) -> List[str]:
        """Collect unique embeddable text variants: name + swahili + sheng aliases."""
        doc = product_doc or {}
        variants = []
        name = doc.get("name")
        if name and str(name).strip():
            variants.append(str(name).strip())
        for alias in doc.get("swahili_aliases") or []:
            if alias and str(alias).strip():
                variants.append(str(alias).strip())
        for alias in doc.get("sheng_aliases") or []:
            if alias and str(alias).strip():
                variants.append(str(alias).strip())

        seen = set()
        unique = []
        for v in variants:
            if v not in seen:
                seen.add(v)
                unique.append(v)
        return unique

    def point_id(self, product_id: str, text: str) -> int:
        """Deterministic Qdrant point ID derived from (product_id, variant)."""
        combined = f"{product_id}_{text}"
        return int(hashlib.md5(combined.encode()).hexdigest(), 16) % (2 ** 63 - 1)

    def build_points(self, product_doc: Dict[str, Any],
                     vectors, variants: List[str]) -> List[PointStruct]:
        product_id = str(product_doc["_id"])
        points = []
        for variant, vector in zip(variants, vectors):
            points.append(PointStruct(
                id=self.point_id(product_id, variant),
                vector=vector.tolist(),
                payload={
                    "product_id": product_id,
                    "text": variant,
                    "product_name": product_doc.get("name", ""),
                    "indexed_at": datetime.now(timezone.utc).isoformat(),
                },
            ))
        return points

    # --- Qdrant operations ---------------------------------------------------

    def upsert(self, points: List[PointStruct]):
        self.ensure_connection()
        self.qdrant.upsert(collection_name=COLLECTION_NAME, points=points)

    def delete_for_product(self, product_id: str, point_ids: Optional[List[int]] = None):
        """Remove every Qdrant point that belongs to a product.

        Tries deleting by payload filter first (catches all variants, even
        stale ones), falling back to a direct list of point IDs on older
        qdrant-client signatures.
        """
        self.ensure_connection()
        try:
            self.qdrant.delete(
                collection_name=COLLECTION_NAME,
                points_selector=rest.FilterSelector(
                    filter=rest.Filter(
                        must=[rest.FieldCondition(
                            key="product_id", match=rest.MatchValue(value=product_id)
                        )]
                    )
                ),
            )
            logger.info(f"[qdrant] deleted points for product {product_id}")
        except Exception as e:
            if point_ids:
                self.qdrant.delete(collection_name=COLLECTION_NAME, points=point_ids)
                logger.info(f"[qdrant] deleted {len(point_ids)} points for product {product_id}")
            else:
                logger.warning(f"[qdrant] could not delete points for {product_id}: {e}")

    async def embed_product(self, product_doc: Dict[str, Any]) -> Tuple[List[PointStruct], List[int]]:
        """Encode a product document into Qdrant points.

        Returns (points, [point_ids]). Encoding runs in a worker thread so the
        asyncio loop stays responsive.
        """
        self.ensure_connection()
        variants = self.generate_variants(product_doc)
        if not variants:
            return [], []
        vectors = await asyncio.to_thread(self._encode_sync, variants)
        # Normalise to a 2D array even for a single variant
        vectors = vectors.reshape(len(variants), -1) if hasattr(vectors, "reshape") else vectors
        points = self.build_points(product_doc, vectors, variants)
        point_ids = [p.id for p in points]
        return points, point_ids

    def _encode_sync(self, variants: List[str]):
        """Load the model and encode variants. Runs in a worker thread."""
        return self.get_model().encode(variants)