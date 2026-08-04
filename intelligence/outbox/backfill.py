#!/usr/bin/env python3
"""
Backfill: enqueue every current product into the embedding outbox so the worker
indexes it into Qdrant (used after seeding, or to re-index all products).

Run from the intelligence container (working dir /app):
    python -m outbox.backfill
    python -m outbox.backfill --force   # re-enqueue even already-processed products
"""
import asyncio
import argparse
import logging

from .outbox import EmbeddingOutboxService

logger = logging.getLogger(__name__)


async def _main(force: bool):
    svc = EmbeddingOutboxService()
    count = await svc.backfill_products(force=force)
    print(f"[backfill] enqueued {count} product(s). The outbox worker will index them.")


def main():
    parser = argparse.ArgumentParser(description="Enqueue all products into the embedding outbox")
    parser.add_argument("--force", action="store_true",
                        help="Re-enqueue even products already marked processed")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    asyncio.run(_main(args.force))


if __name__ == "__main__":
    main()