"""
Data access layer for database operations.
"""

from datetime import datetime
from typing import List, Optional
import uuid

from sqlalchemy import select, update, desc, delete
from sqlalchemy.ext.asyncio import AsyncSession

from .models import TrackedContract, TrackedChannel, PriceAlert
from utils.logger import get_logger

logger = get_logger(__name__)


class ContractRepository:
    """Repository for TrackedContract operations."""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def get_by_address(self, contract_address: str) -> Optional[TrackedContract]:
        """
        Get a contract by its address.
        
        Args:
            contract_address: Solana contract address
            
        Returns:
            TrackedContract if found, None otherwise
        """
        result = await self.session.execute(
            select(TrackedContract).where(
                TrackedContract.contract_address == contract_address
            )
        )
        return result.scalar_one_or_none()
    
    async def get_latest(self, limit: int = 50) -> List[TrackedContract]:
        """
        Get the latest contracts, sorted by first_seen_at descending.
        
        Args:
            limit: Maximum number of contracts to return
            
        Returns:
            List of TrackedContract
        """
        result = await self.session.execute(
            select(TrackedContract)
            .order_by(desc(TrackedContract.first_seen_at))
            .limit(limit)
        )
        return list(result.scalars().all())
    
    async def create(
        self,
        contract_address: str,
        source_channel: str,
        score: int,
        risk_level: str,
        classification: str,
        confidence: Optional[float] = None,
        detected_mcap: Optional[float] = None,
        token_symbol: Optional[str] = None,
    ) -> TrackedContract:
        """
        Create a new tracked contract.
        
        Args:
            contract_address: Solana contract address
            source_channel: Channel username where first seen
            score: Calculated score (0-100)
            risk_level: LOW, MEDIUM, or HIGH
            classification: CALL, WARNING, EXIT, or SPAM
            confidence: LLM confidence score
            detected_mcap: Market cap at time of detection
            token_symbol: Token symbol (e.g., $PEPE)
            
        Returns:
            Created TrackedContract
        """
        contract = TrackedContract(
            contract_address=contract_address,
            first_source_channel=source_channel,
            first_seen_at=datetime.utcnow(),
            score=score,
            risk_level=risk_level,
            classification=classification,
            llm_confidence=confidence,
            detected_mcap=detected_mcap,
            token_symbol=token_symbol,
            mention_count=1,
        )
        
        self.session.add(contract)
        await self.session.flush()
        
        logger.info(f"Created new contract: {contract_address[:8]}... from {source_channel}")
        
        return contract
    
    async def increment_mention(self, contract_address: str) -> bool:
        """
        Increment the mention count for an existing contract.
        
        Args:
            contract_address: Solana contract address
            
        Returns:
            True if updated, False if not found
        """
        result = await self.session.execute(
            update(TrackedContract)
            .where(TrackedContract.contract_address == contract_address)
            .values(
                mention_count=TrackedContract.mention_count + 1,
                updated_at=datetime.utcnow()
            )
        )
        
        if result.rowcount > 0:
            logger.debug(f"Incremented mention count for {contract_address[:8]}...")
            return True
        
        return False
    
    async def exists(self, contract_address: str) -> bool:
        """
        Check if a contract exists in the database.
        
        Args:
            contract_address: Solana contract address
            
        Returns:
            True if exists, False otherwise
        """
        result = await self.session.execute(
            select(TrackedContract.id).where(
                TrackedContract.contract_address == contract_address
            )
        )
        return result.scalar_one_or_none() is not None
    
    async def clear_all(self) -> int:
        """
        Delete all tracked contracts from the database.
        
        Returns:
            Number of deleted records
        """
        result = await self.session.execute(
            delete(TrackedContract)
        )
        logger.info(f"Cleared all contracts: {result.rowcount} records deleted")
        return result.rowcount


