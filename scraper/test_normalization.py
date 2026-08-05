"""
End-to-end test for the NormalizationPipeline.

This test:
- Uses mocked MongoDB collections.
- Uses a mocked Outbox service.
- Runs the complete normalization flow.dock
- Prints the normalized output instead of persisting data.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from pipelines.normalization_pipeline import NormalizationPipeline


# Mock Mongo Collections


class MockInsertResult:
    def __init__(self, inserted_id):
        self.inserted_id = inserted_id


class MockStoresCollection:
    def __init__(self):
        self.find_one = AsyncMock(return_value=None)
        self.insert_one = AsyncMock(
            return_value=MockInsertResult("mock_store_id")
        )


class MockProductsCollection:
    def __init__(self):
        self.find_one = AsyncMock(return_value=None)
        self.insert_one = AsyncMock(
            return_value=MockInsertResult("mock_product_id")
        )

        self.update_one = AsyncMock()


class MockDatabase:
    def __init__(self):
        self.stores = MockStoresCollection()
        self.products = MockProductsCollection()


# Mock Outbox


class MockOutboxService:

    async def insert_product_with_outbox(
        self,
        new_product_doc,
        intent
    ):
        return "mock_product_id"

    async def update_product_with_outbox(
        self,
        product_id,
        update_fields,
        intent
    ):
        return product_id


# Test


async def main():

    pipeline = NormalizationPipeline()

    pipeline.db = MockDatabase()
    pipeline.outbox = MockOutboxService()

    spider = SimpleNamespace(name="test_spider")

    sample_items = [

        {
            "product_name": "Brookside Fresh Milk 500ML",
            "price_kes": 80,
            "store_chain": "Naivas",
            "store_branch": "Westlands",
            "source": "naivas_online",
            "verified_at": "2026-08-04T10:00:00Z",
            "is_promotional": False,
            "promotion_details": None,
        },

        {
            "product_name": "Daima Strawberry Yogurt 400g",
            "price_kes": 120,
            "store_chain": "Carrefour",
            "store_branch": "Garden City",
            "source": "carrefour_online",
            "verified_at": "2026-08-04T11:30:00Z",
            "is_promotional": True,
            "promotion_details": "Buy 2 Get 1 Free",
        },

        {
            "product_name": "Jogoo Maize Flour 2KG",
            "price_kes": 180,
            "store_chain": "Quickmart",
            "store_branch": "Mombasa Road",
            "source": "quickmart_online",
            "verified_at": "2026-08-04T09:15:00Z",
            "is_promotional": False,
            "promotion_details": None,
        },
    ]

    print("=" * 80)
    print("NORMALIZATION PIPELINE TEST")
    print("=" * 80)

    for i, item in enumerate(sample_items, start=1):

        print(f"\nItem {i}")
        print("-" * 80)

        print("INPUT")
        for k, v in item.items():
            print(f"{k:20}: {v}")

        try:

            result = await pipeline.process_item(item, spider)

            print("\nOUTPUT")

            print(f"Product ID          : {result.get('product_id')}")
            print(f"Store ID            : {result.get('store_id')}")
            print(f"Price               : {result.get('price_kes')}")

            normalized = result.get("normalized_product")

            if normalized:

                cp = normalized.canonical_product

                print("\nCanonical Product")
                print(f"Canonical Name      : {cp.canonical_name}")
                print(f"Brand               : {cp.brand}")
                print(f"Category            : {cp.category}")
                print(f"Subcategory         : {cp.subcategory}")
                print(f"Size                : {cp.size}")
                print(f"Unit                : {cp.unit}")
                print(f"Package Type        : {cp.package_type}")
                print(f"Variant             : {cp.variant}")
                print(f"Flavour             : {cp.flavour}")

                print("\nAliases")

                if cp.aliases:
                    for alias in cp.aliases:
                        print(f"  • {alias}")
                else:
                    print("  None")

                print("\nEmbedding Text")
                print(cp.embedding_text)

            else:
                print("No normalized_product returned.")

        except Exception as e:

            print(f"FAILED: {e}")

    print("\n")
    print("=" * 80)
    print("TEST COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())