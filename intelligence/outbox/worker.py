"""
EmbeddingOutboxWorker
---------------------
Consumes the `embeddings_outbox` collection and keeps Qdrant consistent with
MongoDB's `products`.

Two independent paths feed the same idempotent processing routine:

1. Change Streams (CDC): tails the outbox collection so new product writes are
   picked up as soon as they are committed. This is the low-latency path.
2. Reconciliation sweep: periodically re-claims pending records and resets any
   that were left `processing` by a crashed worker. This is the crash-safety /
   resume path, and it also keeps the system working if Change Streams are
   unavailable (e.g. standalone MongoDB).

A record is marked `processed` only after Qdrant confirms the upsert/delete.
Processing is idempotent by product _id (deterministic point IDs), so running
the same record twice is safe.

Run from the intelligence container (working dir /app):
    python -m outbox.worker
"""
import asyncio
import logging
import signal

from bson import ObjectId

from .outbox import EmbeddingOutboxService, OUTBOX_COLLECTION
from .embedder import ProductEmbedder

logger = logging.getLogger(__name__)

CHANGE_STREAM_PIPELINE = [
    {"$match": {"operationType": {"$in": ["insert", "update"]}}}
]


class EmbeddingOutboxWorker:
    def __init__(self, sweep_interval: float = 15.0, batch_size: int = 10,
                 claim_timeout_minutes: int = 5):
        self.outbox = EmbeddingOutboxService()
        self.embedder = ProductEmbedder()
        self.sweep_interval = sweep_interval
        self.batch_size = batch_size
        self.claim_timeout_minutes = claim_timeout_minutes
        self._running = True

    async def run(self):
        db = await self.outbox.connect()
        self.embedder.ensure_connection()

        # Resume any in-flight work from a previous run before starting to tail.
        await self.outbox.reset_stale_processing(self.claim_timeout_minutes)
        logger.info("EmbeddingOutboxWorker started (Change Streams + reconciliation sweep)")

        await asyncio.gather(
            self._change_stream_loop(db),
            self._sweep_loop(),
        )

    # --- Change Stream (CDC) path -------------------------------------------

    async def _change_stream_loop(self, db):
        backoff = 1
        while self._running:
            try:
                async with db[OUTBOX_COLLECTION].watch(
                    CHANGE_STREAM_PIPELINE, full_document="updateLookup"
                ) as stream:
                    backoff = 1
                    logger.info("Outbox Change Stream connected")
                    async for change in stream:
                        if not self._running:
                            break
                        doc = change.get("fullDocument") or {}
                        if doc.get("status") not in (None, "pending"):
                            continue
                        item_id = doc.get("_id") or change["documentKey"]["_id"]
                        await self._process_item(item_id)
            except Exception as e:
                if not self._running:
                    break
                logger.warning(
                    f"Change Stream unavailable/errored (retrying in {backoff}s): {e}"
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    # --- Reconciliation sweep path --------------------------------------------

    async def _sweep_loop(self):
        while self._running:
            try:
                await self._sweep_once()
            except Exception as e:
                logger.error(f"Sweep error: {e}")
            await asyncio.sleep(self.sweep_interval)

    async def _sweep_once(self):
        await self.outbox.reset_stale_processing(self.claim_timeout_minutes)
        claimed = await self.outbox.claim_next(self.batch_size)
        if claimed:
            logger.info(f"[sweep] claimed {len(claimed)} outbox record(s)")
        for doc in claimed:
            await self._process_item(doc["_id"])

    # --- processing -----------------------------------------------------------

    async def _process_item(self, item_id):
        item = await self.outbox.claim_by_id(item_id)
        if item is None:
            return  # already claimed / processed by another run

        db = self.outbox.db
        product_id = item["product_id"]
        intent = item.get("intent", "create")

        try:
            if intent == "delete":
                point_ids = await self._delete_product(product_id)
            else:
                point_ids = await self._upsert_product(product_id)

            await self.outbox.mark_processed(item_id, point_ids)
            logger.info(f"[outbox] processed product {product_id} (intent={intent})")
        except Exception as e:
            logger.exception(f"[outbox] failed product {product_id} (intent={intent}): {e}")
            await self.outbox.mark_failed(item_id, e)

    async def _upsert_product(self, product_id: str) -> list[int]:
        """Delete stale points for a product, then upsert its current variants."""
        product = await self.outbox.db.products.find_one({"_id": ObjectId(product_id)})
        if product is None:
            # Product no longer exists - mirror that in Qdrant.
            await asyncio.to_thread(self.embedder.delete_for_product, product_id)
            return []
        # Remove previous variants so Qdrant mirrors the current product state.
        await asyncio.to_thread(self.embedder.delete_for_product, product_id)
        points, point_ids = await self.embedder.embed_product(product)
        if points:
            await asyncio.to_thread(self.embedder.upsert, points)
            logger.info(f"[outbox] upserted {len(points)} vector(s) for product {product_id}")
        return point_ids

    async def _delete_product(self, product_id: str) -> list[int]:
        await asyncio.to_thread(self.embedder.delete_for_product, product_id)
        return []


async def _main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    worker = EmbeddingOutboxWorker()
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass

    task = asyncio.create_task(worker.run())
    await stop.wait()
    logger.info("Shutting down EmbeddingOutboxWorker...")
    worker._running = False
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


if __name__ == "__main__":
    asyncio.run(_main())
