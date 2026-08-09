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
    chain: str = Field(..., min_length=1, max_length=100, description="Store chain name (e.g., Naivas)")
    branch: str = Field(..., min_length=1, max_length=200, description="Specific branch name")
    town: str = Field(..., min_length=1, max_length=100, description="Town/city location")
    county: str = Field(..., min_length=1, max_length=100, description="County location")
    gps_latitude: Optional[float] = Field(None, description="GPS latitude coordinate")
    gps_longitude: Optional[float] = Field(None, description="GPS longitude coordinate")
    address: Optional[str] = Field(None, max_length=500, description="Full store address")
    phone_number: Optional[str] = Field(None, max_length=20, description="Contact phone number")
    is_active: bool = Field(default=True, description="Whether store is currently operating")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @validator('chain', 'branch', 'town', 'county')
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
                "chain": "Naivas",
                "branch": "Naivas Mega",
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
        "required": ["chain", "branch", "town", "county"],
        "properties": {
            "chain": {
                "bsonType": "string",
                "description": "Store chain name - must be a string and is required"
            },
            "branch": {
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
    ([("chain", 1)], {"unique": False}),
    ([("town", 1)], {"unique": False}),
    ([("county", 1)], {"unique": False}),
    ([("chain", 1), ("town", 1)], {"unique": False}),
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

QUERY_LOG_INDEXES = [
    ([("user_id", 1)], {"unique": False}),
    ([("timestamp", -1)], {"unique": False}),  # Descending for recent-first queries
    ([("ip_address", 1)], {"unique": False}),
    ([("user_id", 1), ("timestamp", -1)], {"unique": False}),  # For user-specific queries over time
    ([("ip_address", 1), ("timestamp", -1)], {"unique": False}),  # For IP-specific queries over time
]


# Chat Message Schema
class ChatMessage(BaseModel):
    """Chat message schema for the chat_messages collection."""
    session_id: str = Field(..., description="Reference to chat session document ID")
    user_id: int = Field(..., description="Telegram user ID of the sender")
    message_text: str = Field(..., min_length=1, description="The message content")
    is_edited: bool = Field(default=False, description="Whether the message has been edited")
    edited_at: Optional[datetime] = Field(None, description="When the message was last edited")
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @validator('message_text')
    def message_text_must_not_be_empty(cls, v):
        if not v or not v.strip():
            raise ValueError('Message text cannot be empty')
        return v.strip()

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
        schema_extra = {
            "example": {
                "session_id": "60f7b3b5d8f1a434e8a6b5c1",
                "user_id": 123456789,
                "message_text": "Do you have fresh tomatoes today?",
                "is_edited": False,
                "created_at": "2026-08-04T10:30:00Z"
            }
        }



# Collection validation schemas for MongoDB
CHAT_SESSION_VALIDATOR = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["request_id", "buyer_user_id", "grocer_id", "grocer_telegram_user_id"],
        "properties": {
            "request_id": {
                "bsonType": "string",
                "description": "The ChatRequest this session was created from"
            },
            "buyer_user_id": {
                "bsonType": ["int", "long"],
                "description": "Telegram user ID of the buyer - must be an integer and is required"
            },
            "grocer_id": {
                "bsonType": "string",
                "description": "Reference to grocer document ID - must be a string and is required"
            },
            "grocer_telegram_user_id": {
                "bsonType": ["int", "long"],
                "description": "Telegram user ID of the grocer - denormalized for fast lookups"
            },
            "status": {
                "bsonType": "string",
                "description": "Session status: active, ended_by_buyer, ended_by_grocer, expired"
            },
            "created_at": {
                "bsonType": "date",
                "description": "Timestamp when chat session was created"
            },
            "updated_at": {
                "bsonType": "date",
                "description": "Timestamp when chat session was last updated"
            },
            "ended_at": {
                "bsonType": "date",
                "description": "Timestamp when chat session was ended"
            }
        }
    }
}

