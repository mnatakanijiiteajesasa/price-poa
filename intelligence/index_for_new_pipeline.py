import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from intelligence.nlp.search_pipeline.vector_search import EnhancedVectorSearchService

# Load environment variables
load_dotenv()

MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://host.docker.internal:27017")
MONGODB_DB = os.getenv("MONGODB_DB", "pricepoa")
QDRANT_HOST = os.getenv("QDRANT_HOST", "host.docker.internal")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))

async def index_products():
    # Connect to MongoDB
    client = AsyncIOMotorClient(MONGODB_URI)
    db = client[MONGODB_DB]

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
