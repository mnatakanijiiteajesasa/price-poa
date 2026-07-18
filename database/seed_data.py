"""
Data seeding script for PricePoa database.
Loads initial product and store data from JSON fixtures, and generates
price data for every product x store combination.
"""
import asyncio
import json
import os
import random
from typing import List, Dict, Any
from motor.motor_asyncio import AsyncIOMotorDatabase
import logging

from .connection import get_database
from .models import Product, Store, Price, PRICE_INDEXES

logger = logging.getLogger(__name__)


async def load_products_from_json(file_path: str) -> int:
    """
    Load products from JSON fixture file into MongoDB.

    Args:
        file_path: Path to JSON file containing product data

    Returns:
        Number of products loaded
    """
    try:
        db = await get_database()
        collection = db.products

        # Load JSON data
        with open(file_path, 'r') as f:
            products_data = json.load(f)

        if not isinstance(products_data, list):
            products_data = [products_data]

        # Validate and insert products
        valid_products = []
        for product_data in products_data:
            try:
                # Validate using Pydantic model
                product = Product(**product_data)
                # Convert to dict for MongoDB insertion
                product_dict = product.dict(by_alias=True)
                valid_products.append(product_dict)
            except Exception as e:
                logger.warning(f"Skipping invalid product data: {e}")
                continue

        if valid_products:
            # Clear existing products (for clean seeding)
            await collection.delete_many({})
            # Insert new products
            result = await collection.insert_many(valid_products)
            logger.info(f"Loaded {len(result.inserted_ids)} products into database")
            return len(result.inserted_ids)
        else:
            logger.warning("No valid products found in seed data")
            return 0

    except FileNotFoundError:
        logger.error(f"Product seed file not found: {file_path}")
        return 0
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in product seed file: {e}")
        return 0
    except Exception as e:
        logger.error(f"Error loading products: {e}")
        return 0


async def load_stores_from_json(file_path: str) -> int:
    """
    Load stores from JSON fixture file into MongoDB.

    Args:
        file_path: Path to JSON file containing store data

    Returns:
        Number of stores loaded
    """
    try:
        db = await get_database()
        collection = db.stores

        # Load JSON data
        with open(file_path, 'r') as f:
            stores_data = json.load(f)

        if not isinstance(stores_data, list):
            stores_data = [stores_data]

        # Validate and insert stores
        valid_stores = []
        for store_data in stores_data:
            try:
                # Validate using Pydantic model
                store = Store(**store_data)
                # Convert to dict for MongoDB insertion
                store_dict = store.dict(by_alias=True)
                valid_stores.append(store_dict)
            except Exception as e:
                logger.warning(f"Skipping invalid store data: {e}")
                continue

        if valid_stores:
            # Clear existing stores (for clean seeding)
            await collection.delete_many({})
            # Insert new stores
            result = await collection.insert_many(valid_stores)
            logger.info(f"Loaded {len(result.inserted_ids)} stores into database")
            return len(result.inserted_ids)
        else:
            logger.warning("No valid stores found in seed data")
            return 0

    except FileNotFoundError:
        logger.error(f"Store seed file not found: {file_path}")
        return 0
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in store seed file: {e}")
        return 0
    except Exception as e:
        logger.error(f"Error loading stores: {e}")
        return 0