CHAT_MESSAGE_VALIDATOR = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["session_id", "user_id", "message_text"],
        "properties": {
            "session_id": {
                "bsonType": "string",
                "description": "Reference to chat session document ID"
            },
            "user_id": {
                "bsonType": ["int", "long"],
                "description": "Telegram user ID of the sender"
            },
            "message_text": {
                "bsonType": "string",
                "minLength": 1,
                "description": "The message content - must be a string and is required"
            },
            "is_edited": {
                "bsonType": "bool",
                "description": "Whether the message has been edited"
            },
            "edited_at": {
                "bsonType": "date",
                "description": "When the message was last edited"
            },
            "created_at": {
                "bsonType": "date",
                "description": "Timestamp when message was created"
            }
        }
    }
}

# Grocer Schema (individual sellers/vendors like mama mbogas)
class Grocer(BaseModel):
    """Grocer schema for individual sellers/vendors collection."""
    telegram_user_id: int = Field(..., description="Telegram user ID of the grocer")
    display_name: str = Field(..., min_length=1, max_length=100, description="Display name for the grocer")
    town: str = Field(..., min_length=1, max_length=100, description="Town/city location")
    categories: List[str] = Field(default_factory=list, description="Categories of goods sold (e.g., ['vegetables', 'fruits'])")
    description: Optional[str] = Field(None, max_length=500, description="Brief description of the grocer's business")
    verification_status: str = Field(default="pending", description="Verification status: pending, verified, rejected")
    opted_in_visible: bool = Field(default=True, description="Whether the grocer opts in to be visible in search results")
    is_banned: bool = Field(default=False, description="Whether the grocer is banned from the platform")
    rating_average: float = Field(default=0.0, ge=0.0, le=5.0, description="Average rating from reviews (0-5)")
    review_count: int = Field(default=0, ge=0, description="Number of reviews received")
    credibility_score: float = Field(default=0.0, ge=0.0, le=5.0, description="Computed credibility score (0-5)")
    is_flagged: bool = Field(default=False, description="Whether the grocer is flagged for potential review fraud")
    flagged_at: Optional[datetime] = Field(None, description="When the grocer was flagged")
    flag_reason: Optional[str] = Field(None, max_length=200, description="Reason for flagging")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @validator('telegram_user_id')
    def telegram_user_id_must_be_positive(cls, v):
        if v <= 0:
            raise ValueError('Telegram user ID must be positive')
        return v

    @validator('town')
    def town_must_not_be_empty(cls, v):
        if not v or not v.strip():
            raise ValueError('Town cannot be empty')
        return v.strip()

    @validator('verification_status')
    def validation_status_must_be_valid(cls, v):
        allowed_statuses = ["pending", "verified", "rejected"]
        if v not in allowed_statuses:
            raise ValueError(f'Verification status must be one of {allowed_statuses}')
        return v

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
        schema_extra = {
            "example": {
                "telegram_user_id": 123456789,
                "display_name": "Mama Mboga Nairobi",
                "town": "Nairobi",
                "categories": ["vegetables", "fruits", "herbs"],
                "description": "Fresh vegetables and fruits sourced daily from Wakulima Market",
                "verification_status": "verified",
                "opted_in_visible": True,
                "is_banned": False,
                "rating_average": 4.5,
                "review_count": 12,
                "credibility_score": 4.2,
                "is_flagged": False
            }
        }


