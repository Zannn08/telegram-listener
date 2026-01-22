"""
SQLAlchemy models for the database.
"""

from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy import String, Integer, Boolean, DateTime, Text, Index
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all models."""
    pass


def generate_uuid() -> str:
    """Generate a UUID string."""
    return str(uuid.uuid4())


class TrackedContract(Base):
    """
    Represents a tracked Solana contract address.
    Stores first-seen data and scoring information.
    """
    
    __tablename__ = "tracked_contracts"
    
    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=generate_uuid
    )
    contract_address: Mapped[str] = mapped_column(
        String(44),
        unique=True,
        nullable=False,
        index=True
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow
    )
    first_source_channel: Mapped[str] = mapped_column(
        String(255),
        nullable=False
    )
    mention_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1
    )
    score: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=50
    )
    risk_level: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default="MEDIUM"
    )
    classification: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="CALL"
    )
    llm_confidence: Mapped[Optional[float]] = mapped_column(
        nullable=True
    )
    # Market cap at the time of detection (real-time capture)
    detected_mcap: Mapped[Optional[float]] = mapped_column(
        nullable=True
    )
    # Token symbol (e.g., $PEPE)
    token_symbol: Mapped[Optional[str]] = mapped_column(
        String(30),
        nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )
    
    # Indexes for common queries
    __table_args__ = (
        Index("idx_contracts_first_seen", "first_seen_at"),
        Index("idx_contracts_score", "score"),
        Index("idx_contracts_classification", "classification"),
    )
    
    def to_dict(self) -> dict:
        """Convert model to dictionary for API responses."""
        return {
            "id": str(self.id),
            "contract_address": self.contract_address,
            "first_seen_at": self.first_seen_at.isoformat() + "Z",  # Add Z to indicate UTC
            "first_source_channel": self.first_source_channel,
            "mention_count": self.mention_count,
            "score": self.score,
            "risk_level": self.risk_level,
            "classification": self.classification,
            "llm_confidence": self.llm_confidence,
            "detected_mcap": self.detected_mcap,
            "token_symbol": self.token_symbol,
            "created_at": self.created_at.isoformat() + "Z",  # Add Z to indicate UTC
        }


class PriceAlert(Base):
    """
    Represents a price alert triggered when a token hits a multiplier threshold.
    Used for 2x, 5x, 10x notifications.
    """
    
    __tablename__ = "price_alerts"
    
    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=generate_uuid
    )
    contract_address: Mapped[str] = mapped_column(
        String(44),
        nullable=False,
        index=True
    )
    source: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="telegram"  # "telegram" or "kol"
    )
    source_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default=""  # Channel name or KOL name
    )
    token_symbol: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True
    )
    entry_mcap: Mapped[float] = mapped_column(
        nullable=False
    )
    current_mcap: Mapped[float] = mapped_column(
        nullable=False
    )
    multiplier: Mapped[float] = mapped_column(
        nullable=False
    )
    threshold: Mapped[float] = mapped_column(
        nullable=False,
        default=2.0  # 2x, 5x, 10x
    )
    is_read: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False
    )
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow
    )
    
    __table_args__ = (
        Index("idx_alerts_triggered", "triggered_at"),
        Index("idx_alerts_is_read", "is_read"),
    )
    
    def to_dict(self) -> dict:
        """Convert model to dictionary for API responses."""
        return {
            "id": str(self.id),
            "contract_address": self.contract_address,
            "source": self.source,
            "source_name": self.source_name,
            "token_symbol": self.token_symbol,
            "entry_mcap": self.entry_mcap,
            "current_mcap": self.current_mcap,
            "multiplier": round(self.multiplier, 1),
            "threshold": self.threshold,
            "is_read": self.is_read,
            "triggered_at": self.triggered_at.isoformat() + "Z",
        }


class TrackedChannel(Base):
    """
    Represents a tracked Telegram channel.
    Stores credibility scoring data.
    """
    
    __tablename__ = "tracked_channels"
    
    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=generate_uuid
    )
    username: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True
    )
    credibility_score: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=50
    )
    total_calls: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0
    )
    successful_calls: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )
    
    def calculate_credibility(self) -> int:
        """
        Calculate credibility score based on historical accuracy.
        
        Returns:
            Credibility score 0-100
        """
        if self.total_calls == 0:
            return 50  # Default for new channels
        
        accuracy = (self.successful_calls / self.total_calls) * 100
        return min(100, max(0, int(accuracy)))
    
    def to_dict(self) -> dict:
        """Convert model to dictionary for API responses."""
        return {
            "id": str(self.id),
            "username": self.username,
            "credibility_score": self.credibility_score,
            "total_calls": self.total_calls,
            "successful_calls": self.successful_calls,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat(),
        }

