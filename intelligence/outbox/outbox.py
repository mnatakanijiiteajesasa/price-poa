"""
EmbeddingOutboxService
-----------------------
Implements the transactional outbox side of the MongoDB <-> Qdrant
dual-write consistency problem.

Core invariant
--------------
A product write and its "intent to index" record are committed to MongoDB in a
single multi-document transaction. If the process crashes between the product
write and the Qdrant write, the outbox record is already durable alongside the
product, so a worker can pick it up later. Nothing can silently drift.

The worker consumes these records (Change Streams + a reconciliation sweep),
embeds the product, pushes to Qdrant, and marks the record `processed` only
after Qdrant confirms. Processing is idempotent by product _id (deterministic
Qdrant point IDs + upserts), so restarting the worker never double-writes.

REQUIREMENT: multi-document transactions and Change Streams both require
MongoDB to run as a replica set (even a single-node one). See docker-compose.yml
(`mongo` with `--replSet rs0` plus the `mongo-init` service).
"""
import os
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ReturnDocument

logger = logging.getLogger(__name__)

OUTBOX_COLLECTION = "embeddings_outbox"

# Intents stored in each outbox record
INTENT_CREATE = "create"
INTENT_UPDATE = "update"
INTENT_DELETE = "delete"
INTENT_BACKFILL = "backfill"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EmbeddingOutboxService:
    """Transactional writes to MongoDB products + outbox, plus outbox bookkeeping."""

    def __init__(self, mongodb_uri: Optional[str] = None, mongodb_db: Optional[str] = None):
        self.mongodb_uri = mongodb_uri or os.getenv("MONGODB_URI", "mongodb://localhost:27017")
        self.mongodb_db = mongodb_db or os.getenv("MONGODB_DB", "pricepoa")
        self._client: Optional[AsyncIOMotorClient] = None
        self._db = None

    async def connect(self):
        """Open a connection (if needed) and ensure outbox indexes exist."""
        if self._db is None:
            self._client = AsyncIOMotorClient(self.mongodb_uri)
            await self._client.admin.command("ping")
            self._db = self._client[self.mongodb_db]
            await self.ensure_indexes()
            logger.info(f"EmbeddingOutboxService connected to {self.mongodb_db}")
        return self._db

    @property
    def db(self):
        return self._db

    async def ensure_indexes(self):
        db = await self.connect()
        await db[OUTBOX_COLLECTION].create_index([("status", 1), ("created_at", 1)])
        await db[OUTBOX_COLLECTION].create_index([("product_id", 1), ("intent", 1)])

    # --- outbox record construction ---------------------------------------

    def _new_doc(self, product_id: str, intent: str, **extra) -> dict:
        now = utcnow()
        doc = {
            "product_id": product_id,
            "intent": intent,
            "status": "pending",
            "attempts": 0,
            "created_at": now,
            "updated_at": now,
            "processed_at": None,
            "last_error": None,
            "point_ids": [],
            "backoff_until": None,
        }
        doc.update(extra)
        return doc

    # --- transactional product + outbox writes ----------------------------

    async def insert_product_with_outbox(self, product_doc: dict, intent: str = INTENT_CREATE) -> str:
        """Insert a product AND its pending outbox record in one transaction.

        Returns the new product's string _id. If this transaction aborts,
        neither the product nor the outbox record is written.
        """
        db = await self.connect()
        now = utcnow()
        doc = dict(product_doc)
        doc["created_at"] = now
        doc["updated_at"] = now

        async with await self._client.start_session() as session:
            async with session.start_transaction():
                res = await db.products.insert_one(doc, session=session)
                product_id = str(res.inserted_id)
                await db[OUTBOX_COLLECTION].insert_one(
                    self._new_doc(product_id, intent), session=session
                )
        logger.info(f"[outbox] inserted product {product_id} + outbox record (intent={intent})")
        return product_id

    async def update_product_with_outbox(self, product_id: str, update_op: dict,
                                         intent: str = INTENT_UPDATE) -> None:
        """Update a product AND append a pending outbox record in one transaction.

        `update_op` is a Mongo update document (e.g. {"$addToSet": ..., "$set": ...}).
        A fresh `updated_at` is always merged into the $set clause.
        """
        db = await self.connect()
        merged = dict(update_op)
        merged["$set"] = {**(update_op.get("$set") or {}), "updated_at": utcnow()}

        async with await self._client.start_session() as session:
            async with session.start_transaction():
                res = await db.products.update_one(
                    {"_id": ObjectId(product_id)}, merged, session=session
                )
                if res.matched_count == 0:
                    raise ValueError(f"Product {product_id} not found for transactional update")
                await db[OUTBOX_COLLECTION].insert_one(
                    self._new_doc(product_id, intent), session=session
                )
        logger.info(f"[outbox] updated product {product_id} + outbox record (intent={intent})")

    async def enqueue(self, product_id: str, intent: str = INTENT_CREATE) -> ObjectId:
        """Append a pending outbox record for an already-existing product.

        Used by the backfill path and any caller that writes the product
        outside the transactional helpers.
        """
        db = await self.connect()
        res = await db[OUTBOX_COLLECTION].insert_one(self._new_doc(product_id, intent))
        return res.inserted_id

    # --- worker bookkeeping -------------------------------------------------

    async def claim_next(self, limit: int = 10) -> List[dict]:
        """Atomically claim up to `limit` pending outbox records as `processing`."""
        db = await self.connect()
        now = utcnow()
        claimed: List[dict] = []
        for _ in range(limit):
            doc = await db[OUTBOX_COLLECTION].find_one_and_update(
                {
                    "status": "pending",
                    "$or": [{"backoff_until": None}, {"backoff_until": {"$lte": now}}],
                },
                {
                    "$set": {"status": "processing", "started_at": now, "updated_at": now},
                    "$inc": {"attempts": 1},
                },
                sort=[("created_at", 1)],
                return_document=ReturnDocument.AFTER,
            )
            if doc is None:
                break
            claimed.append(doc)
        return claimed

    async def claim_by_id(self, item_id) -> Optional[dict]:
        """Atomically claim a specific record if it is still pending/failed."""
        db = await self.connect()
        now = utcnow()
        return await db[OUTBOX_COLLECTION].find_one_and_update(
            {
                "_id": ObjectId(item_id),
                "status": "pending",
                "$or": [{"backoff_until": None}, {"backoff_until": {"$lte": now}}],
            },
            {
                "$set": {"status": "processing", "started_at": now, "updated_at": now},
                "$inc": {"attempts": 1},
            },
            return_document=ReturnDocument.AFTER,
        )

    async def mark_processed(self, item_id, point_ids: Optional[List[int]] = None) -> None:
        db = await self.connect()
        await db[OUTBOX_COLLECTION].update_one(
            {"_id": ObjectId(item_id)},
            {"$set": {
                "status": "processed",
                "processed_at": utcnow(),
                "point_ids": point_ids or [],
                "last_error": None,
                "updated_at": utcnow(),
            }},
        )

    async def mark_failed(self, item_id, error, backoff_seconds: int = 60) -> None:
        """Requeue the record as pending after a backoff window so it is retried."""
        db = await self.connect()
        now = utcnow()
        await db[OUTBOX_COLLECTION].update_one(
            {"_id": ObjectId(item_id)},
            {"$set": {
                "status": "pending",
                "last_error": str(error)[:500],
                "backoff_until": now + timedelta(seconds=backoff_seconds),
                "updated_at": now,
            }},
        )

    async def reset_stale_processing(self, timeout_minutes: int = 5) -> int:
        """Return records stuck in `processing` (crash during processing) to pending.

        This is what lets the worker resume work after a restart without losing
        anything - Qdrant upserts are idempotent, so re-processing is safe.
        """
        db = await self.connect()
        cutoff = utcnow() - timedelta(minutes=timeout_minutes)
        res = await db[OUTBOX_COLLECTION].update_many(
            {"status": "processing", "started_at": {"$lt": cutoff}},
            {"$set": {"status": "pending", "updated_at": utcnow()}},
        )
        if res.modified_count:
            logger.info(f"[outbox] reset {res.modified_count} stale 'processing' records to pending")
        return res.modified_count

    # --- bulk backfill -------------------------------------------------------

    async def backfill_products(self, force: bool = False) -> int:
        """Enqueue every current product into the outbox for (re)indexing.

        With `force=False`, products that already have a `processed` outbox
        record are skipped so a routine sweep stays cheap. With `force=True`,
        every product is re-enqueued (used when the model or variants change).
        """
        db = await self.connect()
        products = await db.products.find({}, {"_id": 1}).to_list(length=None)
        count = 0
        for p in products:
            pid = str(p["_id"])
            if not force:
                existing = await db[OUTBOX_COLLECTION].find_one(
                    {"product_id": pid, "status": "processed"}
                )
                if existing:
                    continue
            await self.enqueue(pid, intent=INTENT_BACKFILL)
            count += 1
        logger.info(f"[outbox] enqueued {count} product(s) for backfill")
        return count

    # --- CDC -----------------------------------------------------------------

    async def watch(self, pipeline: Optional[list] = None):
        """Open a Change Stream on the outbox collection.

        Requires a replica set. On standalone MongoDB this raises
        OperationFailure - the worker falls back to polling in that case.
        """
        db = await self.connect()
        return db[OUTBOX_COLLECTION].watch(pipeline or [])

    async def close(self):
        if self._client:
            self._client.close()
            self._client = None
            self._db = None