# Grocer Review Schema
class GrocerReview(BaseModel):
    """Grocer review schema for the grocer_reviews collection."""
    grocer_id: str = Field(..., description="Reference to grocer document ID")
    reviewer_user_id: int = Field(..., description="Telegram user ID of the reviewer")
    rating: int = Field(..., ge=1, le=5, description="Rating from 1 to 5 stars")
    comment: Optional[str] = Field(None, max_length=500, description="Optional review comment")
    session_id: str = Field(..., description="Reference to chat session document ID this review is for")
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @validator('reviewer_user_id')
    def reviewer_user_id_must_be_positive(cls, v):
        if v <= 0:
            raise ValueError('Reviewer user ID must be positive')
        return v

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
        schema_extra = {
            "example": {
                "grocer_id": "60f7b3b5d8f1a434e8a6b5c1",
                "reviewer_user_id": 987654321,
                "rating": 5,
                "comment": "Excellent quality vegetables, always fresh!",
                "session_id": "60f7b3b5d8f1a434e8a6b5c2",
                "created_at": "2026-08-04T10:30:00Z"
            }
        }



# Collection validation schemas for MongoDB
GROCER_VALIDATOR = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["telegram_user_id", "display_name", "town"],
        "properties": {
            "telegram_user_id": {
                "bsonType": ["int", "long"],
                "description": "Telegram user ID of the grocer - must be an integer and is required"
            },
            "display_name": {
                "bsonType": "string",
                "description": "Display name for the grocer - must be a string and is required"
            },
            "town": {
                "bsonType": "string",
                "description": "Town/city location - must be a string and is required"
            },
            "categories": {
                "bsonType": "array",
                "items": {
                    "bsonType": "string"
                },
                "description": "Categories of goods sold"
            },
            "description": {
                "bsonType": "string",
                "description": "Brief description of the grocer's business"
            },
            "verification_status": {
                "bsonType": "string",
                "description": "Verification status: pending, verified, rejected"
            },
            "opted_in_visible": {
                "bsonType": "bool",
                "description": "Whether the grocer opts in to be visible in search results"
            },
            "is_banned": {
                "bsonType": "bool",
                "description": "Whether the grocer is banned from the platform"
            },
            "rating_average": {
                "bsonType": "double",
                "minimum": 0.0,
                "maximum": 5.0,
                "description": "Average rating from reviews (0-5)"
            },
            "review_count": {
                "bsonType": "int",
                "minimum": 0,
                "description": "Number of reviews received"
            },
            "credibility_score": {
                "bsonType": "double",
                "minimum": 0.0,
                "maximum": 5.0,
                "description": "Computed credibility score (0-5)"
            },
            "is_flagged": {
                "bsonType": "bool",
                "description": "Whether the grocer is flagged for potential review fraud"
            },
            "flagged_at": {
                "bsonType": "date",
                "description": "When the grocer was flagged"
            },
            "flag_reason": {
                "bsonType": "string",
                "description": "Reason for flagging"
            },
            "created_at": {
                "bsonType": "date",
                "description": "Timestamp when grocer was created"
            },
            "updated_at": {
                "bsonType": "date",
                "description": "Timestamp when grocer was last updated"
            }
        }
    }
}

GROCER_REVIEW_VALIDATOR = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["grocer_id", "reviewer_user_id", "rating", "session_id"],
        "properties": {
            "grocer_id": {
                "bsonType": "string",
                "description": "Reference to grocer document ID - must be a string and is required"
            },
            "reviewer_user_id": {
                "bsonType": ["int", "long"],
                "description": "Telegram user ID of the reviewer - must be an integer and is required"
            },
            "rating": {
                "bsonType": "int",
                "minimum": 1,
                "maximum": 5,
                "description": "Rating from 1 to 5 stars - must be an integer and is required"
            },
            "comment": {
                "bsonType": "string",
                "description": "Optional review comment"
            },
            "session_id": {
                "bsonType": "string",
                "description": "Reference to chat session document ID this review is for - must be a string and is required"
            },
            "created_at": {
                "bsonType": "date",
                "description": "Timestamp when review was created"
            }
        }
    }
}

