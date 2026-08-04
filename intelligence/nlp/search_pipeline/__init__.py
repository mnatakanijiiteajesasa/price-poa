"""
Search pipeline package for the intelligence service.
Contains modules for normalization, parsing, representation, vector search,
ranking, and retrieval.
"""

from .config import *
from .normalizer import *
from .query_parser import *
from .product_representation import *
from .vector_search import *
from .ranker import *
from .retrieval import *

__all__ = [
    # Config
    'get_config',
    'get_normalization_config',
    'get_query_parser_config',
    'get_vector_search_config',
    'get_ranker_config',
    'get_rapidfuzz_config',
    'get_hybrid_retrieval_config',

    # Normalizer
    'TextNormalizer',
    'NormalizedText',
    'normalize_text',
    'normalize_product_for_indexing',
    'normalize_query',

    # Query Parser
    'QueryParser',
    'ParsedQuery',
    'parse_query',
    'extract_brand_category_size_unit',
    'extract_keywords',

    # Product Representation
    'ProductEmbeddingDocument',
    'ProductRepresentationBuilder',
    'build_product_embedding_document',
    'product_to_embedding_text',

    # Vector Search
    'EnhancedVectorSearchService',
    'get_vector_search_service',

    # Ranker
    'BusinessRanker',
    'RankingScore',
    'RankedResult',
    'rank_search_results',

    # Retrieval
    'SearchPipeline',
    'search_products'
]