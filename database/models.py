"""
Database models and schemas for PricePoa collections.
Defines the structure for products, stores, and prices collections.
"""
from typing import Dict, Any, List, Optional
from datetime import datetime
from pydantic import BaseModel, Field, validator
import re

# Product Schema
class Product(BaseModel):
    """Product schema for the products collection."""
    name: str = Field(..., min_length=1, max_length=200, description="Product name")
    category: str = Field(..., min_length=1, max_length=100, description="Product category")
    brand: Optional[str] = Field(None, max_length=100, description="Brand name")
    sizes_variants: List[str] = Field(default_factory=list, description="Available sizes/variants")
    swahili_aliases: List[str] = Field(default_factory=list, description="Swahili product names")
    sheng_aliases: List[str] = Field(default_factory=list, description="Sheng product names")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @validator('name')
    def name_must_not_be_empty(cls, v):
        if not v or not v.strip():
            raise ValueError('Product name cannot be empty')
        return v.strip()

    @validator('category')
    def category_must_not_be_empty(cls, v):
        if not v or not v.strip():
            raise ValueError('Category cannot be empty')
        return v.strip()

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
        schema_extra = {
            "example": {
                "name": "Cooking Oil",
                "category": "Oils and Fats",
                "brand": "Bidco",
                "sizes_variants": ["500ml", "1L", "2L"],
                "swahili_aliases": ["mifuta ya kupaka"],
                "sheng_aliases": ["mother"]
            }
        }

# Store Schema
class Store(BaseModel):
    """Store schema for the stores collection."""
    chain_name: str = Field(..., min_length=1, max_length=100, description="Store chain name (e.g., Naivas)")
    branch_name: str = Field(..., min_length=1, max_length=200, description="Specific branch name")
    town: str = Field(..., min_length=1, max_length=100, description="Town/city location")
    county: str = Field(..., min_length=1, max_length=100, description="County location")
    gps_latitude: Optional[float] = Field(None, description="GPS latitude coordinate")
    gps_longitude: Optional[float] = Field(None, description="GPS longitude coordinate")
    address: Optional[str] = Field(None, max_length=500, description="Full store address")
    phone_number: Optional[str] = Field(None, max_length=20, description="Contact phone number")
    is_active: bool = Field(default=True, description="Whether store is currently operating")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @validator('chain_name', 'branch_name', 'town', 'county')
    def field_must_not_be_empty(cls, v):
        if not v or not v.strip():
            raise ValueError('Field cannot be empty')
        return v.strip()

    @validator('gps_latitude')
    def validate_latitude(cls, v):
        if v is not None and (v < -90 or v > 90):
            raise ValueError('Latitude must be between -90 and 90')
        return v

    @validator('gps_longitude')
    def validate_longitude(cls, v):
        if v is not None and (v < -180 or v > 180):
            raise ValueError('Longitude must be between -180 and 180')
        return v

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
        schema_extra = {
            "example": {
                "chain_name": "Naivas",
                "branch_name": "Naivas Mega",
                "town": "Nairobi",
                "county": "Nairobi",
                "gps_latitude": -1.2921,
                "gps_longitude": 36.8219,
                "address": "Mega Plaza, Moi Avenue",
                "phone_number": "+254 700 000000"
            }
        }

# Price Schema
class Price(BaseModel):
    """Price schema for the prices collection."""
    product_id: str = Field(..., description="Reference to product document ID")
    store_id: str = Field(..., description="Reference to store document ID")
    price_kes: float = Field(..., gt=0, description="Price in Kenyan Shillings")
    source: str = Field(..., max_length=100, description="Data source (e.g., 'naivas_online', 'manual')")
    verified_at: datetime = Field(default_factory=datetime.utcnow, description="When price was last verified")
    is_promotional: bool = Field(default=False, description="Whether price is promotional/discounted")
    promotion_details: Optional[str] = Field(None, max_length=200, description="Details of promotion if applicable")
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @validator('price_kes')
    def price_must_be_positive(cls, v):
        if v <= 0:
            raise ValueError('Price must be positive')
        return round(v, 2)  # Ensure 2 decimal places for currency

    @validator('source')
    def source_must_not_be_empty(cls, v):
        if not v or not v.strip():
            raise ValueError('Source cannot be empty')
        return v.strip()

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
        schema_extra = {
            "example": {
                "product_id": "60f7b3b5d8f1a434e8a6b5c1",
                "store_id": "60f7b3b5d8f1a434e8a6b5c2",
                "price_kes": 180.50,
                "source": "naivas_online",
                "verified_at": "2026-06-20T10:30:00Z",
                "is_promotional": True,
                "promotion_details": "Buy 1 Get 1 Free"
            }
        }

