"""
Data seeding script for PricePoa database.
Loads initial product and store data from JSON fixtures.
"""
import asyncio
import json
import os
from typing import List, Dict, Any
from motor.motor_asyncio import AsyncIOMotorDatabase
import logging

from .connection import get_database
from .models import Product, Store

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


async def seed_database(products_file: str = None, stores_file: str = None) -> Dict[str, int]:
    """
    Seed the database with initial product and store data.

    Args:
        products_file: Path to products JSON file (defaults to seeds/products_seed.json)
        stores_file: Path to stores JSON file (defaults to seeds/stores_seed.json)

    Returns:
        Dictionary with counts of loaded products and stores
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

    logger.info(f"Database seeding complete. Loaded {product_count} products and {store_count} stores")

    return {
        "products": product_count,
        "stores": store_count
    }


def create_sample_seeds():
    """
    Create sample seed JSON files for demonstration.
    In a real implementation, these would be populated with actual 200 SKUs.
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

    # Create a script to generate more realistic data for 200 SKUs
    generate_script = os.path.join(seeds_dir, "generate_skus.py")
    with open(generate_script, 'w') as f:
        f.write('''#!/usr/bin/env python3
"""
Script to generate 200 core SKUs for PricePoa seed data.
Creates realistic product data for Nairobi and Nyeri markets.
"""
import json
import random
from typing import List, Dict

# Product categories and typical items for Kenyan grocery stores
CATEGORIES = {
    "Grains and Cereals": ["Maize Flour (Unga)", "Wheat Flour", "Rice", "Millet", "Sorghum"],
    "Sugars and Sweeteners": ["Granulated Sugar", "Brown Sugar", "Honey", "Jam"],
    "Oils and Fats": ["Cooking Oil", "Coconut Oil", "Butter", "Margarine", "Ghee"],
    "Bakery": ["White Bread", "Brown Bread", "Buns", "Muffins", "Cookies"],
    "Dairy": ["Fresh Milk", "Yogurt", "Cheese", "Eggs", "Cream"],
    "Beverages": ["Tea Leaves", "Coffee", "Juice", "Soft Drinks", "Water"],
    "Spices and Seasonings": ["Salt", "Black Pepper", "Curry Powder", "Royco", "Garlic"],
    "Canned Foods": ["Tomatoes", "Beans", "Tuna", "Peas", "Corn"],
    "Personal Care": ["Soap", "Toothpaste", "Shampoo", "Sanitary Pads", "Diapers"],
    "Household": ["Detergent", "Matches", "Candles", "Bags", "Buckets"]
}

BRANDS = {
    "Grains and Cereals": ["Ajiko", "Grameen", "Mwea", "Kenblest"],
    "Sugars and Sweeteners": ["Kabras", "Mumias", "West Kenya"],
    "Oils and Fats": ["Bidco", "Kapa Oils", "BIDCO", "Kericho Gold"],
    "Bakery": ["Sunrise", "Ace", "Mama Mboga", "Fresh Bake"],
    "Dairy": ["Brookside", "Kenchic", "Tuzo", "Sameer"],
    "Beverages": ["Ketepa", "Williamson", "Kereru", "Delmonte"],
    "Spices and Seasonings": ["Bamboo", "MDH", "Everest", "Badshah"],
    "Canned Foods": ["Alliance", "Pickles", "Tuna", "Blue Band"],
    "Personal Care": ["Protex", "Colgate", "Pepsodent", "Always", "Pampers"],
    "Household": ["OMO", "Surf", "Kims", "Harpic", "Glade"]
}

SWAHILI_ALIASES = {
    "Maize Flour (Unga)": "unga",
    "Wheat Flour": "unga wa ngano",
    "Rice": "mchele",
    "Millet": "mtama",
    "Sorghum": "mtama",
    "Granulated Sugar": "sukari",
    "Brown Sugar": "sukari bluu",
    "Honey": "asali",
    "Jam": "jamu",
    "Cooking Oil": "mifuta ya kupaka",
    "Coconut Oil": "mifuta ya nazi",
    "Butter": "boteri",
    "Margarine": "margareen",
    "Ghee": "samni",
    "White Bread": "mkate",
    "Brown Bread": "mkate bluu",
    "Buns": "buns",
    "Muffins": "mavuffin",
    "Cookies": "biscuiti",
    "Fresh Milk": "maziwa",
    "Yogurt": "yogerti",
    "Cheese": "jibini",
    "Eggs": "mayai",
    "Cream": "kribu",
    "Tea Leaves": "chai",
    "Coffee": "kahawa",
    "Juice": "jasho",
    "Soft Drinks": "soda",
    "Water": "maji",
    "Salt": "chumvi",
    "Black Pepper": "pilipili manga",
    "Curry Powder": "pavu ya karri",
    "Royco": "royco",
    "Garlic": "utunguu",
    "Tomatoes": "nyanya",
    "Beans": "maharagwe",
    "Tuna": "tuna",
    "Peas": " njegere",
    "Corn": " mahindi",
    "Soap": "sabuni",
    "Toothpaste": "paste ya meno",
    "Shampoo": "shampuu",
    "Sanitary Pads": "mapambano",
    "Diapers": "pampers",
    "Detergent": "deterjent",
    "Matches": "kichawi",
    "Candles": "mishipa",
    "Bags": " bendera",
    "Buckets": " baaki"
}

SHENG_ALIASES = {
    "Maize Flour (Unga)": "unga power",
    "Wheat Flour": "flour",
    "Rice": "mchele",
    "Millet": "mtama",
    "Sorghum": "mtama",
    "Granulated Sugar": "sukari nguru",
    "Brown Sugar": "sukari bluu",
    "Honey": "asali",
    "Jam": "jamu",
    "Cooking Oil": "mother",
    "Coconut Oil": "mother bluu",
    "Butter": "butter",
    "Margarine": "margarine",
    "Ghee": "samni",
    "White Bread": "mkate wa mzungu",
    "Brown Bread": "mkate bluu",
    "Buns": "buns",
    "Muffins": "mavuffin",
    "Cookies": "biscuiti",
    "Fresh Milk": "maziwa kali",
    "Yogurt": "yogurt",
    "Cheese": "cheez",
    "Eggs": "mayai",
    "Cream": "cream",
    "Tea Leaves": "chai",
    "Coffee": "kahawa",
    "Juice": "juice",
    "Soft Drinks": "soda",
    "Water": "maji",
    "Salt": "chumbo",
    "Black Pepper": "paprika",
    "Curry Powder": "pavu",
    "Royco": "royco",
    "Garlic": "itunguu",
    "Tomatoes": "tamatim",
    "Beans": "maharagwe",
    "Tuna": "tuna",
    "Peas": "ngere",
    "Corn": "mahindi",
    "Soap": "sabuni",
    "Toothpaste": "paste",
    "Shampoo": "shampoo",
    "Sanitary Pads": "pads",
    "Diapers": "pampers",
    "Detergent": "detergent",
    "Matches": "matches",
    "Candles": "candles",
    "Bags": "bags",
    "Buckets": "buckets"
}

def generate_product_id() -> str:
    """Generate a simple product ID."""
    return f"prod_{random.randint(1000, 9999)}"

def generate_products(count: int = 200) -> List[Dict]:
    """Generate specified number of product documents."""
    products = []
    used_names = set()

    for i in range(count):
        # Select random category
        category = random.choice(list(CATEGORIES.keys()))
        # Select random product from category
        base_name = random.choice(CATEGORIES[category])

        # Make name more specific if needed
        if base_name in used_names and len(used_names) < len(CATEGORIES[category]) * 2:
            variants = ["Premium", "Super", "Extra", "Fresh", "Pure", "Natural", "Select"]
            variant = random.choice(variants)
            name = f"{base_name} {variant}"
        else:
            name = base_name
            used_names.add(name)

        # Select brand
        brand = random.choice(BRANDS.get(category, ["Generic"]))

        # Generate sizes/variants
        size_options = ["500g", "1kg", "2kg", "500ml", "1L", "2L", "5L", "100g", "250g"]
        sizes_variants = random.sample(size_options, random.randint(1, 3))

        # Get aliases
        swahili_aliases = [SWAHILI_ALIASES.get(base_name, base_name.lower())]
        sheng_aliases = [SHENG_ALIASES.get(base_name, base_name.lower())]

        product = {
            "name": name,
            "category": category,
            "brand": brand,
            "sizes_variants": sizes_variants,
            "swahili_aliases": swahili_aliases,
            "sheng_aliases": sheng_aliases
        }
        products.append(product)

    return products

if __name__ == "__main__":
    # Generate 200 products
    products = generate_products(200)

    # Save to JSON file
    with open("products_seed.json", "w") as f:
        json.dump(products, f, indent=2)

    print(f"Generated {len(products)} products and saved to products_seed.json")
''')
    os.chmod(generate_script, 0o755)
    logger.info(f"Created SKU generation script: {generate_script}")

if __name__ == "__main__":
    create_sample_seeds()
    logger.info("Sample seed files created successfully")