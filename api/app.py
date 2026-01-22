"""
FastAPI application factory.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database.connection import init_db, close_db
from utils.logger import get_logger
from .routes import router

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan handler.
    Manages database connection on startup/shutdown.
    """
    # Startup
    logger.info("Starting API server...")
    await init_db()
    
    yield
    
    # Shutdown
    logger.info("Shutting down API server...")
    await close_db()


def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application.
    
    Returns:
        Configured FastAPI application instance
    """
    app = FastAPI(
        title="Telegram CA Listener API",
        description="API for accessing detected Solana contract addresses from Telegram channels",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )
    
    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Configure appropriately for production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Include routes
    app.include_router(router)
    
    logger.info("FastAPI application created")
    
    return app


# Application instance for direct uvicorn usage
app = create_app()