# Chat Request Schema (for consent handshake between buyers and sellers)
class ChatRequest(BaseModel):
    """Chat request schema for the chat_requests collection."""
    buyer_user_id: int = Field(..., description="Telegram user ID of the buyer")
    grocer_id: str = Field(..., description="Reference to grocer document ID")
    status: str = Field(default="pending", description="Request status: pending, accepted, declined, expired")
    buyer_message: Optional[str] = Field(None, max_length=500, description="Optional message from buyer to grocer")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: datetime = Field(..., description="When the request expires (10 minutes from creation)")
    responded_at: Optional[datetime] = Field(None, description="When the grocer responded to the request")

    @validator('buyer_user_id')
    def buyer_user_id_must_be_positive(cls, v):
        if v <= 0:
            raise ValueError('Buyer user ID must be positive')
        return v

    @validator('status')
    def status_must_be_valid(cls, v):
        allowed_statuses = ["pending", "accepted", "declined", "expired"]
        if v not in allowed_statuses:
            raise ValueError(f'Status must be one of {allowed_statuses}')
        return v

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
        schema_extra = {
            "example": {
                "buyer_user_id": 111111111,
                "grocer_id": "60f7b3b5d8f1a434e8a6b5c1",
                "status": "pending",
                "buyer_message": "Hello, I'm interested in buying some tomatoes and onions. Do you have fresh ones available today?",
                "created_at": "2026-08-04T10:30:00Z",
                "expires_at": "2026-08-04T10:40:00Z"
            }
        }


CHAT_REQUEST_VALIDATOR = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["buyer_user_id", "grocer_id", "status", "expires_at"],
        "properties": {
            "buyer_user_id": {
                "bsonType": ["int", "long"],
                "description": "Telegram user ID of the buyer - must be an integer and is required"
            },
            "grocer_id": {
                "bsonType": "string",
                "description": "Reference to grocer document ID - must be a string and is required"
            },
            "status": {
                "bsonType": "string",
                "description": "Request status: pending, accepted, declined, expired"
            },
            "buyer_message": {
                "bsonType": "string",
                "description": "Optional message from buyer to grocer"
            },
            "created_at": {
                "bsonType": "date",
                "description": "Timestamp when request was created"
            },
            "expires_at": {
                "bsonType": "date",
                "description": "When the request expires"
            },
            "responded_at": {
                "bsonType": "date",
                "description": "When the grocer responded to the request"
            }
        }
    }
}


class DiscoverySearchContext(BaseModel):
    """
    The exact ranked seller list most recently shown to a buyer, so a
    numeric reply ("2") resolves to the grocer they actually saw rather
    than a fresh, possibly-different, re-query.
    """
    buyer_user_id: int = Field(..., description="Telegram user ID of the buyer")
    grocer_ids: List[str] = Field(..., description="Ranked order, index 0 == option '1'")
    search_term: Optional[str] = None
    location_filter: Optional[str] = None
    category_filter: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: datetime

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


# Updated Chat Session Schema (more general purpose for buyer-seller chats)
class ChatSession(BaseModel):
    """Chat session schema for the chat_sessions collection."""
    request_id: str = Field(..., description="The ChatRequest this session was created from")
    buyer_user_id: int = Field(..., description="Telegram user ID of the buyer")
    grocer_id: str = Field(..., description="Reference to grocer document ID")
    grocer_telegram_user_id: int = Field(..., description="Denormalized for fast relay/role lookups")
    status: str = Field(default="active", description="Session status: active, ended_by_buyer, ended_by_grocer, expired")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    ended_at: Optional[datetime] = Field(None, description="When the session was ended")

    @validator('buyer_user_id', 'grocer_telegram_user_id')
    def positive_id(cls, v):
        if v <= 0:
            raise ValueError('Telegram user ID must be positive')
        return v

    @validator('status')
    def status_must_be_valid(cls, v):
        allowed_statuses = ["active", "ended_by_buyer", "ended_by_grocer", "expired"]
        if v not in allowed_statuses:
            raise ValueError(f'Status must be one of {allowed_statuses}')
        return v

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
        schema_extra = {
            "example": {
                "buyer_user_id": 111111111,
                "grocer_id": "60f7b3b5d8f1a434e8a6b5c1",
                "status": "active",
                "created_at": "2026-08-04T10:30:00Z",
                "updated_at": "2026-08-04T10:35:00Z"
            }
        }



