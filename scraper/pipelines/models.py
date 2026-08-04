"""
Shared data models for the ingestion pipeline.
"""
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from datetime import datetime


@dataclass
class ExtractedAttributes:
    """Structured attributes extracted from raw product data."""
    brand: Optional[str] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    variant: Optional[str] = None
    flavour: Optional[str] = None
    package_type: Optional[str] = None
    size: Optional[float] = None
    unit: Optional[str] = None
    quantity: Optional[int] = None
    colour: Optional[str] = None
    raw_text: str = ""
    cleaned_text: str = ""


@dataclass
class CanonicalProduct:
    """Canonical product representation."""
    canonical_name: str
    brand: str
    category: str
    subcategory: str
    size: Optional[float] = None
    unit: Optional[str] = None
    package_type: Optional[str] = None
    variant: Optional[str] = None
    flavour: Optional[str] = None
    aliases: List[str] = field(default_factory=list)
    embedding_text: str = ""


@dataclass
class NormalizedProduct:
    """Fully normalized product ready for storage."""
    canonical_product: CanonicalProduct
    extracted_attributes: ExtractedAttributes
    canonical_id: Optional[str] = None
    store_id: Optional[str] = None
    price: Optional[float] = None
    source: Optional[str] = None
    product_url: Optional[str] = None
    is_promotional: bool = False
    promotion_details: Optional[str] = None
    verified_at: Optional[datetime] = None
    created_at: Optional[datetime] = field(default_factory=datetime.utcnow)