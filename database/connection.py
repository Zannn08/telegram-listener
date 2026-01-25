"""
Async database connection management.
"""

import ssl
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    AsyncEngine,
    create_async_engine,
    async_sessionmaker,
)

from config import settings
from utils.logger import get_logger
from .models import Base

logger = get_logger(__name__)

# Global engine and session factory
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


async def init_db() -> None:
    """
    Initialize database connection and create tables.
    Call this at application startup.
    """
    global _engine, _session_factory
    
    logger.info("Initializing database connection...")
    
    # Get the async-compatible database URL
    db_url = settings.async_database_url
    logger.info(f"Using database: {'SQLite' if 'sqlite' in db_url else 'PostgreSQL'}")
    
    # Create async engine with appropriate settings based on database type
    is_sqlite = db_url.startswith("sqlite")
    
    if is_sqlite:
        # SQLite doesn't support connection pooling
        _engine = create_async_engine(
            db_url,
            echo=False,
        )
    else:
        # PostgreSQL with connection pooling and SSL
        # Create SSL context for secure connection to Render PostgreSQL
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE  # Render uses self-signed certs
        
        _engine = create_async_engine(
            db_url,
            echo=False,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
            connect_args={"ssl": ssl_context},
        )
    
    # Create session factory
    _session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )
    
    # Create tables
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    logger.info("Database initialized successfully")


async def close_db() -> None:
    """
    Close database connection.
    Call this at application shutdown.
    """
    global _engine, _session_factory
    
    if _engine:
        logger.info("Closing database connection...")
        await _engine.dispose()
        _engine = None
        _session_factory = None
        logger.info("Database connection closed")


@asynccontextmanager
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Get an async database session.
    
    Usage:
        async with get_db() as session:
            # Use session here
            pass
    
    Yields:
        AsyncSession: Database session
    """
    if _session_factory is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    
    session = _session_factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency for getting database sessions.
    
    Yields:
        AsyncSession: Database session
    """
    async with get_db() as session:
        yield session

