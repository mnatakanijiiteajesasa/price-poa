from fastapi import FastAPI
from fastapi.responses import JSONResponse
import os

app = FastAPI(title="PricePoa API", description="AI agent for Kenyan grocery price comparisons")

@app.get("/")
async def root():
    return {"message": "PricePoa API is running"}

@app.get("/health")
async def health_check():
    # Check MongoDB connection
    mongodb_uri = os.getenv("MONGODB_URI", "not_set")
    mongodb_db = os.getenv("MONGODB_DB", "not_set")

    return JSONResponse(
        status_code=200,
        content={
            "status": "healthy",
            "service": "api",
            "mongodb_uri": mongodb_uri,
            "mongodb_db": mongodb_db
        }
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)