# Illustrative base price (KES) for the first/typical size variant of each
# product. Rough placeholders for MVP testing - NOT sourced market data.
# Keyed on product["name"] exactly as it appears in products_seed.json.
BASE_PRICES = {
    "Maize Flour (Unga)": 220, "Granulated Sugar": 180, "Cooking Oil": 320,
    "White Bread": 65, "Fresh Milk": 65, "Eggs": 360, "Rice": 320,
    "Tea Leaves": 150, "Salt": 60, "Wheat Flour": 230, "Sorghum": 150,
    "Millet": 180, "Brown Sugar": 190, "Honey": 450, "Jam": 220,
    "Butter": 380, "Margarine": 210, "Ghee": 550, "Brown Bread": 70,
    "Buns": 90, "Cookies": 150, "Yogurt": 120, "Cheese": 280, "Cream": 150,
    "Coffee": 250, "Juice": 180, "Soft Drinks": 130, "Water": 60,
    "Black Pepper": 120, "Curry Powder": 110, "Royco": 90, "Garlic": 60,
    "Tomatoes": 90, "Beans": 150, "Tuna": 220, "Peas": 100, "Corn": 100,
    "Bar Soap": 80, "Toothpaste": 180, "Shampoo": 350, "Sanitary Pads": 150,
    "Diapers": 900, "Washing Powder": 250, "Dishwashing Liquid": 220,
    "Matches": 10, "Candles": 100, "Trash Bags": 200, "Bucket": 350,
}

# Illustrative per-chain pricing tendency, applied as a multiplier on top
# of BASE_PRICES, plus per-branch random noise below. Not sourced data -
# just enough spread that bar charts aren't flat across stores.
CHAIN_FACTOR = {
    "Naivas": 1.00,
    "Carrefour": 1.07,
    "Quickmart": 0.96,
    "Chandarana": 0.98,
}

OFFER_PROBABILITY = 0.12  # ~1 in 8 store/product combos is promotional


def _compute_price(base: float, chain_name: str) -> tuple:
    """Returns (price_kes, is_promotional) for one product/store combo."""
    chain_mult = CHAIN_FACTOR.get(chain_name, 1.00)
    noise = random.uniform(-0.05, 0.05)  # +/-5% per-branch variance
    price = base * chain_mult * (1 + noise)

    is_promotional = random.random() < OFFER_PROBABILITY
    if is_promotional:
        price *= random.uniform(0.80, 0.90)  # 10-20% off

    return round(price, 2), is_promotional


async def generate_prices() -> int:
    """
    Generate price documents for every product x store combination
    currently in the database.

    Prices are SYNTHETIC placeholders (illustrative KES base values with
    randomised per-chain/per-branch variance) - just enough realism to
    exercise the query engine and infographic pipeline end to end. Not
    sourced market data; should be superseded by the Phase 1 scraper
    (source="scraper") and later receipt OCR (source="receipt").

    Returns:
        Number of price documents inserted
    """
    db = await get_database()

    products = await db.products.find().to_list(length=None)
    stores = await db.stores.find().to_list(length=None)

    if not products or not stores:
        logger.warning("No products or stores found - seed those before generating prices")
        return 0

    valid_prices = []
    skipped_products = set()

    for product in products:
        base = BASE_PRICES.get(product["name"])
        if base is None:
            skipped_products.add(product["name"])
            continue

        for store in stores:
            price_kes, is_promotional = _compute_price(base, store["chain_name"])
            try:
                price = Price(
                    product_id=str(product["_id"]),
                    store_id=str(store["_id"]),
                    price_kes=price_kes,
                    source="seed",
                    is_promotional=is_promotional,
                    promotion_details="Special offer" if is_promotional else None,
                )
                valid_prices.append(price.dict())
            except Exception as e:
                logger.warning(f"Skipping invalid price data: {e}")
                continue

    if not valid_prices:
        logger.warning("No valid prices generated")
        return 0

    collection = db.prices
    # Clear existing prices (for clean seeding), same pattern as
    # load_products_from_json / load_stores_from_json above.
    await collection.delete_many({})
    result = await collection.insert_many(valid_prices)

    # Apply the same indexes defined for prices in models.py
    for keys, options in PRICE_INDEXES:
        await collection.create_index(keys, **options)

    logger.info(
        f"Generated {len(result.inserted_ids)} price documents across "
        f"{len(products) - len(skipped_products)} products x {len(stores)} stores"
    )
    if skipped_products:
        logger.warning(
            f"Skipped {len(skipped_products)} products with no BASE_PRICES "
            f"entry: {sorted(skipped_products)}"
        )

    return len(result.inserted_ids)


