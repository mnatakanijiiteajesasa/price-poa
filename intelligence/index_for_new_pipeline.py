import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from intelligence.nlp.search_pipeline.vector_search import EnhancedVectorSearchService

async def index_products():
    # Connect to MongoDB
    client = AsyncIOMotorClient("mongodb://localhost:27017")
    db = client["pricepoa"]

    # Initialize the enhanced vector search service
    vector_service = EnhancedVectorSearchService()

    # Fetch all products
    products = await db.products.find({}).to_list(length=None)
    print(f"Found {len(products)} products to index")

    # Index them using the enhanced service
    indexed_count = await vector_service.index_products_batch(products)
    print(f"Successfully indexed {indexed_count} products")

    # Close connection
    client.close()

if __name__ == "__main__":
    asyncio.run(index_products())
