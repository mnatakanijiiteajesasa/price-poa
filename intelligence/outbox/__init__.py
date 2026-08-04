"""
Transactional outbox pattern for MongoDB <-> Qdrant embedding consistency.

This package keeps the `products` collection and the Qdrant `product_embeddings`
collection consistent without the classic "dual write" race: a product change
and a pending outbox record are committed to MongoDB inside a SINGLE
transaction, and a separate worker (worker.py) tails the outbox via Change
Streams (CDC) to push embeddings to Qdrant, marking the record processed only
after Qdrant acknowledges. A periodic reconciliation sweep makes the worker
crash-safe: anything left pending after a restart is simply re-processed, and
idempotency is guaranteed by deterministic point IDs per (product_id, variant).
"""
from .outbox import EmbeddingOutboxService

__all__ = ["EmbeddingOutboxService"]