async def seed_database(products_file: str = None, stores_file: str = None) -> Dict[str, int]:
    """
    Seed the database with initial product, store, and price data.

    Args:
        products_file: Path to products JSON file (defaults to seeds/products_seed.json)
        stores_file: Path to stores JSON file (defaults to seeds/stores_seed.json)

    Returns:
        Dictionary with counts of loaded products, stores, and generated prices
    """
    if products_file is None:
        products_file = os.path.join(
            os.path.dirname(__file__), "seeds", "products_seed.json"
        )

    if stores_file is None:
        stores_file = os.path.join(
            os.path.dirname(__file__), "seeds", "stores_seed.json"
        )

    logger.info("Starting database seeding process...")

    # Load products
    product_count = await load_products_from_json(products_file)

    # Load stores
    store_count = await load_stores_from_json(stores_file)

    # Generate prices for every product x store combination
    price_count = await generate_prices()

    logger.info(
        f"Database seeding complete. Loaded {product_count} products, "
        f"{store_count} stores, generated {price_count} prices"
    )

    return {
        "products": product_count,
        "stores": store_count,
        "prices": price_count,
    }


def create_sample_seeds():
    """
    Create sample seed JSON files for demonstration.
    In a real implementation, these would be populated with actual 200 SKUs.

    NOTE: not called automatically from __main__ - running this would
    overwrite your real seeds/products_seed.json and seeds/stores_seed.json
    with the small 10/8-item samples below. Call it explicitly if you
    actually want to regenerate the sample files from scratch.
    """
    seeds_dir = os.path.join(os.path.dirname(__file__), "seeds")
    os.makedirs(seeds_dir, exist_ok=True)

    # Sample products data (core SKUs for Nairobi and Nyeri)
    sample_products = [
        {
            "name": "Maize Flour (Unga)",
            "category": "Grains and Cereals",
            "brand": "Ajiko",
            "sizes_variants": ["1kg", "2kg"],
            "swahili_aliases": ["unga"],
            "sheng_aliases": ["unga power"]
        },
        {
            "name": "Granulated Sugar",
            "category": "Sugars and Sweeteners",
            "brand": "Kabras",
            "sizes_variants": ["500g", "1kg", "2kg"],
            "swahili_aliases": ["sukari"],
            "sheng_aliases": ["sukari nguru"]
        },
        {
            "name": "Cooking Oil",
            "category": "Oils and Fats",
            "brand": "Bidco",
            "sizes_variants": ["500ml", "1L", "2L", "5L"],
            "swahili_aliases": ["mifuta ya kupaka"],
            "sheng_aliases": ["mother"]
        },
        {
            "name": "White Bread",
            "category": "Bakery",
            "brand": "Sunrise",
            "sizes_variants": ["400g", "800g"],
            "swahili_aliases": ["mkate"],
            "sheng_aliases": ["mkate wa mzungu"]
        },
        {
            "name": "Fresh Milk",
            "category": "Dairy",
            "brand": "Brookside",
            "sizes_variants": ["500ml", "1L", "2L"],
            "swahili_aliases": ["maziwa"],
            "sheng_aliases": ["maziwa kali"]
        },
        {
            "name": "Eggs",
            "category": "Dairy",
            "brand": "Kenchic",
            "sizes_variants": ["dozen (6 pcs)", "dozen (12 pcs)"],
            "swahili_aliases": ["mayai"],
            "sheng_aliases": ["mayai"]
        },
        {
            "name": "Rice",
            "category": "Grains and Cereals",
            "brand": "Mwea",
            "sizes_variants": ["1kg", "2kg", "5kg"],
            "swahili_aliases": ["mchele"],
            "sheng_aliases": ["mchele"]
        },
        {
            "name": "Tea Leaves",
            "category": "Beverages",
            "brand": "Ketepa",
            "sizes_variants": ["100g", "250g", "500g"],
            "swahili_aliases": ["chai"],
            "sheng_aliases": ["chai"]
        },
        {
            "name": "Salt",
            "category": "Spices and Seasonings",
            "brand": "Bamboo",
            "sizes_variants": ["500g", "1kg"],
            "swahili_aliases": ["chumvi"],
            "sheng_aliases": ["chumbo"]
        },
        {
            "name": "Wheat Flour",
            "category": "Grains and Cereals",
            "brand": "Grameen",
            "sizes_variants": ["1kg", "2kg"],
            "swahili_aliases": ["unga wa ngano"],
            "sheng_aliases": ["flour"]
        }
    ]

    # Sample stores data (chains in Nairobi and Nyeri)
    sample_stores = [
        {
            "chain_name": "Naivas",
            "branch_name": "Naivas Mega",
            "town": "Nairobi",
            "county": "Nairobi",
            "gps_latitude": -1.2921,
            "gps_longitude": 36.8219,
            "address": "Mega Plaza, Moi Avenue, Nairobi",
            "phone_number": "+254 700 000000"
        },
        {
            "chain_name": "Naivas",
            "branch_name": "Naivas Village Market",
            "town": "Nairobi",
            "county": "Nairobi",
            "gps_latitude": -1.2641,
            "gps_longitude": 36.8015,
            "address": "Village Market, Limuru Road",
            "phone_number": "+254 700 000001"
        },
        {
            "chain_name": "Carrefour",
            "branch_name": "Carrefour Hub Karen",
            "town": "Nairobi",
            "county": "Nairobi",
            "gps_latitude": -1.3321,
            "gps_longitude": 36.6927,
            "address": "The Hub Karen, Karen Road",
            "phone_number": "+254 700 000002"
        },
        {
            "chain_name": "Carrefour",
            "branch_name": "Carrefour Junction",
            "town": "Nairobi",
            "county": "Nairobi",
            "gps_latitude": -1.2835,
            "gps_longitude": 36.8245,
            "address": "Junction Mall, Naivasha Road",
            "phone_number": "+254 700 000003"
        },
        {
            "chain_name": "Quickmart",
            "branch_name": "Quickmart Westlands",
            "town": "Nairobi",
            "county": "Nairobi",
            "gps_latitude": -1.2678,
            "gps_longitude": 36.8015,
            "address": "Mpaka Road, Westlands",
            "phone_number": "+254 700 000004"
        },
        {
            "chain_name": "Quickmart",
            "branch_name": "Quickmart Kilimani",
            "town": "Nairobi",
            "county": "Nairobi",
            "gps_latitude": -1.3031,
            "gps_longitude": 36.7902,
            "address": "Argwings Kodhek Road, Kilimani",
            "phone_number": "+254 700 000005"
        },
        {
            "chain_name": "Chandarana",
            "branch_name": "Chandarana Nyeri",
            "town": "Nyeri",
            "county": "Nyeri",
            "gps_latitude": -0.4201,
            "gps_longitude": 36.9476,
            "address": "Kimathi Way, Nyeri Town",
            "phone_number": "+254 700 000006"
        },
        {
            "chain_name": "Naivas",
            "branch_name": "Naivas Nyeri",
            "town": "Nyeri",
            "county": "Nyeri",
            "gps_latitude": -0.4198,
            "gps_longitude": 36.9487,
            "address": "Mweiga Road, Nyeri",
            "phone_number": "+254 700 000007"
        }
    ]

    # Write products seed file
    products_file = os.path.join(seeds_dir, "products_seed.json")
    with open(products_file, 'w') as f:
        json.dump(sample_products, f, indent=2)
    logger.info(f"Created sample products seed file: {products_file}")

    # Write stores seed file
    stores_file = os.path.join(seeds_dir, "stores_seed.json")
    with open(stores_file, 'w') as f:
        json.dump(sample_stores, f, indent=2)
    logger.info(f"Created sample stores seed file: {stores_file}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(seed_database())