
from fastapi import FastAPI

from app.database.database import Base, engine
from app.routes.user_routes import router as user_router
from app.routes.incident_routes import router as incident_router
from app.routes.analytics_routes import router as analytics_router


# Initialize database tables
Base.metadata.create_all(bind=engine)

# Initialize FastAPI application
app = FastAPI(
    title="SmartOps API",
    description="Production Incident and Root Cause Management API",
    version="1.0.0",
)


# Register application routers
app.include_router(user_router)
app.include_router(incident_router)
app.include_router(analytics_router)


@app.get("/")
def home():
    return {"message": "Welcome to SmartOps API"}