# Collection validation schemas for MongoDB
PRODUCT_VALIDATOR = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["name", "category"],
        "properties": {
            "name": {
                "bsonType": "string",
                "description": "Product name - must be a string and is required"
            },
            "category": {
                "bsonType": "string",
                "description": "Product category - must be a string and is required"
            },
            "brand": {
                "bsonType": "string",
                "description": "Brand name"
            },
            "sizes_variants": {
                "bsonType": "array",
                "items": {
                    "bsonType": "string"
                },
                "description": "Available sizes/variants"
            },
            "swahili_aliases": {
                "bsonType": "array",
                "items": {
                    "bsonType": "string"
                },
                "description": "Swahili product names"
            },
            "sheng_aliases": {
                "bsonType": "array",
                "items": {
                    "bsonType": "string"
                },
                "description": "Sheng product names"
            },
            "created_at": {
                "bsonType": "date",
                "description": "Timestamp when product was created"
            },
            "updated_at": {
                "bsonType": "date",
                "description": "Timestamp when product was last updated"
            }
        }
    }
}

STORE_VALIDATOR = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["chain_name", "branch_name", "town", "county"],
        "properties": {
            "chain_name": {
                "bsonType": "string",
                "description": "Store chain name - must be a string and is required"
            },
            "branch_name": {
                "bsonType": "string",
                "description": "Specific branch name - must be a string and is required"
            },
            "town": {
                "bsonType": "string",
                "description": "Town/city location - must be a string and is required"
            },
            "county": {
                "bsonType": "string",
                "description": "County location - must be a string and is required"
            },
            "gps_latitude": {
                "bsonType": "double",
                "description": "GPS latitude coordinate"
            },
            "gps_longitude": {
                "bsonType": "double",
                "description": "GPS longitude coordinate"
            },
            "address": {
                "bsonType": "string",
                "description": "Full store address"
            },
            "phone_number": {
                "bsonType": "string",
                "description": "Contact phone number"
            },
            "is_active": {
                "bsonType": "bool",
                "description": "Whether store is currently operating"
            },
            "created_at": {
                "bsonType": "date",
                "description": "Timestamp when store was created"
            },
            "updated_at": {
                "bsonType": "date",
                "description": "Timestamp when store was last updated"
            }
        }
    }
}

PRICE_VALIDATOR = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["product_id", "store_id", "price_kes", "source"],
        "properties": {
            "product_id": {
                "bsonType": "string",
                "description": "Reference to product document ID"
            },
            "store_id": {
                "bsonType": "string",
                "description": "Reference to store document ID"
            },
            "price_kes": {
                "bsonType": "double",
                "minimum": 0,
                "exclusiveMinimum": True,
                "description": "Price in Kenyan Shillings - must be a positive number"
            },
            "source": {
                "bsonType": "string",
                "description": "Data source - must be a string and is required"
            },
            "verified_at": {
                "bsonType": "date",
                "description": "When price was last verified"
            },
            "is_promotional": {
                "bsonType": "bool",
                "description": "Whether price is promotional/discounted"
            },
            "promotion_details": {
                "bsonType": "string",
                "description": "Details of promotion if applicable"
            },
            "created_at": {
                "bsonType": "date",
                "description": "Timestamp when price record was created"
            }
        }
    }
}

# Index definitions
PRODUCT_INDEXES = [
    ([("name", 1)], {"unique": False}),
    ([("category", 1)], {"unique": False}),
    ([("brand", 1)], {"unique": False}),
    ([("name", 1), ("category", 1)], {"unique": False}),
]

STORE_INDEXES = [
    ([("chain_name", 1)], {"unique": False}),
    ([("town", 1)], {"unique": False}),
    ([("county", 1)], {"unique": False}),
    ([("chain_name", 1), ("town", 1)], {"unique": False}),
    ([("is_active", 1)], {"unique": False}),
]

PRICE_INDEXES = [
    ([("product_id", 1)], {"unique": False}),
    ([("store_id", 1)], {"unique": False}),
    ([("verified_at", -1)], {"unique": False}),  # Descending for recent-first queries
    ([("product_id", 1), ("store_id", 1)], {"unique": False}),
    ([("source", 1)], {"unique": False}),
    ([("is_promotional", 1)], {"unique": False}),
    ([("product_id", 1), ("store_id", 1), ("verified_at", -1)], {"unique": False}),
]