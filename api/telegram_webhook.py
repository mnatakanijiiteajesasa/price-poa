"""
telegram_webhook.py
FastAPI webhook endpoint for the Telegram Bot API - receives messages, sends replies.
Handles chat sessions, reviews, and credibility scoring for grocers.
"""

from fastapi import APIRouter, Request, HTTPException, Header, BackgroundTasks
from fastapi.responses import JSONResponse
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone, timedelta
from bson import ObjectId
from pymongo.errors import DuplicateKeyError
from pydantic import BaseModel, Field, ValidationError

from telegram_bot import verify_telegram_secret, send_telegram_text, send_telegram_photo
from infographics.generator import (
    generate_shopping_list_image,
    generate_product_options_image,
)
from query_engine import get_product_prices, find_product_matches
from database.connection import get_database
from intelligence.nlp.product_matcher import find_product_fuzzy
from query_engine import find_product
from database.models import (
    ChatSession, ChatMessage, Grocer, ChatRequest,
    GrocerReview, DiscoverySearchContext, GROCER_VALIDATOR, GROCER_REVIEW_VALIDATOR,
    CHAT_SESSION_VALIDATOR, CHAT_MESSAGE_VALIDATOR
)

logger = logging.getLogger("uvicorn.error")

# Router
router = APIRouter()

# Webhook Models
class TelegramUpdate(BaseModel):
    update_id: int
    message: Optional[Dict[str, Any]] = None
    callback_query: Optional[Dict[str, Any]] = None

class TelegramMessage(BaseModel):
    message_id: int
    from_user: dict
    chat: dict
    date: int
    text: Optional[str] = None
    callback_query: Optional[Dict[str, Any]] = None

class ReviewRequest(BaseModel):
    grocer_id: str
    reviewer_user_id: int
    rating: int
    comment: Optional[str] = None
    session_id: str

class SessionEndedRequest(BaseModel):
    session_id: str
    ended_by: str  # "buyer" or "grocer"
    ended_at: datetime

class RatingPromptRequest(BaseModel):
    session_id: str
    buyer_user_id: int
    grocer_id: str
    chat_ended_at: datetime

# Helper Functions
def _to_object_id(value: str):
    """Best-effort conversion of a Mongo document ID string to ObjectId."""
    try:
        return ObjectId(value)
    except Exception:
        return value

async def find_active_session_for_user(db, chat_id: int) -> Optional[Dict[str, Any]]:
    """Find an active chat session where chat_id is either the buyer or the grocer."""
    return await db.chat_sessions.find_one({
        "status": "active",
        "$or": [
            {"buyer_user_id": chat_id},
            {"grocer_telegram_user_id": chat_id},
        ]
    })

async def verify_session_completion(session_id: str) -> bool:
    """Verify that a session exists and has been completed."""
    db = await get_database()
    session = await db.chat_sessions.find_one({"_id": session_id})
    if not session:
        return False

    # Check if session is ended
    return session.get("status") in ["ended_by_buyer", "ended_by_grocer", "expired"]

async def check_review_rate_limit(grocer_id: str, reviewer_user_id: int) -> bool:
    """
    Check if reviewer has already reviewed this grocer in the last 30 days.
    Returns True if they CAN review (not rate limited), False if they cannot.
    """
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)

    db = await get_database()
    existing_review = await db.grocer_reviews.find_one({
        "grocer_id": grocer_id,
        "reviewer_user_id": reviewer_user_id,
        "created_at": {"$gte": thirty_days_ago}
    })

    return existing_review is None

async def find_latest_ratable_session(db, buyer_user_id: int) -> Optional[Dict[str, Any]]:
    """
    The buyer's most recently ended session — used for text-based /rating,
    which has no session_id for the user to supply.
    """
    return await db.chat_sessions.find_one(
        {"buyer_user_id": buyer_user_id, "status": {"$in": ["ended_by_buyer", "ended_by_grocer"]}},
        sort=[("ended_at", -1)],
    )


async def apply_rating(db, user_id: int, session_id: str, score: int, comment: Optional[str] = None) -> str:
    """Validate and record a rating. Returns the message to send back to the user."""
    session = await db.chat_sessions.find_one({"_id": _to_object_id(session_id)})
    if not session:
        return "Sorry, we couldn't find that chat session."

    if session.get("buyer_user_id") != user_id:
        logger.warning(f"User {user_id} tried to rate session {session_id} they weren't the buyer on")
        return "Only the buyer in this chat can leave a rating."

    grocer_id = str(session["grocer_id"]) if session.get("grocer_id") else ""

    can_review = await check_review_rate_limit(grocer_id, user_id)
    if not can_review:
        return "You've already rated this seller recently. Thanks for your feedback!"

    review = GrocerReview(
        grocer_id=grocer_id,
        reviewer_user_id=user_id,
        rating=score,
        comment=comment,
        session_id=session_id,
        created_at=datetime.now(timezone.utc),
    )
    try:
        await db.grocer_reviews.insert_one(review.dict(by_alias=True))
    except DuplicateKeyError:
        return "You've already rated this seller for this chat. Thanks!"

    await update_grocer_credibility_score(grocer_id)
    await update_review_stats(grocer_id)

    return f"Thanks for rating {score}/5! Your feedback helps our marketplace."

async def calculate_credibility_score(grocer_id: str) -> float:
    """
    Calculate credibility score for a grocer based on:
    - Average rating (40%)
    - Number of reviews (20%, capped at 50 reviews = full score)
    - Tenure with decay (20%)
    - Verification status (10%)
    - Response rate (10%) - simplified as activity check

    Returns score from 0.0 to 5.0
    """
    db = await get_database()
    grocer = await db.grocers.find_one({"_id": _to_object_id(grocer_id)})
    if not grocer:
        return 0.0

    # Get reviews for this grocer
    reviews = await db.grocer_reviews.find({"grocer_id": grocer_id}).to_list(length=None)

    if not reviews:
        # New grocer - base score on verification status only
        verification_score = {
            "pending": 1.0,
            "verified": 3.0,
            "rejected": 0.0
        }.get(grocer.get("verification_status", "pending"), 1.0)

        # New grocer gets base score based on verification
        return min(max(verification_score, 0.0), 5.0)

    # Calculate average rating
    total_rating = sum(review["rating"] for review in reviews)
    avg_rating = total_rating / len(reviews)

    # Review count score (0-5 scale, max at 50 reviews)
    review_count_score = min(len(reviews) / 50 * 5, 5)

    # Tenure score with decay (older accounts get slightly less weight)
    account_age_days = (datetime.utcnow() - grocer["created_at"]).days
    # Peak at 365 days, then slight decay
    tenure_score = min(5.0, (min(account_age_days, 365) / 365) * 5)
    if account_age_days > 365:
        # Slight decay after 1 year
        decay_factor = 0.95 ** ((account_age_days - 365) / 365)
        tenure_score *= decay_factor

    # Verification score
    verification_score_map = {
        "pending": 1.0,
        "verified": 5.0,
        "rejected": 0.0
    }
    verification_score = verification_score_map.get(grocer.get("verification_status", "pending"), 1.0)

    # Response rate (simplified: check if grocer has been active recently)
    last_activity = grocer.get("updated_at", grocer["created_at"])
    days_since_active = (datetime.utcnow() - last_activity).days
    # Full points if active in last 30 days, decaying after that
    response_score = max(0.0, 5.0 - (days_since_active / 30))
    if days_since_active > 90:
        response_score = 0.0  # No points if inactive for over 90 days

    # Weighted composite score
    credibility_score = (
        avg_rating * 0.40 +          # 40% from average rating
        review_count_score * 0.20 +   # 20% from review count
        tenure_score * 0.20 +         # 20% from tenure with decay
        verification_score * 0.10 +   # 10% from verification status
        response_score * 0.10         # 10% from response rate
    )

    # Ensure score is between 0 and 5
    return min(max(credibility_score, 0.0), 5.0)