class ChannelRepository:
    """Repository for TrackedChannel operations."""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def get_by_username(self, username: str) -> Optional[TrackedChannel]:
        """
        Get a channel by its username.
        
        Args:
            username: Channel username (without @)
            
        Returns:
            TrackedChannel if found, None otherwise
        """
        result = await self.session.execute(
            select(TrackedChannel).where(TrackedChannel.username == username)
        )
        return result.scalar_one_or_none()
    
    async def get_all_active(self) -> List[TrackedChannel]:
        """
        Get all active channels.
        
        Returns:
            List of active TrackedChannel
        """
        result = await self.session.execute(
            select(TrackedChannel).where(TrackedChannel.is_active == True)
        )
        return list(result.scalars().all())
    
    async def get_or_create(self, username: str) -> TrackedChannel:
        """
        Get an existing channel or create a new one.
        
        Args:
            username: Channel username (without @)
            
        Returns:
            TrackedChannel
        """
        channel = await self.get_by_username(username)
        
        if channel is None:
            channel = TrackedChannel(
                username=username,
                credibility_score=50,  # Default
                total_calls=0,
                successful_calls=0,
                is_active=True,
            )
            self.session.add(channel)
            await self.session.flush()
            logger.info(f"Created new channel: {username}")
        
        return channel
    
    async def increment_call_count(self, username: str) -> None:
        """
        Increment the total call count for a channel.
        
        Args:
            username: Channel username
        """
        await self.session.execute(
            update(TrackedChannel)
            .where(TrackedChannel.username == username)
            .values(
                total_calls=TrackedChannel.total_calls + 1,
                updated_at=datetime.utcnow()
            )
        )
    
    async def update_credibility(self, username: str) -> None:
        """
        Recalculate and update credibility score for a channel.
        
        Args:
            username: Channel username
        """
        channel = await self.get_by_username(username)
        if channel:
            new_score = channel.calculate_credibility()
            await self.session.execute(
                update(TrackedChannel)
                .where(TrackedChannel.username == username)
                .values(
                    credibility_score=new_score,
                    updated_at=datetime.utcnow()
                )
            )
            logger.debug(f"Updated credibility for {username}: {new_score}")
    
    async def get_credibility(self, username: str) -> int:
        """
        Get the credibility score for a channel.
        
        Args:
            username: Channel username
            
        Returns:
            Credibility score (0-100), defaults to 50 for unknown channels
        """
        channel = await self.get_by_username(username)
        return channel.credibility_score if channel else 50
    
    async def delete_by_username(self, username: str) -> bool:
        """
        Delete a channel by its username.
        
        Args:
            username: Channel username (without @)
            
        Returns:
            True if deleted, False if not found
        """
        result = await self.session.execute(
            delete(TrackedChannel).where(TrackedChannel.username == username)
        )
        if result.rowcount > 0:
            logger.info(f"Deleted channel: {username}")
            return True
        return False


class AlertRepository:
    """Repository for PriceAlert operations."""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def create(
        self,
        contract_address: str,
        source: str,
        source_name: str,
        token_symbol: Optional[str],
        entry_mcap: float,
        current_mcap: float,
        multiplier: float,
        threshold: float,
    ) -> PriceAlert:
        """
        Create a new price alert.
        
        Args:
            contract_address: Token contract address
            source: "telegram" or "kol"
            source_name: Channel or KOL name
            token_symbol: Token symbol (e.g., $WIF)
            entry_mcap: Market cap at detection
            current_mcap: Current market cap
            multiplier: Current multiplier (current/entry)
            threshold: Threshold that was hit (2, 5, 10)
            
        Returns:
            Created PriceAlert
        """
        alert = PriceAlert(
            contract_address=contract_address,
            source=source,
            source_name=source_name,
            token_symbol=token_symbol,
            entry_mcap=entry_mcap,
            current_mcap=current_mcap,
            multiplier=multiplier,
            threshold=threshold,
            is_read=False,
        )
        
        self.session.add(alert)
        await self.session.flush()
        
        logger.info(f"Created price alert: {source_name} {multiplier:.1f}x on {contract_address[:8]}...")
        
        return alert
    
    async def get_unread(self, limit: int = 10) -> List[PriceAlert]:
        """
        Get unread alerts, sorted by triggered_at descending.
        
        Args:
            limit: Maximum number of alerts to return
            
        Returns:
            List of unread PriceAlert
        """
        result = await self.session.execute(
            select(PriceAlert)
            .where(PriceAlert.is_read == False)
            .order_by(desc(PriceAlert.triggered_at))
            .limit(limit)
        )
        return list(result.scalars().all())
    
    async def mark_as_read(self, alert_id: str) -> bool:
        """
        Mark an alert as read.
        
        Args:
            alert_id: Alert ID
            
        Returns:
            True if updated, False if not found
        """
        result = await self.session.execute(
            update(PriceAlert)
            .where(PriceAlert.id == alert_id)
            .values(is_read=True)
        )
        return result.rowcount > 0
    
    async def mark_all_as_read(self) -> int:
        """
        Mark all alerts as read.
        
        Returns:
            Number of alerts marked as read
        """
        result = await self.session.execute(
            update(PriceAlert)
            .where(PriceAlert.is_read == False)
            .values(is_read=True)
        )
        return result.rowcount
    
    async def exists_for_threshold(
        self,
        contract_address: str,
        threshold: float
    ) -> bool:
        """
        Check if an alert already exists for this contract at this threshold.
        Prevents duplicate alerts.
        
        Args:
            contract_address: Token contract address
            threshold: Threshold level (2, 5, 10)
            
        Returns:
            True if exists, False otherwise
        """
        result = await self.session.execute(
            select(PriceAlert.id).where(
                PriceAlert.contract_address == contract_address,
                PriceAlert.threshold == threshold
            )
        )
        return result.scalar_one_or_none() is not None
    
    async def get_all(self, limit: int = 50) -> List[PriceAlert]:
        """
        Get all alerts, sorted by triggered_at descending.
        
        Args:
            limit: Maximum number of alerts to return
            
        Returns:
            List of PriceAlert
        """
        result = await self.session.execute(
            select(PriceAlert)
            .order_by(desc(PriceAlert.triggered_at))
            .limit(limit)
        )
        return list(result.scalars().all())

