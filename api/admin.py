"""
Admin panel routes for PricePoa
Provides dashboards for viewing trends, popular products, traffic stats, etc.
"""
import os
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from datetime import datetime, timedelta, timezone
import logging

logger = logging.getLogger("uvicorn.error")

# Create router
admin_router = APIRouter(prefix="/admin", tags=["admin"])

# Set up templates - handle potential path issues
current_file_dir = os.path.dirname(os.path.abspath(__file__))
# If the file is in an api/ subdirectory, use the parent directory as base
if current_file_dir.endswith('/api'):
    base_dir = os.path.dirname(current_file_dir)
else:
    base_dir = current_file_dir
templates = Jinja2Templates(directory=os.path.join(base_dir, "templates"))

# Helper to get database
async def get_db():
    from database.connection import get_database
    return await get_database()

@admin_router.get("/", response_class=HTMLResponse, name="admin.dashboard")
async def dashboard(request: Request):
    """Admin dashboard showing key metrics"""
    db = await get_db()

    # Get basic stats
    total_queries = await db.query_logs.count_documents({})

    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_queries = await db.query_logs.count_documents({"timestamp": {"$gte": today}})

    today_unique_users = len(await db.query_logs.distinct("user_id", {"timestamp": {"$gte": today}}))

    total_users = len(await db.query_logs.distinct("user_id"))

    # Get recent queries
    recent_queries = await db.query_logs.find(
        {},
        {"text": 1, "user_id": 1, "timestamp": 1}
    ).sort("timestamp", -1).limit(10).to_list(length=None)

    # Format for template
    recent_formatted = []
    for q in recent_queries:
        recent_formatted.append({
            "text": q["text"][:50] + "..." if len(q["text"]) > 50 else q["text"],
            "user_id": str(q["user_id"]),
            "timestamp": q["timestamp"].strftime("%Y-%m-%d %H:%M")
        })

    return templates.TemplateResponse(
        "admin/dashboard.html",
        {
            "request": request,
            "total_queries": total_queries,
            "today_queries": today_queries,
            "today_unique_users": today_unique_users,
            "total_users": total_users,
            "recent_queries": recent_formatted
        }
    )

@admin_router.get("/trends", response_class=HTMLResponse, name="admin.trends")
async def trends(request: Request):
    """Trends page showing query trends over time"""
    db = await get_db()

    # Get daily query counts for last 30 days
    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)

    daily_pipeline = [
        {"$match": {"timestamp": {"$gte": thirty_days_ago}}},
        {"$group": {
            "_id": {
                "year": {"$year": "$timestamp"},
                "month": {"$month": "$timestamp"},
                "day": {"$dayOfMonth": "$timestamp"}
            },
            "count": {"$sum": 1}
        }},
        {"$sort": {"_id": 1}}
    ]

    daily_data = await db.query_logs.aggregate(daily_pipeline).to_list(length=None)

    # Format for chart.js
    labels = []
    data = []
    for item in daily_data:
        date = datetime(
            item["_id"]["year"],
            item["_id"]["month"],
            item["_id"]["day"]
        )
        labels.append(date.strftime("%Y-%m-%d"))
        data.append(item["count"])

    return templates.TemplateResponse(
        "admin/trends.html",
        {
            "request": request,
            "daily_labels": labels,
            "daily_data": data
        }
    )

@admin_router.get("/popular", response_class=HTMLResponse, name="admin.popular")
async def popular(request: Request):
    """Popular products page"""
    db = await get_db()

    # Get all time popular products from query logs
    pipeline = [
        {"$project": {
            "query_text": "$text"
        }},
        {"$match": {
            "$expr": {
                "$gt": [{"$strLenCP": "$query_text"}, 0]
            }
        }},
        {"$group": {
            "_id": "$query_text",
            "count": {"$sum": 1}
        }},
        {"$sort": {"count": -1}},
        {"$limit": 20}
    ]

    popular_queries = await db.query_logs.aggregate(pipeline).to_list(length=None)

    return templates.TemplateResponse(
        "admin/popular.html",
        {
            "request": request,
            "popular_queries": popular_queries
        }
    )

@admin_router.get("/traffic", response_class=HTMLResponse, name="admin.traffic")
async def traffic(request: Request):
    """Traffic patterns page"""
    db = await get_db()

    # Hourly distribution (last 24 hours)
    twenty_four_hours_ago = datetime.now(timezone.utc) - timedelta(hours=24)

    hourly_pipeline = [
        {"$match": {"timestamp": {"$gte": twenty_four_hours_ago}}},
        {"$group": {
            "_id": {"$hour": "$timestamp"},
            "count": {"$sum": 1}
        }},
        {"$sort": {"_id": 1}}
    ]

    hourly_data = await db.query_logs.aggregate(hourly_pipeline).to_list(length=None)

    # Format for chart (0-23 hours)
    hourly_labels = [f"{i:02d}:00" for i in range(24)]
    hourly_counts = [0] * 24
    for item in hourly_data:
        hour = item["_id"]["hour"]
        hourly_counts[hour] = item["count"]

    # Daily distribution (last 7 days)
    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)

    daily_pipeline = [
        {"$match": {"timestamp": {"$gte": seven_days_ago}}},
        {"$group": {
            "_id": {"$dayOfWeek": "$timestamp"},  # 1=Sunday, 7=Saturday
            "count": {"$sum": 1}
        }},
        {"$sort": {"_id": 1}}
    ]

    daily_data = await db.query_logs.aggregate(daily_pipeline).to_list(length=None)

    # Format weekday names (adjusting for JS Date.getDay() which starts with Sunday=0)
    weekday_names = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    weekday_labels = []
    weekday_counts = [0] * 7

    for item in daily_data:
        # MongoDB dayOfWeek: 1=Sunday, JS getDay(): 0=Sunday
        # So we can use directly
        idx = item["_id"]["_id"] - 1  # Convert to 0-based index
        if 0 <= idx < 7:
            weekday_counts[idx] = item["count"]

    weekday_labels = weekday_names  # Already in correct order

    return templates.TemplateResponse(
        "admin/traffic.html",
        {
            "request": request,
            "hourly_labels": hourly_labels,
            "hourly_counts": hourly_counts,
            "weekday_labels": weekday_labels,
            "weekday_counts": weekday_counts
        }
    )

# API endpoints for AJAX data
@admin_router.get("/api/stats")
async def api_stats():
    """API endpoint for dashboard stats"""
    db = await get_db()

    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    stats = {
        "total_queries": await db.query_logs.count_documents({}),
        "today_queries": await db.query_logs.count_documents({"timestamp": {"$gte": today}}),
        "today_unique_users": len(await db.query_logs.distinct("user_id", {"timestamp": {"$gte": today}})),
        "total_users": len(await db.query_logs.distinct("user_id")),
    }

    return stats

@admin_router.get("/api/recent")
async def api_recent():
    """API endpoint for recent queries"""
    db = await get_db()

    recent = await db.query_logs.find(
        {},
        {"text": 1, "user_id": 1, "timestamp": 1, "type": 1}
    ).sort("timestamp", -1).limit(10).to_list(length=None)

    formatted = []
    for q in recent:
        formatted.append({
            "text": q["text"],
            "user_id": str(q["user_id"]),
            "timestamp": q["timestamp"].isoformat(),
            "type": q.get("type", "unknown")
        })

    return formatted