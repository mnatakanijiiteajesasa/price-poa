"""
Heterogeneous Product Graph Builder for PricePoa
Builds a heterogeneous graph from MongoDB and Qdrant data for GNN embeddings.
"""

import logging
from typing import Dict, List, Tuple, Optional, Set
from datetime import datetime, timedelta
import asyncio
from collections import defaultdict

import numpy as np
import torch
from torch_geometric.data import HeteroData
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from qdrant_client import QdrantClient
from qdrant_client.http import models as rest

logger = logging.getLogger(__name__)


class ProductGraphBuilder:
    """
    Builds a heterogeneous product graph for GNN embeddings.

    Node type: product
    Edge types:
    - same_category: products sharing same confirmed category
    - size_variant_of: products sharing same name + brand but differ in sizes_variants
    - substitutes: products in same category but different brand values
    - co_queried_with: products co-queried in same user session
    """

    def __init__(self,
                 mongodb_uri: str = None,
                 mongodb_db: str = None,
                 qdrant_host: str = None,
                 qdrant_port: int = None):
        """
        Initialize the ProductGraphBuilder.

        Args:
            mongodb_uri: MongoDB connection URI
            mongodb_db: MongoDB database name
            qdrant_host: Qdrant host
            qdrant_port: Qdrant port
        """
        # Load from environment if not provided
        import os
        from dotenv import load_dotenv
        load_dotenv()

        self.mongodb_uri = mongodb_uri or os.getenv("MONGODB_URI", "mongodb://host.docker.internal:27017")
        self.mongodb_db = mongodb_db or os.getenv("MONGODB_DB", "pricepoa")
        self.qdrant_host = qdrant_host or os.getenv("QDRANT_HOST", "host.docker.internal")
        self.qdrant_port = qdrant_port or int(os.getenv("QDRANT_PORT", "6333"))

        # Initialize connections (will be set up in async context)
        self.mongo_client: Optional[AsyncIOMotorClient] = None
        self.db: Optional[AsyncIOMotorDatabase] = None
        self.qdrant_client: Optional[QdrantClient] = None

        # Graph data
        self.product_ids: List[str] = []  # Original product IDs (ObjectIds as strings)
        self.product_id_to_index: Dict[str, int] = {}  # Mapping from product_id to node index
        self.node_features: Optional[np.ndarray] = None  # [num_products, 384] embedding matrix

        # Edge lists (will be stored as lists of [source_index, target_index] pairs)
        self.same_category_edges: List[List[int]] = []
        self.size_variant_edges: List[List[int]] = []
        self.substitutes_edges: List[List[int]] = []
        self.co_queried_edges: List[List[int]] = []

        # Statistics
        self.stats = {
            "total_products": 0,
            "products_with_embeddings": 0,
            "products_missing_embeddings": 0,
            "embeddings_missing_products": 0,
            "same_category_edges": 0,
            "size_variant_edges": 0,
            "substitutes_edges": 0,
            "co_queried_edges": 0
        }

    async def initialize_connections(self):
        """Initialize MongoDB and Qdrant connections."""
        try:
            # Initialize MongoDB connection
            self.mongo_client = AsyncIOMotorClient(self.mongodb_uri)
            self.db = self.mongo_client[self.mongodb_db]

            # Test connection
            await self.mongo_client.admin.command('ping')
            logger.info(f"Connected to MongoDB: {self.mongodb_uri}")

            # Initialize Qdrant connection
            self.qdrant_client = QdrantClient(host=self.qdrant_host, port=self.qdrant_port)

            # Test connection
            self.qdrant_client.get_collections()
            logger.info(f"Connected to Qdrant: {self.qdrant_host}:{self.qdrant_port}")

        except Exception as e:
            logger.error(f"Failed to initialize connections: {e}")
            raise

    async def close_connections(self):
        """Close MongoDB and Qdrant connections."""
        if self.mongo_client:
            self.mongo_client.close()
        # QdrantClient doesn't have an explicit close method

    async def load_and_align_nodes(self) -> bool:
        """
        Step 1: Load and align nodes from MongoDB and Qdrant.

        Returns:
            True if successful, False otherwise
        """
        try:
            logger.info("Loading products from MongoDB...")

            # Step 1.1: Query products collection for all documents with confirmed category
            # We'll consider all products for now, but in practice we might want to filter
            # for reviewed/trusted categories as mentioned in the guide
            products_cursor = self.db.products.find({})
            products = await products_cursor.to_list(length=None)

            logger.info(f"Found {len(products)} products in MongoDB")

            # Step 1.2: Query Qdrant product_embeddings collection
            logger.info("Fetching embeddings from Qdrant...")

            # Get all points from Qdrant collection
            # We'll scroll through all points to get embeddings
            all_points = []
            offset = None

            while True:
                if offset is None:
                    result = self.qdrant_client.scroll(
                        collection_name="product_embeddings",
                        limit=1000,
                        with_payload=True,
                        with_vectors=True
                    )
                else:
                    result = self.qdrant_client.scroll(
                        collection_name="product_embeddings",
                        limit=1000,
                        offset=offset,
                        with_payload=True,
                        with_vectors=True
                    )

                points, next_page_offset = result
                all_points.extend(points)

                if next_page_offset is None:
                    break
                offset = next_page_offset

            logger.info(f"Found {len(all_points)} embeddings in Qdrant")

            # Step 1.3: Build mapping from product_id to index and collect embeddings
            # First, build product_id -> index mapping from MongoDB products
            for i, product in enumerate(products):
                product_id = str(product["_id"])
                self.product_ids.append(product_id)
                self.product_id_to_index[product_id] = i

            # Initialize node features matrix
            num_products = len(self.product_ids)
            embedding_dim = 384  # From Qdrant / sentence-transformers model
            self.node_features = np.zeros((num_products, embedding_dim), dtype=np.float32)

            # Step 1.4: Match embeddings to products and build feature matrix
            products_with_embeddings = 0
            embeddings_matching_products = 0

            # Create a mapping from Qdrant payload product_id to vector
            qdrant_vectors = {}
            for point in all_points:
                payload = point.payload or {}
                qdrant_product_id = payload.get("product_id")
                if qdrant_product_id:
                    # Ensure it's a string for consistent comparison
                    qdrant_product_id = str(qdrant_product_id)
                    vector = point.vector
                    if vector is not None:
                        qdrant_vectors[qdrant_product_id] = vector

            # Match products to embeddings
            for i, product_id in enumerate(self.product_ids):
                if product_id in qdrant_vectors:
                    self.node_features[i] = qdrant_vectors[product_id]
                    products_with_embeddings += 1
                else:
                    # Product in MongoDB but missing from Qdrant
                    self.stats["products_missing_embeddings"] += 1
                    logger.warning(f"Product {product_id} found in MongoDB but missing from Qdrant")

            # Check for embeddings that don't match any product
            for qdrant_product_id in qdrant_vectors:
                if qdrant_product_id not in self.product_id_to_index:
                    self.stats["embeddings_missing_products"] += 1
                    logger.warning(f"Embedding found in Qdrant for product {qdrant_product_id} but no matching product in MongoDB")

            self.stats["total_products"] = num_products
            self.stats["products_with_embeddings"] = products_with_embeddings

            logger.info(f"Node alignment complete:")
            logger.info(f"  Total products: {num_products}")
            logger.info(f"  Products with embeddings: {products_with_embeddings}")
            logger.info(f"  Products missing embeddings: {self.stats['products_missing_embeddings']}")
            logger.info(f"  Embeddings missing products: {self.stats['embeddings_missing_products']}")

            # Return success if we have at least some products with embeddings
            return products_with_embeddings > 0

        except Exception as e:
            logger.error(f"Failed to load and align nodes: {e}")
            return False

    async def build_same_category_edges(self):
        """
        Step 2: Build edge type 1: same_category

        For every pair of products sharing the same confirmed category value,
        create an edge. Group by category first for efficiency.
        """
        try:
            logger.info("Building same_category edges...")

            # Get all products with their categories
            products_cursor = self.db.products.find(
                {},
                {"_id": 1, "category": 1}
            )
            products = await products_cursor.to_list(length=None)

            # Group products by category
            category_to_product_ids = defaultdict(list)

            for product in products:
                product_id = str(product["_id"])
                category = product.get("category", "").strip()

                # Only include products that have a category and are in our node mapping
                if category and product_id in self.product_id_to_index:
                    category_to_product_ids[category].append(product_id)

            logger.info(f"Found {len(category_to_product_ids)} distinct categories")

            # For each category, create edges between all pairs of products
            # Note: This creates a complete graph within each category
            same_category_edges = []

            for category, product_ids in category_to_product_ids.items():
                # Skip categories with only one product (no edges to create)
                if len(product_ids) < 2:
                    continue

                # Create all pairs within this category
                for i in range(len(product_ids)):
                    for j in range(i + 1, len(product_ids)):
                        product_id_1 = product_ids[i]
                        product_id_2 = product_ids[j]

                        # Both products should be in our mapping (we already filtered above)
                        if product_id_1 in self.product_id_to_index and product_id_2 in self.product_id_to_index:
                            index_1 = self.product_id_to_index[product_id_1]
                            index_2 = self.product_id_to_index[product_id_2]

                            # Add undirected edge (both directions)
                            same_category_edges.append([index_1, index_2])
                            same_category_edges.append([index_2, index_1])

            self.same_category_edges = same_category_edges
            self.stats["same_category_edges"] = len(same_category_edges)

            logger.info(f"Built {len(same_category_edges)} same_category edges")

        except Exception as e:
            logger.error(f"Failed to build same_category edges: {e}")
            raise

    async def build_size_variant_edges(self):
        """
        Step 3: Build edge type 2: size_variant_of

        Connect products that share the same name + brand but differ in sizes_variants.
        """
        try:
            logger.info("Building size_variant_of edges...")

            # Get products with name, brand, and sizes_variants
            products_cursor = self.db.products.find(
                {},
                {"_id": 1, "name": 1, "brand": 1, "sizes_variants": 1}
            )
            products = await products_cursor.to_list(length=None)

            # Group by (name, brand) combination
            name_brand_to_products = defaultdict(list)

            for product in products:
                product_id = str(product["_id"])
                name = product.get("name", "").strip()
                brand = product.get("brand") or ""  # Handle None brand
                brand = brand.strip()
                sizes_variants = product.get("sizes_variants", [])

                # Only include products that have name and are in our node mapping
                if name and product_id in self.product_id_to_index:
                    # Create a key from name and brand
                    key = (name.lower(), brand.lower())  # Case-insensitive matching
                    name_brand_to_products[key].append({
                        "product_id": product_id,
                        "sizes_variants": sizes_variants
                    })

            logger.info(f"Found {len(name_brand_to_products)} distinct name-brand combinations")

            # For each name-brand group, check if products differ in sizes_variants
            size_variant_edges = []

            for (name, brand), products_in_group in name_brand_to_products.items():
                # We need at least 2 products to compare
                if len(products_in_group) < 2:
                    continue

                # Compare each pair of products
                for i in range(len(products_in_group)):
                    for j in range(i + 1, len(products_in_group)):
                        product_1 = products_in_group[i]
                        product_2 = products_in_group[j]

                        product_id_1 = product_1["product_id"]
                        product_id_2 = product_2["product_id"]

                        # Both products should be in our mapping
                        if product_id_1 in self.product_id_to_index and product_id_2 in self.product_id_to_index:
                            sizes_1 = set(product_1["sizes_variants"])
                            sizes_2 = set(product_2["sizes_variants"])

                            # Check if they differ in sizes_variants
                            # We'll consider them variants if they have different size sets
                            # and neither is a subset of the other (to avoid connecting base product to itself)
                            if sizes_1 != sizes_2:
                                index_1 = self.product_id_to_index[product_id_1]
                                index_2 = self.product_id_to_index[product_id_2]

                                # Add undirected edge (both directions)
                                size_variant_edges.append([index_1, index_2])
                                size_variant_edges.append([index_2, index_1])

            self.size_variant_edges = size_variant_edges
            self.stats["size_variant_edges"] = len(size_variant_edges)

            logger.info(f"Built {len(size_variant_edges)} size_variant_of edges")

        except Exception as e:
            logger.error(f"Failed to build size_variant_of edges: {e}")
            raise

    async def build_substitutes_edges(self):
        """
        Step 4: Build edge type 3: substitutes (brand + category)

        Connect products in the same category but with different brand values.
        """
        try:
            logger.info("Building substitutes edges...")

            # Get products with category and brand
            products_cursor = self.db.products.find(
                {},
                {"_id": 1, "category": 1, "brand": 1}
            )
            products = await products_cursor.to_list(length=None)

            # Group by category
            category_to_products = defaultdict(list)

            for product in products:
                product_id = str(product["_id"])
                category = product.get("category", "").strip()
                brand = product.get("brand") or ""  # Handle None brand
                brand = brand.strip()

                # Only include products that have category and are in our node mapping
                if category and product_id in self.product_id_to_index:
                    category_to_products[category].append({
                        "product_id": product_id,
                        "brand": brand
                    })

            logger.info(f"Found {len(category_to_products)} distinct categories")

            # For each category, create edges between products with different brands
            substitutes_edges = []

            for category, products_in_category in category_to_products.items():
                # We need at least 2 products to compare
                if len(products_in_category) < 2:
                    continue

                # Compare each pair of products
                for i in range(len(products_in_category)):
                    for j in range(i + 1, len(products_in_category)):
                        product_1 = products_in_category[i]
                        product_2 = products_in_category[j]

                        product_id_1 = product_1["product_id"]
                        product_id_2 = product_2["product_id"]

                        brand_1 = product_1["brand"]
                        brand_2 = product_2["brand"]

                        # Both products should be in our mapping (we already filtered above)
                        # Only create edge if brands are different
                        if brand_1 != brand_2:
                            if product_id_1 in self.product_id_to_index and product_id_2 in self.product_id_to_index:
                                index_1 = self.product_id_to_index[product_id_1]
                                index_2 = self.product_id_to_index[product_id_2]

                                # Add undirected edge (both directions)
                                substitutes_edges.append([index_1, index_2])
                                substitutes_edges.append([index_2, index_1])

            self.substitutes_edges = substitutes_edges
            self.stats["substitutes_edges"] = len(substitutes_edges)

            logger.info(f"Built {len(substitutes_edges)} substitutes edges")

        except Exception as e:
            logger.error(f"Failed to build substitutes edges: {e}")
            raise

    async def build_co_queried_edges(self, session_window_minutes: int = 30):
        """
        Step 5: Build edge type 4: co_queried_with

        From query_logs, group by user_id within a rolling session window (e.g.
        same user_id, timestamps within N minutes of each other).
        For each session with 2+ resolved products, create edges between every
        pair of products in that session.

        Args:
            session_window_minutes: Session window size in minutes (default: 30)
        """
        try:
            logger.info("Building co_queried_with edges...")

            # Check if query_logs collection exists
            collection_names = await self.db.list_collection_names()
            if "query_logs" not in collection_names:
                logger.warning("query_logs collection does not exist, skipping co_queried_with edges")
                self.co_queried_edges = []
                self.stats["co_queried_edges"] = 0
                return

            # Query query_logs collection
            # We need to get query logs with resolved products
            # Based on the schema, we'll assume there's a way to know which products were resolved
            # For now, let's assume there's a "resolved_products" field or similar
            # Looking at the codebase, let's check what fields exist in query_logs

            # Let's first check one sample document to understand the structure
            sample_log = await self.db.query_logs.find_one({}, {"_id": 0})
            if sample_log:
                logger.info(f"Sample query_log document structure: {list(sample_log.keys())}")
            else:
                logger.info("No query logs found")
                self.co_queried_edges = []
                self.stats["co_queried_edges"] = 0
                return

            # Based on the guide, we need to group by user_id within a rolling session window
            # Let's assume the query_logs has: user_id, timestamp, and resolved_products fields
            # We'll need to adjust based on actual schema

            # For now, let's implement a basic version and we can refine based on actual data
            # We'll look for common fields that might indicate resolved products

            # Let's check what fields are commonly available
            sample_keys = set(sample_log.keys()) if sample_log else set()

            # Possible fields that might contain resolved products
            product_related_fields = [
                "resolved_products", "products", "product_ids",
                "search_results", "results", "matched_products"
            ]

            # Find which product-related field exists
            products_field = None
            for field in product_related_fields:
                if field in sample_keys:
                    products_field = field
                    break

            # If we don't find a specific products field, let's check if there are
            # individual product fields or we need to look at a different approach
            if not products_field:
                logger.warning("Could not identify products field in query_logs")
                # Let's try to look for arrays or objects that might contain product references
                for key, value in sample_log.items():
                    if isinstance(value, list) and len(value) > 0:
                        # Check if first element looks like a product ID or reference
                        if isinstance(value[0], str) and (len(value[0]) == 24 or value[0].startswith("product")):
                            products_field = key
                            break
                    elif isinstance(value, dict):
                        # Check if dict has product-like keys
                        if any(k in value for k in ["product_id", "_id", "id"]):
                            products_field = key
                            break

            if not products_field:
                logger.warning("Could not determine how to extract products from query_logs, skipping co_queried_with edges")
                self.co_queried_edges = []
                self.stats["co_queried_edges"] = 0
                return

            logger.info(f"Using '{products_field}' field to extract products from query_logs")

            # Now query the logs with necessary fields
            query_cursor = self.db.query_logs.find(
                {},
                {
                    "user_id": 1,
                    "timestamp": 1,
                    products_field: 1
                }
            ).sort("timestamp", 1)  # Sort by timestamp ascending for session processing

            query_logs = await query_cursor.to_list(length=None)

            logger.info(f"Found {len(query_logs)} query log entries")

            # Group by user_id and create sessions based on time window
            user_logs = defaultdict(list)

            for log in query_logs:
                user_id = log.get("user_id")
                timestamp = log.get("timestamp")
                products_field_value = log.get(products_field, [])

                if user_id is not None and timestamp is not None:
                    user_logs[user_id].append({
                        "timestamp": timestamp,
                        "products": products_field_value if isinstance(products_field_value, list) else []
                    })

            logger.info(f"Found logs for {len(user_logs)} unique users")

            # For each user, sort logs by timestamp and create sessions
            co_queried_edges = []
            session_window_seconds = session_window_minutes * 60

            for user_id, logs in user_logs.items():
                # Sort by timestamp
                logs_sorted = sorted(logs, key=lambda x: x["timestamp"])

                # Create sessions based on time window
                current_session = []
                session_start_time = None

                for log_entry in logs_sorted:
                    timestamp = log_entry["timestamp"]
                    products = log_entry["products"]

                    # Initialize session if needed
                    if session_start_time is None:
                        session_start_time = timestamp
                        current_session = []

                    # Check if this log entry falls within the session window
                    time_diff = (timestamp - session_start_time).total_seconds()

                    if time_diff <= session_window_seconds:
                        # Still in current session, add products
                        current_session.extend(products)
                    else:
                        # Session ended, process current session and start new one
                        if len(current_session) >= 2:
                            # Create edges between all pairs of products in session
                            await self._add_session_edges(current_session, co_queried_edges)

                        # Start new session
                        session_start_time = timestamp
                        current_session = products.copy() if isinstance(products, list) else []

                # Don't forget to process the last session
                if len(current_session) >= 2:
                    await self._add_session_edges(current_session, co_queried_edges)

            # Remove duplicate edges (since we'll add both directions) and convert to indices
            # We'll use a set to avoid duplicates, then convert back to list
            unique_edge_set = set()

            for edge in co_queried_edges:
                # Ensure we have valid product IDs
                if len(edge) == 2:
                    pid_1, pid_2 = edge[0], edge[1]
                    # Only include if both products are in our mapping
                    if pid_1 in self.product_id_to_index and pid_2 in self.product_id_to_index:
                        idx_1 = self.product_id_to_index[pid_1]
                        idx_2 = self.product_id_to_index[pid_2]

                        # Add both directions (undirected graph)
                        unique_edge_set.add((idx_1, idx_2))
                        unique_edge_set.add((idx_2, idx_1))

            # Convert set back to list format
            self.co_queried_edges = [[edge[0], edge[1]] for edge in unique_edge_set]
            self.stats["co_queried_edges"] = len(self.co_queried_edges)

            logger.info(f"Built {len(self.co_queried_edges)} co_queried_with edges")

        except Exception as e:
            logger.error(f"Failed to build co_queried_with edges: {e}")
            raise

    async def _add_session_edges(self, product_ids: List[str], edge_list: List[List[str]]):
        """
        Helper method to add edges for all pairs of products in a session.

        Args:
            product_ids: List of product IDs in the session
            edge_list: List to append edges to (each edge as [product_id_1, product_id_2])
        """
        # Remove duplicates and filter to only products we have in our mapping
        unique_product_ids = list(set(pid for pid in product_ids if pid in self.product_id_to_index))

        # Create edges between all pairs
        for i in range(len(unique_product_ids)):
            for j in range(i + 1, len(unique_product_ids)):
                pid_1 = unique_product_ids[i]
                pid_2 = unique_product_ids[j]
                edge_list.append([pid_1, pid_2])

    def build_heterodata(self) -> HeteroData:
        """
        Step 6: Assemble the HeteroData object.

        Returns:
            HeteroData object containing the graph
        """
        logger.info("Assembling HeteroData object...")

        if self.node_features is None:
            raise ValueError("Node features not available. Call load_and_align_nodes() first.")

        # Create HeteroData object
        graph = HeteroData()

        # Add node features and product IDs
        graph['product'].x = torch.from_numpy(self.node_features)
        graph['product'].product_id = self.product_ids  # Keep original IDs for later lookup

        # Add edge indices for each edge type
        # Each edge_index should be a [2, num_edges] LongTensor

        if self.same_category_edges:
            graph['product', 'same_category', 'product'].edge_index = torch.tensor(
                self.same_category_edges, dtype=torch.long
            ).t().contiguous()  # Transpose to [2, num_edges] and ensure contiguous

        if self.size_variant_edges:
            graph['product', 'size_variant_of', 'product'].edge_index = torch.tensor(
                self.size_variant_edges, dtype=torch.long
            ).t().contiguous()

        if self.substitutes_edges:
            graph['product', 'substitutes', 'product'].edge_index = torch.tensor(
                self.substitutes_edges, dtype=torch.long
            ).t().contiguous()

        if self.co_queried_edges:
            graph['product', 'co_queried_with', 'product'].edge_index = torch.tensor(
                self.co_queried_edges, dtype=torch.long
            ).t().contiguous()

        logger.info("HeteroData object assembled successfully")
        logger.info(f"  Node features shape: {graph['product'].x.shape}")
        logger.info(f"  Number of products: {len(self.product_ids)}")

        # Log edge counts
        edge_types = ['same_category', 'size_variant_of', 'substitutes', 'co_queried_with']
        for edge_type in edge_types:
            edge_key = ('product', edge_type, 'product')
            if edge_key in graph.edge_index_dict:
                edge_count = graph.edge_index_dict[edge_key].shape[1]
                logger.info(f"  {edge_type} edges: {edge_count}")
            else:
                logger.info(f"  {edge_type} edges: 0")

        return graph

    async def build_graph(self, session_window_minutes: int = 30) -> Optional[HeteroData]:
        """
        Build the complete product graph by executing all steps.

        Args:
            session_window_minutes: Session window size in minutes for co_queried_with edges

        Returns:
            HeteroData object or None if failed
        """
        try:
            logger.info("Starting product graph construction...")

            # Initialize connections
            await self.initialize_connections()

            try:
                # Step 1: Load and align nodes
                success = await self.load_and_align_nodes()
                if not success:
                    logger.error("Failed to load and align nodes")
                    return None

                # Step 2: Build same_category edges
                await self.build_same_category_edges()

                # Step 3: Build size_variant_of edges
                await self.build_size_variant_edges()

                # Step 4: Build substitutes edges
                await self.build_substitutes_edges()

                # Step 5: Build co_queried_with edges
                await self.build_co_queried_edges(session_window_minutes=session_window_minutes)

                # Step 6: Assemble HeteroData object
                graph = self.build_heterodata()

                # Log final statistics
                self._log_statistics()

                return graph

            finally:
                # Close connections
                await self.close_connections()

        except Exception as e:
            logger.error(f"Failed to build product graph: {e}")
            await self.close_connections()
            return None

    def _log_statistics(self):
        """Log graph construction statistics."""
        logger.info("=== Product Graph Construction Statistics ===")
        logger.info(f"Total products: {self.stats['total_products']}")
        logger.info(f"Products with embeddings: {self.stats['products_with_embeddings']}")
        logger.info(f"Products missing embeddings: {self.stats['products_missing_embeddings']}")
        logger.info(f"Embeddings missing products: {self.stats['embeddings_missing_products']}")
        logger.info(f"Same category edges: {self.stats['same_category_edges']}")
        logger.info(f"Size variant edges: {self.stats['size_variant_edges']}")
        logger.info(f"Substitutes edges: {self.stats['substitutes_edges']}")
        logger.info(f"Co-queried edges: {self.stats['co_queried_edges']}")
        logger.info("=" * 50)

    def get_statistics(self) -> Dict[str, int]:
        """
        Get graph construction statistics.

        Returns:
            Dictionary containing statistics
        """
        return self.stats.copy()