async def update_grocer_credibility_score(grocer_id: str):
    """Update the credibility score for a grocer in the database."""
    score = await calculate_credibility_score(grocer_id)
    db = await get_database()
    result = await db.grocers.update_one(
        {"_id": _to_object_id(grocer_id)},
        {"$set": {"credibility_score": score, "updated_at": datetime.utcnow()}}
    )
    logger.info(f"Updated credibility score for grocer {grocer_id}: {score}")
    return score

async def update_review_stats(grocer_id: str):
    """Update the grocer's review statistics (average rating and review count)."""
    try:
        db = await get_database()
        # Get all reviews for this grocer
        reviews = await db.grocer_reviews.find({"grocer_id": grocer_id}).to_list(length=None)

        if reviews:
            total_rating = sum(review["rating"] for review in reviews)
            avg_rating = total_rating / len(reviews)
            review_count = len(reviews)

            # Update grocer document
            await db.grocers.update_one(
                {"_id": _to_object_id(grocer_id)},
                {
                    "$set": {
                        "rating_average": round(avg_rating, 2),
                        "review_count": review_count,
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            logger.info(f"Updated review stats for grocer {grocer_id}: avg={avg_rating}, count={review_count}")
        else:
            # Reset to defaults if no reviews
            await db.grocers.update_one(
                {"_id": _to_object_id(grocer_id)},
                {
                    "$set": {
                        "rating_average": 0.0,
                        "review_count": 0,
                        "updated_at": datetime.utcnow()
                    }
                }
            )
    except Exception as e:
        logger.error(f"Error updating review stats for grocer {grocer_id}: {e}")

# Background task for nightly credibility score recalculation
async def recalculate_all_credibility_scores():
    """Nightly job to recalculate credibility scores for all grocers."""
    try:
        logger.info("Starting nightly credibility score recalculation")

        db = await get_database()
        # Get all grocers
        grocers = await db.grocers.find({}).to_list(length=None)
        updated_count = 0

        for grocer in grocers:
            grocer_id = str(grocer["_id"])
            score = await calculate_credibility_score(grocer_id)

            # Update the grocer's credibility score
            await db.grocers.update_one(
                {"_id": grocer["_id"]},
                {"$set": {"credibility_score": score, "updated_at": datetime.utcnow()}}
            )
            updated_count += 1

        logger.info(f"Completed nightly credibility score recalculation for {updated_count} grocers")

    except Exception as e:
        logger.error(f"Error in nightly credibility score recalculation: {e}")

# Anti-Gaming: Isolation Forest for detecting review bursts
# Note: In a real implementation, we would use scikit-learn's IsolationForest
# For now, we'll implement a simplified version that flags suspicious patterns
async def detect_review_bursts(grocer_id: str) -> bool:
    """
    Detect suspicious review bursts that might indicate gaming.
    Returns True if suspicious activity is detected.
    """
    try:
        db = await get_database()
        # Get reviews for this grocer in the last 7 days
        seven_days_ago = datetime.utcnow() - timedelta(days=7)
        recent_reviews = await db.grocer_reviews.find({
            "grocer_id": grocer_id,
            "created_at": {"$gte": seven_days_ago}
        }).to_list(length=None)

        # If more than 5 reviews in 7 days from new/no-review accounts, flag for review
        if len(recent_reviews) > 5:
            # Check if reviewers are new accounts (simplified check)
            new_reviewer_count = 0
            for review in recent_reviews:
                reviewer_id = review["reviewer_user_id"]
                # Check if reviewer has only left 1 review total (their first review)
                total_reviews_by_user = await db.grocer_reviews.count_documents(
                    {"reviewer_user_id": reviewer_id}
                )
                if total_reviews_by_user == 1:
                    new_reviewer_count += 1

            # If more than 60% of recent reviews are from first-time reviewers, flag
            if len(recent_reviews) > 0 and (new_reviewer_count / len(recent_reviews)) > 0.6:
                logger.warning(f"Potential review burst detected for grocer {grocer_id}")
                return True

        return False
    except Exception as e:
        logger.error(f"Error detecting review bursts for grocer {grocer_id}: {e}")
        return False

async def flag_grocer_for_review(grocer_id: str, reason: str):
    """Flag a grocer for manual review due to suspicious activity."""
    try:
        db = await get_database()
        await db.grocers.update_one(
            {"_id": _to_object_id(grocer_id)},
            {
                "$set": {
                    "is_flagged": True,
                    "flagged_at": datetime.utcnow(),
                    "flag_reason": reason,
                    "updated_at": datetime.utcnow()
                }
            }
        )
        logger.warning(f"Grocer {grocer_id} flagged for review: {reason}")
    except Exception as e:
        logger.error(f"Error flagging grocer {grocer_id}: {e}")


async def handle_telegram_message(message: Dict[str, Any], background_tasks: BackgroundTasks):
    """Handle incoming Telegram messages."""
    try:
        telegram_message = TelegramMessage(**message)
        user_id = telegram_message.from_user.get("id")
        chat_id = telegram_message.chat.get("id")
        text = telegram_message.text

        logger.info(f"Processing message from user {user_id}: {text}")

        # Handle commands
        if text and text.startswith("/"):
            await handle_telegram_command(text, user_id, chat_id, background_tasks)

    except Exception as e:
        logger.error(f"Error handling Telegram message: {e}")


async def handle_telegram_command(command: str, user_id: int, chat_id: int, background_tasks: BackgroundTasks):
    """Handle Telegram commands."""
    if command.startswith("/start"):
        # Handle start command - show help or initiate chat
        pass
    elif command.startswith("/review"):
        # Handle review command - this would be used when buyer wants to review a grocer
        pass

async def send_rating_prompt(buyer_user_id: int, grocer_id: str, session_id: str):
    """Send a rating prompt to the buyer after a chat session ends."""
    try:
        # Get grocer details for the message
        db = await get_database()
        grocer = await db.grocers.find_one({"_id": _to_object_id(grocer_id)})
        if not grocer:
            logger.warning(f"Could not find grocer {grocer_id} when sending rating prompt")
            return

        grocer_name = grocer.get("display_name") or "the grocer"

        # Create the rating prompt message
        message = (
            f"How was your chat with {grocer_name}?\n"
            f"Please rate your experience from 1 to 5 stars.\n"
            f"This helps us maintain quality in our marketplace.\n\n"
            f"To rate, send /rating <score> [optional comment]\n"
            f"Example: /rating 5 Great quality produce!"
        )

        # Only the buyer receives the rating prompt
        send_telegram_text(buyer_user_id, message)
        logger.info(f"Sent rating prompt to buyer {buyer_user_id} for grocer {grocer_id} after session {session_id}")

    except Exception as e:
        logger.error(f"Error sending rating prompt: {e}")


async def handle_callback_query(callback_query: Dict[str, Any]):
    """Handle Telegram callback queries, e.g. rating button presses."""
    try:
        data = callback_query.get("data", "")
        chat = callback_query.get("message", {}).get("chat", {})
        chat_id = chat.get("id")
        user_id = callback_query.get("from", {}).get("id")

        if not data.startswith("rate:"):
            logger.info(f"Ignoring unsupported callback query: {data}")
            return

        try:
            _, score_str, session_id = data.split(":")
            score = int(score_str)
        except (ValueError, IndexError):
            logger.warning(f"Malformed rating callback data: {data}")
            return

        if score not in range(1, 6):
            logger.warning(f"Rating out of range in callback data: {data}")
            return

        db = await get_database()
        message_text = await apply_rating(db, user_id, session_id, score)
        send_telegram_text(chat_id, message_text)
        logger.info(f"Recorded rating {score}/5 from user {user_id} for session {session_id}")
    except Exception as e:
        logger.error(f"Error handling callback query: {e}")


def extract_product_names_from_shopping_list(text: str) -> List[str]:
    """
    Extract potential product names from a shopping list query.

    Args:
        text: The user's message text

    Returns:
        List of potential product names to look up
    """
    # Convert to lowercase for processing
    text_lower = text.lower().strip()

    # Remove common shopping-related phrases
    shopping_indicators = [
        "i want to buy", "i need to buy", "can you show me prices for",
        "shopping list:", "buy", "get", "need", "want", "show me prices for",
        "what is the price of", "what are the prices of", "prices for",
        " cost", " costs", "price", "prices"
    ]

    for indicator in shopping_indicators:
        text_lower = text_lower.replace(indicator, "")

    # Split by common delimiters
    # First replace common conjunctions and punctuation with spaces
    for delim in [",", "&", "and", "plus", "+"]:
        text_lower = text_lower.replace(delim, " | ")

    # Split by the pipe delimiter we introduced
    parts = [part.strip() for part in text_lower.split("|") if part.strip()]

    # Extract meaningful terms
    terms = []

    # First, add the cleaned text itself if it's substantial
    cleaned_text = text_lower.strip()
    if len(cleaned_text) > 2 and not cleaned_text.isdigit():
        terms.append(cleaned_text)

    # Extract meaningful multi-word combinations (2-3 words)
    words_with_pos = text_lower.split()
    for i in range(len(words_with_pos)):
        # 2-word combinations
        if i < len(words_with_pos) - 1:
            two_word = f"{words_with_pos[i]} {words_with_pos[i+1]}"
            two_word = two_word.strip(".,!?;:")
            # Only add if it's not just common words and has sufficient length
            if len(two_word) > 3 and not _is_meaningless_phrase(two_word):
                terms.append(two_word)
        # 3-word combinations
        if i < len(words_with_pos) - 2:
            three_word = f"{words_with_pos[i]} {words_with_pos[i+1]} {words_with_pos[i+2]}"
            three_word = three_word.strip(".,!?;:")
            # Only add if it's not just common words and has sufficient length
            if len(three_word) > 3 and not _is_meaningless_phrase(three_word):
                terms.append(three_word)

    # Extract single meaningful words (nouns, etc.) but be very selective
    # Skip extremely common words that are unlikely to be product names
    stop_words = {"a", "an", "the", "of", "for", "in", "on", "at", "to", "from",
                  "with", "by", "is", "are", "was", "were", "be", "been", "being",
                  "have", "has", "had", "do", "does", "did", "will", "would", "should",
                  "could", "may", "might", "must", "can", "and", "or", "but", "in",
                  "on", "at", "to", "for", "of", "with", "by", "about", "like",
                  "through", "over", "before", "between", "after", "since", "without",
                  "under", "within", "along", "following", "across", "behind",
                  "beyond", "plus", "except", "but", "up", "down", "in", "out",
                  "on", "off", "over", "under", "again", "further", "then", "once",
                  "here", "there", "when", "where", "why", "how", "all", "any",
                  "both", "each", "few", "more", "most", "other", "some", "such",
                  "no", "nor", "not", "only", "own", "same", "so", "than", "too",
                  "very", "s", "t", "can", "will", "just", "don", "should", "now"}

    # Also skip units and quantities as they're handled elsewhere
    unit_words = {"kg", "g", "mg", "ml", "l", "ltr", "liter", "litre",
                  "piece", "pieces", "pc", "pcs", "bottle", "bottles",
                  "packet", "packets", "pack", "packs", "can", "cans",
                  "jar", "jars", "tin", "tins", "bag", "bags",
                  "pouch", "pouches", "box", "boxes", "dozen"}

    # Descriptor words that are only meaningful as part of a phrase, not standalone
    descriptor_words = {"baby", "premium", "large", "small", "fresh", "organic",
                        "natural", "new", "classic", "original", "extra",
                        "super", "mega", "mini", "jumbo", "value", "family",
                        "regular", "select", "choice", "quality", "special"}

    for part in parts:
        # Split by spaces and consider each word
        subparts = part.split()
        for word in subparts:
            # Remove any trailing/leading punctuation
            word = word.strip(".,!?;:")
            # Only consider words that are not too short, not stop words, not units, and not descriptors
            if (len(word) > 2 and
                word not in stop_words and
                word not in unit_words and
                word not in descriptor_words and   # Skip descriptor words as standalone terms
                not word.isdigit()):  # Not just a number
                terms.append(word)

    # Remove duplicates while preserving order
    seen = set()
    unique_terms = []
    for term in terms:
        if term not in seen:
            seen.add(term)
            unique_terms.append(term)

    return unique_terms


def _is_meaningless_phrase(phrase: str) -> bool:
    """
    Check if a phrase is likely to be meaningless for product matching.

    Args:
        phrase: The phrase to check

    Returns:
        True if the phrase is likely meaningless, False otherwise
    """
    # Common meaningless phrases
    meaningless_patterns = [
        "the ", "and ", "or ", "but ", "in ", "on ", "at ", "to ", "for ",
        "of ", "with ", "by ", "is ", "are ", "was ", "were ", "be ", "been ",
        "have ", "has ", "had ", "do ", "does ", "did ", "will ", "would ",
        "should ", "could ", "may ", "might ", "must ", "can ", "it ", "its ",
        "this ", "that ", "these ", "those ", "he ", "she ", "they ", "we ",
        "you ", "i ", "me ", "him ", "her ", "us ", "them "
    ]

    phrase_lower = phrase.lower() + " "  # Add space to match patterns
    for pattern in meaningless_patterns:
        if phrase_lower.startswith(pattern):
            return True

    # Also check if it's mostly just common words
    words = phrase.split()
    if len(words) > 0:
        meaningless_words = {"the", "and", "or", "but", "in", "on", "at", "to", "for",
                           "of", "with", "by", "is", "are", "was", "were", "be", "been",
                           "have", "has", "had", "do", "does", "did", "will", "would",
                           "should", "could", "may", "might", "must", "can", "it", "its",
                           "this", "that", "these", "those", "he", "she", "they", "we",
                           "you", "i", "me", "him", "her", "us", "them", "a", "an"}
        meaningful_count = sum(1 for w in words if w.lower() not in meaningless_words)
        # If less than 30% of words are meaningful, consider the phrase meaningless
        if len(words) > 0 and (meaningful_count / len(words)) < 0.3:
            return True

    return False


def extract_meaningful_product_terms(text: str) -> List[str]:
    """
    Extract and filter product terms, removing quantities, units, and non-meaningful terms.
    This helps determine if we have multiple products vs false positives.

    Args:
        text: The user's message text

    Returns:
        List of filtered product terms likely to be actual product names
    """
    # First extract all potential terms
    all_terms = extract_product_names_from_shopping_list(text)

    # Filter out terms that look like quantities or units
    filtered_terms = []
    import re
    unit_words = {"kg", "g", "mg", "ml", "l", "ltr", "liter", "litre",
                  "piece", "pieces", "pc", "pcs", "bottle", "bottles",
                  "packet", "packets", "pack", "packs", "can", "cans",
                  "jar", "jars", "tin", "tins", "bag", "bags",
                  "pouch", "pouches", "box", "boxes", "dozen"}

    for term in all_terms:
        term_lower = term.lower().strip()

        # Skip if it's just a number
        if term.isdigit():
            continue

        # Skip if it looks like a quantity (number + unit)
        # e.g., "2kg", "1.5l", "500g"
        if re.match(r'^\d+(\.\d+)?\s*(kg|g|mg|ml|l|ltr|liter|litre|piece|pieces|pc|pcs|bottle|bottles|packet|packets|pack|packs|can|cans|jar|jars|tin|tins|bag|bags|pouch|pouches|box|boxes|dozen)\s*$', term_lower):
            continue

        # Skip if it's just a unit
        if term_lower in unit_words:
            continue

        # Skip if it's too short (likely not a meaningful product name)
        if len(term_lower) < 3:
            continue

        # Skip if it's a common word that is unlikely to be a product name
        common_words = {"and", "or", "but", "in", "on", "at", "to", "for", "of", "with", "by", "is", "are", "was", "were", "be", "been", "have", "has", "had", "do", "does", "did", "will", "would", "should", "could", "may", "might", "must", "can", "it", "its", "this", "that", "these", "those", "he", "she", "they", "we", "you", "i", "me", "him", "her", "us", "them", "a", "an", "the"}
        if term_lower in common_words:
            continue

        filtered_terms.append(term)

    # Remove duplicates while preserving order
    seen = set()
    unique_filtered_terms = []
    for term in filtered_terms:
        if term not in seen:
            seen.add(term)
            unique_filtered_terms.append(term)

    return unique_filtered_terms


async def find_alternative_product_in_store(db, product: dict, store_id: str) -> Optional[Dict[str, Any]]:
    """
    Find an alternative product in a specific store when the exact product is not available.
    Looks for products with similar names or aliases that ARE available in the store.

    Args:
        db: Database connection
        product: The original product dictionary
        store_id: The store ID to check for alternatives

    Returns:
        Alternative product dictionary or None if not found
    """
    try:
        product_name = product.get("name", "").lower()
        if not product_name:
            return None

        # Get product aliases
        swahili_aliases = [alias.lower() for alias in product.get("swahili_aliases", [])]
        sheng_aliases = [alias.lower() for alias in product.get("sheng_aliases", [])]

        # All possible names to search for
        search_terms = [product_name] + swahili_aliases + sheng_aliases

        # Remove duplicates and empty strings
        search_terms = list(set([term.strip() for term in search_terms if term.strip()]))

        # Search for products in the store that match our search terms
        for term in search_terms:
            # Build query for products matching this term in name or aliases
            query = {
                "$or": [
                    {"name": {"$regex": f"^{term}$", "$options": "i"}},
                    {"swahili_aliases": {"$elemMatch": {"$regex": f"^{term}$", "$options": "i"}}},
                    {"sheng_aliases": {"$elemMatch": {"$regex": f"^{term}$", "$options": "i"}}}
                ]
            }

            # Find matching products
            matching_products = await db.products.find(query).to_list(length=None)

            # Check which of these products have prices in the target store
            for candidate_product in matching_products:
                candidate_id = str(candidate_product["_id"])
                # Check if this product has a price in the store
                price_count = await db.prices.count_documents({
                    "product_id": candidate_id,
                    "store_id": store_id
                })
                if price_count > 0:
                    return candidate_product

        return None
    except Exception as e:
        logger.error(f"Error finding alternative product: {e}")
        return None


async def get_products_for_shopping_list(db, product_names: List[str]) -> List[Dict[str, Any]]:
    """
    Look up products by name for a shopping list.
    For each product name, selects the cheapest matching product variant.

    Args:
        db: Database connection
        product_names: List of product names to look up

    Returns:
        List of product dictionaries that were found
    """
    products = []
    found_names = set()  # To avoid duplicates

    for name in product_names:
        if not name or len(name.strip()) < 2:
            continue

        # Get multiple product matches by confidence
        matches = await find_product_fuzzy(db, name.strip(), threshold=0.3)
        # Take top 5 matches by confidence to consider for price-based selection
        matches = matches[:5] if len(matches) > 5 else matches

        best_match = None
        best_price = float('inf')  # Start with infinity as worst price

        # Evaluate each match to find the cheapest one
        for match in matches:
            product_id = match["product_id"]
            # Skip if we've already added this product
            if product_id in found_names:
                continue

            # Get prices for this product to determine its cost
            try:
                # Create a minimal product dict for get_product_prices
                product_for_pricing = {"_id": product_id}
                prices_data = await get_product_prices(db, product_for_pricing)

                if prices_data and "stores" in prices_data and prices_data["stores"]:
                    # Extract prices and find the minimum
                    min_price = float('inf')
                    for store in prices_data["stores"]:
                        price_str = store.get("price", "0 KES")
                        # Parse the price (e.g., "100 KES" -> 100)
                        try:
                            price_value = float(price_str.split()[0])
                            if price_value < min_price:
                                min_price = price_value
                        except (ValueError, IndexError):
                            # If we can't parse, skip this store's price
                            continue

                    # If we found valid prices, use the minimum
                    if min_price != float('inf'):
                        if min_price < best_price:
                            best_price = min_price
                            best_match = match
                # If no prices found, we might still want to consider the product
                # but give it a high price so it's less likely to be selected
                elif best_price == float('inf'):  # Only if we haven't found any priced products yet
                    best_price = float('inf')  # Keep as infinity
                    best_match = match  # Fallback to this match if no others have prices

            except Exception as e:
                logger.error(f"Error processing product match {product_id}: {e}")
                continue

        # If we found a best match, get the full product and add it
        if best_match:
            try:
                product = await db.products.find_one({"_id": ObjectId(best_match["product_id"])})
                if product and str(product["_id"]) not in found_names:
                    products.append(product)
                    found_names.add(str(product["_id"]))
            except Exception as e:
                logger.error(f"Error fetching product {best_match['product_id']}: {e}")
        else:
            # Fallback to the original behavior if our new method didn't work
            product = await find_product(db, name.strip())
            if product and str(product["_id"]) not in found_names:
                products.append(product)
                found_names.add(str(product["_id"]))

    return products


async def get_shopping_list_data(db, products: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Get pricing data for a list of products across stores and format for shopping list image.

    Args:
        db: Database connection
        products: List of product dictionaries

    Returns:
        Dictionary formatted for the shopping list image generator
    """
    if not products:
        return {
            "stores": [],
            "recommendation": "No products found",
            "savings": "",
            "date": datetime.now().strftime("%Y-%m-%d")
        }

    # Get all active stores first
    stores_cursor = db.stores.find({"is_active": True})
    stores = await stores_cursor.to_list(length=None)

    if not stores:
        return {
            "stores": [],
            "recommendation": "No stores found",
            "savings": "",
            "date": datetime.now().strftime("%Y-%m-%d")
        }

    # Get active store IDs for filtering
    active_store_ids = [str(store["_id"]) for store in stores]

    # Drop products with no pricing data in any of the active stores
    priced_products = []
    for product in products:
        has_price = await db.prices.count_documents({
            "product_id": str(product["_id"]),
            "store_id": {"$in": active_store_ids}
        }) > 0
        if has_price:
            priced_products.append(product)
        else:
            logger.info(f"Dropping product with no pricing data in any active store: {product.get('name', 'Unknown')}")
    products = priced_products

    if not products:
        return {
            "stores": [],
            "recommendation": "No pricing data available for any product in your list",
            "savings": "",
            "date": datetime.now().strftime("%Y-%m-%d")
        }

    # For each store, get prices for all products and calculate total
    store_totals = []
    store_items = {}  # Store ID -> list of items with prices

    for store in stores:
        store_id = str(store["_id"])
        store_name = f"{store['chain']} - {store['branch']}"

        # Initialize for this store
        store_items[store_id] = []
        total_price = 0.0
        found_products = 0

        # For each product, get its price at this store
        for product in products:
            product_id = str(product["_id"])
            product_name = product["name"]

            # Look for price of this product at this store
            price_cursor = db.prices.find({
                "product_id": product_id,
                "store_id": store_id
            }).sort("verified_at", -1).limit(1)  # Get most recent price

            price_doc = await price_cursor.to_list(length=1)

            if price_doc:
                price = price_doc[0]
                price_kes = price["price_kes"]
                is_promotional = price.get("is_promotional", False)

                # Format price
                price_str = f"{int(price_kes)} KES" if price_kes == int(price_kes) else f"{price_kes:.1f} KES"

                # Add to store items
                store_items[store_id].append({
                    "name": product_name,
                    "price": price_str,
                    "offer": is_promotional
                })

                total_price += price_kes
                found_products += 1
            else:
                # Product not available at this store, try to find similar alternatives
                alternative_product = await find_alternative_product_in_store(db, product, store_id)
                if alternative_product:
                    # Use the alternative product
                    alt_price_cursor = db.prices.find({
                        "product_id": str(alternative_product["_id"]),
                        "store_id": store_id
                    }).sort("verified_at", -1).limit(1)

                    alt_price_doc = await alt_price_cursor.to_list(length=1)
                    if alt_price_doc:
                        alt_price = alt_price_doc[0]
                        alt_price_kes = alt_price["price_kes"]
                        is_promotional = alt_price.get("is_promotional", False)

                        # Format price
                        price_str = f"{int(alt_price_kes)} KES" if alt_price_kes == int(alt_price_kes) else f"{alt_price_kes:.1f} KES"

                        # Add to store items with indication it's an alternative
                        store_items[store_id].append({
                            "name": f"{product_name} ({alternative_product['name']})",
                            "price": price_str,
                            "offer": is_promotional
                        })

                        total_price += alt_price_kes
                        found_products += 1
                    else:
                        # Fallback to N/A if somehow no price found for alternative
                        store_items[store_id].append({
                            "name": product_name,
                            "price": "N/A",
                            "offer": False
                        })
                else:
                    # No similar product found in this store
                    store_items[store_id].append({
                        "name": product_name,
                        "price": "N/A",
                        "offer": False
                    })

        # Only include stores where we found at least one product
        if found_products > 0:
            total_str = f"{int(total_price)} KES" if total_price == int(total_price) else f"{total_price:.1f} KES"
            store_totals.append({
                "store_id": store_id,
                "store_name": store_name,
                "total": total_str,
                "total_value": total_price,  # For sorting
                "items": store_items[store_id],
                "product_count": found_products
            })
        

    # Sort stores: most complete basket first, then by total price ascending
    store_totals.sort(key=lambda x: (-x["product_count"], x["total_value"]))

    # Format for the image generator
    stores_for_display = []
    for store_data in store_totals:
        stores_for_display.append({
            "name": store_data["store_name"],
            "total": store_data["total"],
            "items": store_data["items"],
            "product_count": store_data["product_count"],
        })

    # Generate recommendation and savings
    recommendation = ""
    savings = ""

    if len(stores_for_display) >= 2:
        def parse_price(price_str):
            try:
                import re
                match = re.search(r'[\d,]+\.?\d*', price_str)
                return float(match.group().replace(',', '')) if match else 0
            except:
                return 0

        best_store = stores_for_display[0]  # completeness+price winner, already correctly ordered
        highest_priced_store = max(stores_for_display, key=lambda s: parse_price(s["total"]))

        best_val = parse_price(best_store["total"])
        highest_val = parse_price(highest_priced_store["total"])

        if highest_val > best_val:
            savings_amount = highest_val - best_val
            savings_str = f"{int(savings_amount)} KES" if savings_amount == int(savings_amount) else f"{savings_amount:.1f} KES"

            recommendation = f"{best_store['name']} - Lowest total ({best_store.get('product_count', '?')}/{len(products)} items found)"
            savings = f"Save {savings_str} vs {highest_priced_store['name']}"
        else:
            recommendation = f"{best_store['name']} - Best match ({best_store.get('product_count', '?')}/{len(products)} items found)"
            savings = ""


    elif len(stores_for_display) == 1:
        recommendation = f"Only {stores_for_display[0]['name']} has pricing data"
    else:
        recommendation = "No pricing data available for any store"

    return {
        "stores": stores_for_display,
        "recommendation": recommendation,
        "savings": savings,
        "date": datetime.now().strftime("%Y-%m-%d"),
        "item_count": len(products)
    }


async def process_telegram_message(chat_id: int, text: str, background_tasks: Optional[BackgroundTasks] = None) -> dict:
    """
    Process an incoming Telegram message and return structured data for infographic.
    This is where the NLP parser will go (Phase 2).
    """
    logger.info(f"Processing message from {chat_id}: {text}")

    text_lower = text.lower().strip()

    # Commands bypass relay even mid-session (so /end, ACCEPT, DECLINE always work).
    is_command = (
        text.startswith("/")
        or text.upper().startswith("ACCEPT ")
        or text.upper().startswith("DECLINE ")
    )

    if not is_command:
        db = await get_database()
        session = await find_active_session_for_user(db, chat_id)
        if session:
            is_buyer = session["buyer_user_id"] == chat_id
            recipient_id = session["grocer_telegram_user_id"] if is_buyer else session["buyer_user_id"]

            chat_message = ChatMessage(
                session_id=str(session["_id"]),
                user_id=chat_id,
                message_text=text,
            )
            await db.chat_messages.insert_one(chat_message.dict(by_alias=True))

            return {
                "type": "relay_message",
                "data": {"recipient_id": recipient_id, "message_text": text},
            }

    # Handle /start command
    if text.startswith("/start"):
        # Return a special response type for start command
        return {
            "type": "start",
            "data": {}
        }

    # Handle /sell command for seller onboarding
    if text.startswith("/sell"):
        return {
            "type": "sell_onboarding",
            "data": {
                "step": 1,
                "message": "Welcome to seller onboarding! Let's get you set up as a verified seller. What's your display name? (e.g., 'Mama Mboga Nairobi')"
            }
        }

    # Handle text-based /rating command (fallback for when there's no inline keyboard)
    if text.startswith("/rating"):
        parts = text.split(maxsplit=2)
        if len(parts) < 2 or not parts[1].isdigit():
            return {"type": "not_found", "data": {"message": "Usage: /rating <score 1-5> [optional comment]"}}

        score = int(parts[1])
        if score not in range(1, 6):
            return {"type": "not_found", "data": {"message": "Please rate between 1 and 5."}}

        comment = parts[2] if len(parts) > 2 else None

        db = await get_database()
        session = await find_latest_ratable_session(db, chat_id)
        if not session:
            return {"type": "not_found", "data": {"message": "We couldn't find a recent chat to rate."}}

        message_text = await apply_rating(db, chat_id, str(session["_id"]), score, comment)
        return {"type": "rating_recorded", "data": {"message": message_text}}

    # Handle ACCEPT / DECLINE replies from grocers to chat requests
    if text.upper().startswith("ACCEPT ") or text.upper().startswith("DECLINE "):
        db = await get_database()
        parts = text.split(maxsplit=1)
        if len(parts) != 2:
            return {"type": "not_found", "data": {"message": "Usage: ACCEPT <request_id> or DECLINE <request_id>"}}

        action, request_id_str = parts[0].upper(), parts[1].strip()

        try:
            request_oid = ObjectId(request_id_str)
        except Exception:
            return {"type": "not_found", "data": {"message": "That request ID doesn't look right."}}

        chat_request = await db.chat_requests.find_one({"_id": request_oid})
        if not chat_request:
            return {"type": "not_found", "data": {"message": "That request no longer exists."}}

        grocer = await db.grocers.find_one({"_id": ObjectId(chat_request["grocer_id"])})
        if not grocer or grocer.get("telegram_user_id") != chat_id:
            # Whoever is replying isn't the grocer this request was sent to.
            return {"type": "not_found", "data": {"message": "This request isn't yours to respond to."}}

        if chat_request.get("expires_at") and chat_request["expires_at"] < datetime.now(timezone.utc):
            await db.chat_requests.update_one(
                {"_id": request_oid, "status": "pending"}, {"$set": {"status": "expired"}}
            )
            return {"type": "not_found", "data": {"message": "That request has expired."}}

        if action == "DECLINE":
            result = await db.chat_requests.update_one(
                {"_id": request_oid, "status": "pending"},
                {"$set": {"status": "declined", "responded_at": datetime.now(timezone.utc)}},
            )
            if result.modified_count == 0:
                return {"type": "not_found", "data": {"message": "That request was already responded to."}}
            return {"type": "request_declined", "data": {"buyer_user_id": chat_request["buyer_user_id"]}}

        # ACCEPT — atomic compare-and-swap: only the first accept for this
        # request wins the race if it somehow gets triggered twice.
        result = await db.chat_requests.update_one(
            {"_id": request_oid, "status": "pending"},
            {"$set": {"status": "accepted", "responded_at": datetime.now(timezone.utc)}},
        )
        if result.modified_count == 0:
            return {"type": "not_found", "data": {"message": "That request was already responded to."}}

        session = ChatSession(
            request_id=str(request_oid),
            buyer_user_id=chat_request["buyer_user_id"],
            grocer_id=chat_request["grocer_id"],
            grocer_telegram_user_id=chat_id,
            status="active",
        )
        try:
            session_result = await db.chat_sessions.insert_one(session.dict(by_alias=True))
        except DuplicateKeyError:
            # Partial-unique index caught a genuine race: an active session
            # already exists for this buyer/grocer pair.
            return {"type": "not_found", "data": {"message": "You already have an active chat with this buyer."}}

        return {
            "type": "request_accepted",
            "data": {
                "buyer_user_id": chat_request["buyer_user_id"],
                "grocer_name": grocer["display_name"],
                "session_id": str(session_result.inserted_id),
            },
        }

    # Handle phase B: seller discovery trigger phrases
    # Check if message starts with trigger phrases for seller discovery
    trigger_phrases = ["sell ", "sell:", "where to buy ", "where to buy:", "find seller ", "find seller:"]
    is_seller_discovery = any(text_lower.startswith(phrase) for phrase in trigger_phrases)

    if is_seller_discovery:
        # Extract the product/search term after the trigger phrase
        search_term = text_lower
        for phrase in trigger_phrases:
            if text_lower.startswith(phrase):
                search_term = text_lower[len(phrase):].strip()
                break

        # If there's a trailing location/category filter (e.g., "in Nairobi" or "for vegetables")
        # We'll parse simple prepositions
        location_filter = None
        category_filter = None

        # Simple parsing for common patterns
        if " in " in search_term:
            parts = search_term.split(" in ")
            search_term = parts[0].strip()
            location_filter = parts[1].strip()
        elif " for " in search_term:
            parts = search_term.split(" for ")
            search_term = parts[0].strip()
            category_filter = parts[1].strip()

        # Perform seller discovery
        db = await get_database()

        # Build query for verified, opted-in grocers
        query = {
            "verification_status": "verified",
            "opted_in_visible": True,
            "is_banned": False
        }

        # Add text search on display_name, description, or categories
        if search_term:
            # For simplicity, we'll do a text search on display_name and description
            # In a real app, we'd use text indexes or more sophisticated search
            search_regex = {"$regex": search_term, "$options": "i"}
            query["$or"] = [
                {"display_name": search_regex},
                {"description": search_regex},
                {"categories": {"$in": [search_term]}}  # Exact match on category
            ]

        # Add location filter if specified
        if location_filter:
            location_regex = {"$regex": location_filter, "$options": "i"}
            query["town"] = location_regex

        # Add category filter if specified
        if category_filter:
            query["categories"] = {"$in": [category_filter]}

        # Find matching grocers, ranked by credibility (limit to 10 for display)
        grocers_cursor = db.grocers.find(query).sort("credibility_score", -1).limit(10)
        grocers = await grocers_cursor.to_list(length=10)

        if not grocers:
            # No sellers found
            return {
                "type": "seller_discovery_results",
                "data": {
                    "message": f"No verified sellers found for '{search_term}'{' in ' + location_filter if location_filter else ''}{' for ' + category_filter if category_filter else ''}.\n\nTry a different search term or check spelling.",
                    "sellers": []
                }
            }

        # Format results for display (we'll use a simple text format for now)
        # In a real implementation, we might generate an image or use inline keyboards
        seller_list_text = f"Found {len(grocers)} verified seller(s) for '{search_term}'"
        if location_filter:
            seller_list_text += f" in {location_filter}"
        if category_filter:
            seller_list_text += f" selling {category_filter}"
        seller_list_text += ":\n\n"

        for i, grocer in enumerate(grocers, 1):
            seller_list_text += f"{i}. {grocer['display_name']} "
            if 'town' in grocer:
                seller_list_text += f"({grocer['town']}) "
            seller_list_text += f"- Rating: {grocer.get('rating_average', 0):.1f}/5 ({grocer.get('review_count', 0)} reviews)\n"

        seller_list_text += "\nReply with the number of the seller you'd like to contact (e.g., '1')"

        # Save exactly which grocers were shown, in this order, so a numeric
        # reply resolves to what the buyer actually saw, not a fresh re-query.
        await db.discovery_search_context.update_one(
            {"buyer_user_id": chat_id},
            {"$set": {
                "buyer_user_id": chat_id,
                "grocer_ids": [str(g["_id"]) for g in grocers],
                "search_term": search_term,
                "location_filter": location_filter,
                "category_filter": category_filter,
                "created_at": datetime.now(timezone.utc),
                "expires_at": datetime.now(timezone.utc) + timedelta(minutes=10),
            }},
            upsert=True,
        )

        return {
            "type": "seller_discovery_results",
            "data": {
                "message": seller_list_text,
                "sellers": grocers,
                "search_term": search_term,
                "location_filter": location_filter,
                "category_filter": category_filter
            }
        }

    # Handle seller selection (when user replies with a number after seeing seller results)
    elif text.strip().isdigit():
        choice_num = int(text.strip())
        db = await get_database()

        search_context = await db.discovery_search_context.find_one({"buyer_user_id": chat_id})

        if not search_context or search_context["expires_at"] < datetime.now(timezone.utc):
            return {"type": "not_found", "data": {"message": "That selection has expired. Please search for sellers again."}}

        grocer_ids = search_context.get("grocer_ids", [])
        index = choice_num - 1
        if index < 0 or index >= len(grocer_ids):
            return {"type": "not_found", "data": {"message": f"Please reply with a number between 1 and {len(grocer_ids)}."}}

        grocer = await db.grocers.find_one({"_id": ObjectId(grocer_ids[index])})
        if not grocer:
            return {"type": "not_found", "data": {"message": "Sorry, that seller is no longer available. Please search again."}}

        chat_request = ChatRequest(
            buyer_user_id=chat_id,
            grocer_id=str(grocer["_id"]),
            status="pending",
            buyer_message="Hello! I'm interested in your products.",
            created_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        )

        try:
            result = await db.chat_requests.insert_one(chat_request.dict(by_alias=True))
        except DuplicateKeyError:
            return {"type": "not_found", "data": {"message": f"You already have a pending request with {grocer['display_name']}. Wait for them to respond."}}

        request_id = str(result.inserted_id)

        return {
            "type": "chat_request_created",
            "data": {
                "request_id": request_id,
                "buyer_message": (
                    f"Your request to connect with {grocer['display_name']} has been sent! "
                    f"They have 10 minutes to respond. You'll be notified when they do."
                ),
                "grocer_telegram_user_id": grocer["telegram_user_id"],
                "grocer_message": (
                    f"New chat request!\n\nA buyer is interested in connecting with you.\n"
                    f"Your response is needed within 10 minutes.\n\n"
                    f"To accept, reply: ACCEPT {request_id}\n"
                    f"To decline, reply: DECLINE {request_id}"
                ),
            },
        }

    # Handle /end command to end chat sessions (buyer or grocer)
    if text.startswith("/end"):
        db = await get_database()

        # A session can only be ended by the buyer or the grocer in it.
        # First check if the user is the buyer in an active session.
        chat_session = await db.chat_sessions.find_one(
            {"buyer_user_id": chat_id, "status": "active"},
            sort=[("created_at", -1)],
        )

        if chat_session:
            await db.chat_sessions.update_one(
                {"_id": chat_session["_id"]},
                {"$set": {"status": "ended_by_buyer", "ended_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc)}}
            )

            # Buyer ended the session - send the rating prompt to the buyer
            grocer_id = str(chat_session["grocer_id"]) if chat_session.get("grocer_id") else ""
            session_id = str(chat_session["_id"])

            if background_tasks:
                background_tasks.add_task(send_rating_prompt, buyer_user_id=chat_id, grocer_id=grocer_id, session_id=session_id)
            else:
                await send_rating_prompt(buyer_user_id=chat_id, grocer_id=grocer_id, session_id=session_id)

            return {
                "type": "chat_ended",
                "data": {
                    "message": "Chat session ended. Thank you for using PricePoa!\n\nWe'd love to hear about your experience. Please rate your conversation."
                }
            }

        # Otherwise, check if the user is the grocer in an active session.
        grocer = await db.grocers.find_one({"telegram_user_id": chat_id})
        if grocer:
            chat_session = await db.chat_sessions.find_one(
                {"grocer_id": str(grocer["_id"]), "status": "active"},
                sort=[("created_at", -1)],
            )

            if chat_session:
                await db.chat_sessions.update_one(
                    {"_id": chat_session["_id"]},
                    {"$set": {"status": "ended_by_grocer", "ended_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc)}}
                )

                # The rating prompt goes to the BUYER only - never to the grocer
                buyer_user_id = chat_session.get("buyer_user_id")
                grocer_id = str(chat_session["grocer_id"]) if chat_session.get("grocer_id") else ""
                session_id = str(chat_session["_id"])

                if buyer_user_id:
                    if background_tasks:
                        background_tasks.add_task(send_rating_prompt, buyer_user_id=buyer_user_id, grocer_id=grocer_id, session_id=session_id)
                    else:
                        await send_rating_prompt(buyer_user_id=buyer_user_id, grocer_id=grocer_id, session_id=session_id)

                return {
                    "type": "chat_ended",
                    "data": {
                        "message": "Chat session ended. Thank you for using PricePoa!"
                    }
                }

        return {
            "type": "not_found",
            "data": {"message": "You are not currently in an active chat session."}
        }

    # Enhanced logic: Check for shopping keywords OR multiple product terms
    shopping_keywords = ["list", "basket", "shopping", "buy", "get", "shop", "market"]

    # Extract meaningful product terms to detect multiple products
    meaningful_terms = extract_meaningful_product_terms(text)
    has_multiple_products = len(meaningful_terms) >= 2

    # Treat as shopping list if we see shopping keywords OR multiple products
    is_shopping_list = any(keyword in text_lower for keyword in shopping_keywords) or has_multiple_products

    if is_shopping_list:
        # Shopping list - process the request to get real data
        db = await get_database()

        # Extract potential product names from the text
        product_names = extract_product_names_from_shopping_list(text)
        logger.info(f"Extracted product names: {product_names}")

        # Look up the products in the database
        products = await get_products_for_shopping_list(db, product_names)
        logger.info(f"Found {len(products)} products: {[p['name'] for p in products]}")

        # Get shopping list data (prices across stores)
        if products:
            try:
                shopping_list_data = await get_shopping_list_data(db, products)
                return {
                    "type": "shopping_list",
                    "data": {
                        "stores": shopping_list_data["stores"],
                        "recommendation": shopping_list_data["recommendation"],
                        "savings": shopping_list_data["savings"],
                        "date": datetime.now().strftime("%Y-%m-%d"),
                        "item_count": len(products)
                    }
                }
            except Exception as e:
                logger.error(f"Error generating shopping list data: {e}")
                # Fallback to a simple response if data generation fails
                return {
                    "type": "shopping_list",
                    "data": {
                        "stores": [],
                        "recommendation": "Unable to retrieve pricing data at this time. Please try again later.",
                        "savings": "",
                        "date": datetime.now().strftime("%Y-%m-%d"),
                        "item_count": len(products)
                    }
                }
        else:
            # No products found
            return {
                "type": "shopping_list",
                "data": {
                    "stores": [],
                    "recommendation": "No products found in your query. Try common product names like 'unga', 'sugar', or 'cooking oil'.",
                    "savings": "",
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "item_count": 0
                }
            }
    else:
        # Single product query - return multiple options for comparison
        db = await get_database()
        matches = await find_product_matches(db, text, limit=5)

        if not matches:
            return {
                "type": "not_found",
                "data": {"query_text": text},
            }

        return {
            "type": "product_options",
            "data": {
                "query_text": text,
                "options": matches,
                "date": datetime.now().strftime("%Y-%m-%d"),
            },
        }


@router.post("/webhook/telegram")
async def telegram_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_telegram_bot_api_secret_token: Optional[str] = Header(None),
):
    """
    Handle incoming Telegram updates.

    Unlike Meta, there's no GET-based verification handshake - you register
    this URL once with Telegram via set_telegram_webhook(). Telegram then
    POSTs every update here and attaches your secret_token in the
    X-Telegram-Bot-Api-Secret-Token header for you to verify.
    """
    if not verify_telegram_secret(x_telegram_bot_api_secret_token or ""):
        logger.warning("Invalid or missing secret token on Telegram webhook")
        raise HTTPException(status_code=401, detail="Invalid secret token")

    try:
        update = await request.json()
    except Exception:
        logger.error("Invalid JSON in Telegram webhook payload")
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Extract message details. Telegram updates can be messages, edited
    # messages, channel posts, callback queries, etc.
    message = update.get("message")
    callback_query = update.get("callback_query")

    # Handle callback queries (for rating buttons)
    if callback_query:
        await handle_callback_query(callback_query)
        return JSONResponse(status_code=200, content={"status": "accepted"})

    if not message:
        logger.info("Received non-message update (e.g. edited_message)")
        return JSONResponse(status_code=200, content={"status": "ok"})

    chat = message.get("chat", {})
    chat_id = chat.get("id")
    text = message.get("text")

    if not chat_id or not text:
        logger.info("Message has no chat id or text (e.g. photo/sticker) - ignoring")
        return JSONResponse(status_code=200, content={"status": "ok"})

    text = text.strip()

    # Extract client IP address for device tracking (considering proxies)
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        # X-Forwarded-For can contain multiple IPs, the first is the client
        client_ip = forwarded.split(',')[0].strip()
    else:
        # If not behind a proxy, use the direct client host
        client_ip = request.client.host if request.client else "unknown"

    # Process the message
    try:
        processed = await process_telegram_message(chat_id, text, background_tasks)
    except Exception as e:
        logger.error(f"Error processing message from {chat_id} (IP: {client_ip}): {e}")
        fallback_text = "Sorry, our service is temporarily unavailable. Please try again later."
        send_telegram_text(chat_id, fallback_text)
        return JSONResponse(status_code=200, content={"status": "accepted"})

    # Log query for analytics
    try:
        db = await get_database()
        query_log = {
            "user_id": chat_id,
            "text": text,
            "timestamp": datetime.now(timezone.utc),
            "ip_address": client_ip,
            "products": [],  # will fill if we have product IDs
        }
        if processed.get("type") == "single_product":
            product = processed.get("_product")
            if product:
                query_log["products"] = [str(product["_id"])]
        elif processed.get("type") == "product_options":
            options = processed.get("data", {}).get("options", [])
            query_log["products"] = [opt["product_id"] for opt in options if opt.get("product_id")]

        # Store the query log in database
        await db.query_logs.insert_one(query_log)
    except Exception as e:
        logger.error(f"Failed to log query: {e}")

    if processed["type"] == "not_found":
        query_text = processed["data"]["query_text"]
        fallback_text = (
            f'Sorry, I couldn\'t find "{query_text}" in our database yet. '
            "Try the exact product name, e.g. \"Cooking Oil\" or \"unga\"."
        )
        send_telegram_text(chat_id, fallback_text)
        return JSONResponse(status_code=200, content={"status": "accepted"})

    # Handle start command
    if processed["type"] == "start":
        welcome_text = (
            "Welcome to PricePoa, your ultimate shopping partner, we help you find the best prices in you area by typing the products you need or a list of your entire shopping. Let's get Shopping!🛒"
        )
        send_telegram_text(chat_id, welcome_text)
        return JSONResponse(status_code=200, content={"status": "accepted"})

    # Handle message relay inside an active session
    if processed["type"] == "relay_message":
        data = processed["data"]
        send_telegram_text(data["recipient_id"], data["message_text"])
        return JSONResponse(status_code=200, content={"status": "accepted"})

    # Handle sell onboarding
    if processed["type"] == "sell_onboarding":
        data = processed["data"]
        step = data.get("step", 1)
        message = data["message"]

        if step == 1:
            message = (
                "📝 SELLER ONBOARDING - STEP 1/4\n\n"
                f"{message}\n\n"
                "Please reply with your display name (e.g., 'Mama Mboga Nairobi', 'Fresh Fruits Vendor')"
            )
        elif step == 2:
            message = (
                "📝 SELLER ONBOARDING - STEP 2/4\n\n"
                f"{message}\n\n"
                "Please reply with your town/city location (e.g., 'Nairobi', 'Mombasa', 'Kisumu')"
            )
        elif step == 3:
            message = (
                "📝 SELLER ONBOARDING - STEP 3/4\n\n"
                f"{message}\n\n"
                "Please reply with the categories of goods you sell (comma-separated, e.g., 'vegetables, fruits, herbs')"
            )
        elif step == 4:
            message = (
                "📝 SELLER ONBOARDING - STEP 4/4\n\n"
                f"{message}\n\n"
                "Would you like to add a photo of your stall or ID for verification? (Reply 'yes' or 'skip')"
            )
        else:
            message = "Onboarding complete! Thank you for registering as a seller."

        send_telegram_text(chat_id, message)
        return JSONResponse(status_code=200, content={"status": "accepted"})

    # Handle seller discovery results
    if processed["type"] == "seller_discovery_results":
        data = processed["data"]
        message = data["message"]
        send_telegram_text(chat_id, message)
        return JSONResponse(status_code=200, content={"status": "accepted"})

    # Handle chat request created
    if processed["type"] == "chat_request_created":
        data = processed["data"]
        send_telegram_text(chat_id, data["buyer_message"])
        send_telegram_text(data["grocer_telegram_user_id"], data["grocer_message"])
        return JSONResponse(status_code=200, content={"status": "accepted"})

    # Handle declined chat request
    if processed["type"] == "request_declined":
        send_telegram_text(processed["data"]["buyer_user_id"], "Sorry — the seller isn't available to chat right now.")
        return JSONResponse(status_code=200, content={"status": "accepted"})

    # Handle accepted chat request
    if processed["type"] == "request_accepted":
        data = processed["data"]
        send_telegram_text(data["buyer_user_id"], f"{data['grocer_name']} accepted! You're now connected — send your message.")
        send_telegram_text(chat_id, "Chat started. Send /end anytime to finish.")
        return JSONResponse(status_code=200, content={"status": "accepted"})

    # Handle chat ended
    if processed["type"] == "chat_ended":
        data = processed["data"]
        message = data["message"]
        send_telegram_text(chat_id, message)
        return JSONResponse(status_code=200, content={"status": "accepted"})

    # Handle recorded rating from text /rating command
    if processed["type"] == "rating_recorded":
        send_telegram_text(chat_id, processed["data"]["message"])
        return JSONResponse(status_code=200, content={"status": "accepted"})

    # Generate the infographic
    image_bytes = None
    try:
        if processed["type"] == "shopping_list":
            if "data" in processed:
                image_bytes = generate_shopping_list_image(processed["data"])
            else:
                logger.error("Missing 'data' key in processed for shopping_list")
        elif processed["type"] == "product_options":
            if "data" in processed:
                image_bytes = generate_product_options_image(processed["data"])
            else:
                logger.error("Missing 'data' key in processed for product_options")
    except Exception as e:
        logger.error(f"Error generating image: {e}")
        image_bytes = None

    # Try to send image if we have it
    if image_bytes is not None:
        success = send_telegram_photo(chat_id, image_bytes)
        if success:
            return JSONResponse(status_code=200, content={"status": "accepted"})
        else:
            logger.warning("Failed to send photo, falling back to text")

    # Fallback to text message
    if processed["type"] == "shopping_list":
        data = processed["data"]
        lines = [f"Shopping List Comparison:"]
        stores = data.get("stores", [])
        for store in stores:
            lines.append(f"  {store.get('name', 'Unknown')}: {store.get('total', 'N/A')}")
        recommendation = data.get("recommendation", "")
        if recommendation:
            lines.append(f"Recommendation: {recommendation}")
        savings = data.get("savings", "")
        if savings:
            lines.append(f"Savings: {savings}")
        lines.append(f"Date: {data.get('date', 'N/A')}")
        if data.get("item_count"):
            lines.append(f"Items: {data['item_count']}")
        fallback_text = "\n".join(lines)
    else:  # product_options
        data = processed["data"]
        text_lines = [f'Results for "{data.get("query_text", "")}":']
        for opt in data.get("options", []):
            line = f"  {opt['name']} ({opt['store_name']}): {opt['price_label']}"
            if opt.get('offer'):
                line += " (Offer!)"
            text_lines.append(line)
        text_lines.append(f"Date: {data.get('date', 'N/A')}")
        fallback_text = "\n".join(text_lines)

    # Send the fallback text
    success = send_telegram_text(chat_id, fallback_text)
    if not success:
        logger.error("Failed to send fallback text message")

    return JSONResponse(status_code=200, content={"status": "accepted"})