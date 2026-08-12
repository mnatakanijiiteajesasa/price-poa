from pymongo import MongoClient
from pipelines.attribute_extractor import AttributeExtractor, ExtractionRules

client = MongoClient("mongodb://pricepoa_dev:pricepoa_dev_password@mongo:27017/pricepoa?authSource=admin")
db = client.pricepoa

extractor = AttributeExtractor(ExtractionRules())  # uses your broadened known_categories

matched = 0
unmatched = 0

for product in db.products.find({"category": "general"}):
    category, subcategory = extractor._extract_category(product.get("name", ""))
    if category:
        matched += 1
        print(f"{product['name']!r} -> {category}")
    else:
        unmatched += 1

print(f"\nMatched: {matched} / {matched + unmatched}")