# Collection validation schemas for MongoDB
GROCER_INDEXES = [
    ([("telegram_user_id", 1)], {"unique": True}),  # Each Telegram user can only have one grocer profile
    ([("town", 1)], {"unique": False}),
    ([("verification_status", 1)], {"unique": False}),
    ([("opted_in_visible", 1)], {"unique": False}),
    ([("is_banned", 1)], {"unique": False}),
    ([("town", 1), ("verification_status", 1)], {"unique": False}),
    ([("categories", 1)], {"unique": False}),
    # Supports the discovery query's filter + sort in one index — filter
    # fields first, sort field last, matching what the webhook actually queries.
    (
        [("verification_status", 1), ("opted_in_visible", 1), ("is_banned", 1), ("credibility_score", -1)],
        {"unique": False},
    ),
]

GROCER_REVIEW_INDEXES = [
    ([("grocer_id", 1)], {"unique": False}),
    ([("reviewer_user_id", 1)], {"unique": False}),
    ([("created_at", -1)], {"unique": False}),  # Descending for recent-first queries
    ([("grocer_id", 1), ("created_at", -1)], {"unique": False}),  # For grocer-specific reviews over time
    ([("session_id", 1)], {"unique": True}),  # one review per completed session
]

CHAT_REQUEST_INDEXES = [
    ([("buyer_user_id", 1)], {"unique": False}),
    ([("grocer_id", 1)], {"unique": False}),
    ([("status", 1)], {"unique": False}),
    ([("created_at", -1)], {"unique": False}),  # Descending for recent-first queries
    ([("expires_at", 1)], {"unique": False}),  # For expiring old requests
    ([("buyer_user_id", 1), ("status", 1)], {"unique": False}),  # For user's pending requests
    ([("grocer_id", 1), ("status", 1)], {"unique": False}),  # For grocer's incoming requests
    # Only one PENDING request per buyer/grocer pair at a time.
    (
        [("buyer_user_id", 1), ("grocer_id", 1)],
        {"unique": True, "partialFilterExpression": {"status": "pending"}},
    ),
]

# Update CHAT_SESSION_INDEXES to include buyer/grocer indices
CHAT_SESSION_INDEXES = [
    ([("buyer_user_id", 1)], {"unique": False}),
    ([("grocer_id", 1)], {"unique": False}),
    ([("grocer_telegram_user_id", 1)], {"unique": False}),
    ([("status", 1)], {"unique": False}),
    ([("created_at", -1)], {"unique": False}),  # Descending for recent-first queries
    ([("request_id", 1)], {"unique": True}),
    # Partial-unique: only one ACTIVE session per buyer/grocer pair. This is
    # what actually makes the DuplicateKeyError in the ACCEPT handler mean
    # something — a plain index (the old version here) enforces nothing.
    (
        [("buyer_user_id", 1), ("grocer_id", 1)],
        {"unique": True, "partialFilterExpression": {"status": "active"}},
    ),
]

CHAT_MESSAGE_INDEXES = [
    ([("session_id", 1)], {"unique": False}),
    ([("user_id", 1)], {"unique": False}),
    ([("created_at", -1)], {"unique": False}),  # Descending for recent-first queries
    ([("session_id", 1), ("created_at", 1)], {"unique": False}),  # ascending — chronological replay within a session
]

DISCOVERY_CONTEXT_INDEXES = [
    ([("buyer_user_id", 1)], {"unique": True}),  # one live search context per buyer, overwritten each search
    ([("expires_at", 1)], {"unique": False}),
]