from pymongo import MongoClient
from pipelines.attribute_extractor import AttributeExtractor, ExtractionRules

client = MongoClient("mongodb://pricepoa_dev:pricepoa_dev_password@mongo:27017/pricepoa?authSource=admin")
db = client.pricepoa

extractor = AttributeExtractor(ExtractionRules())

matched = 0
unmatched_ids = []

for product in db.products.find({"category": "general"}):
    category, subcategory = extractor._extract_category(product.get("name", ""))
    if category:
        db.products.update_one(
            {"_id": product["_id"]},
            {"$set": {
                "suggested_category": category,
                "suggested_subcategory": subcategory,
                "category_status": "suggested"  # vs "confirmed" once you review it
            }}
        )
        matched += 1
    else:
        unmatched_ids.append(product["_id"])
        db.products.update_one(
            {"_id": product["_id"]},
            {"$set": {"category_status": "unmatched"}}
        )

print(f"Suggested: {matched}")
print(f"Unmatched (needs full manual review): {len(unmatched_ids)}")