# Convenience function for external use
async def build_product_graph(
    mongodb_uri: str = None,
    mongodb_db: str = None,
    qdrant_host: str = None,
    qdrant_port: int = None,
    session_window_minutes: int = 30
) -> Optional[HeteroData]:
    """
    Build a product graph from MongoDB and Qdrant data.

    Args:
        mongodb_uri: MongoDB connection URI
        mongodb_db: MongoDB database name
        qdrant_host: Qdrant host
        qdrant_port: Qdrant port
        session_window_minutes: Session window size in minutes for co_queried_with edges

    Returns:
        HeteroData object or None if failed
    """
    builder = ProductGraphBuilder(
        mongodb_uri=mongodb_uri,
        mongodb_db=mongodb_db,
        qdrant_host=qdrant_host,
        qdrant_port=qdrant_port
    )

    return await builder.build_graph(session_window_minutes=session_window_minutes)


if __name__ == "__main__":
    # For testing/demonstration
    import asyncio
    import logging

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    async def main():
        graph = await build_product_graph()
        if graph is not None:
            print("Graph built successfully!")
            print(f"Number of nodes: {graph['product'].num_nodes}")
            print(f"Node feature shape: {graph['product'].x.shape}")

            # Print edge counts
            for edge_type in ['same_category', 'size_variant_of', 'substitutes', 'co_queried_with']:
                edge_key = ('product', edge_type, 'product')
                if edge_key in graph.edge_index_dict:
                    count = graph.edge_index_dict[edge_key].shape[1]
                    print(f"{edge_type} edges: {count}")
                else:
                    print(f"{edge_type} edges: 0")
        else:
            print("Failed to build graph")

    asyncio.run(main())