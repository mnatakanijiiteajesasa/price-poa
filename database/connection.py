"""
MongoDB connection manager using Motor async driver.
Handles connection setup and provides access to database collections.
"""
import os
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import ConnectionFailure
import logging

# Load environment variables from .env file if available (useful for local development runs)
try:
    from dotenv import load_dotenv
    current_dir = os.path.dirname(os.path.abspath(__file__))
    # Try local root folder
    dotenv_path = os.path.abspath(os.path.join(current_dir, '..', '.env'))
    if os.path.exists(dotenv_path):
        load_dotenv(dotenv_path)
    else:
        # Try one folder further up in case of sub-component execution
        dotenv_path = os.path.abspath(os.path.join(current_dir, '..', '..', '.env'))
        if os.path.exists(dotenv_path):
            load_dotenv(dotenv_path)
        else:
            load_dotenv()
except ImportError:
    pass

# Silence verbose PyMongo internal topology/connection debug heartbeats
logging.getLogger('pymongo').setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

class DatabaseConnection:
    """Manages MongoDB connection using Motor async driver."""

    _instance = None
    _client = None
    _database = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(DatabaseConnection, cls).__new__(cls)
        return cls._instance

    async def connect(self):
        """Establish connection to MongoDB."""
        try:
            mongodb_uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
            mongodb_db = os.getenv("MONGODB_DB", "pricepoa")

            self._client = AsyncIOMotorClient(mongodb_uri)

            # Verify connection
            await self._client.admin.command('ping')
            self._database = self._client[mongodb_db]

            logger.info(f"Connected to MongoDB: {mongodb_uri}, Database: {mongodb_db}")
            return self._database
        except ConnectionFailure as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error connecting to MongoDB: {e}")
            raise

    def get_database(self):
        """Get the database instance."""
        if self._database is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._database

    def get_collection(self, collection_name: str):
        """Get a specific collection."""
        db = self.get_database()
        return db[collection_name]

    async def close(self):
        """Close the MongoDB connection."""
        if self._client:
            self._client.close()
            self._client = None
            self._database = None
            logger.info("MongoDB connection closed")

# Global database connection instance
db_connection = DatabaseConnection()

# Convenience functions
async def get_database():
    """Get database instance, establishing connection if needed."""
    if db_connection._database is None:
        await db_connection.connect()
    return db_connection.get_database()

def get_collection(collection_name: str):
    """Get collection instance."""
    return db_connection.get_collection(collection_name)