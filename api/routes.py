"""
REST API route definitions.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

from database.connection import get_db_session
from database.repository import ContractRepository, ChannelRepository, AlertRepository, SubscriptionRepository
from listener.telegram_client import TelegramListener
from utils.logger import get_logger

logger = get_logger(__name__)

# Create router
router = APIRouter()


# Pydantic models for API responses
class ContractResponse(BaseModel):
    """Response model for a single contract."""
    id: str
    contract_address: str
    first_seen_at: str
    first_source_channel: str
    mention_count: int
    score: int
    risk_level: str
    classification: str
    llm_confidence: Optional[float] = None
    detected_mcap: Optional[float] = None
    token_symbol: Optional[str] = None
    created_at: str


class ClearResponse(BaseModel):
    """Response model for clear operations."""
    success: bool = True
    message: str = ""
    deleted_count: int = 0


class ContractListResponse(BaseModel):
    """Response model for contract list."""
    success: bool = True
    data: List[ContractResponse]
    count: int


class SingleContractResponse(BaseModel):
    """Response model for single contract lookup."""
    success: bool = True
    data: Optional[ContractResponse] = None
    error: Optional[str] = None


class ChannelResponse(BaseModel):
    """Response model for a channel."""
    id: str
    username: str
    credibility_score: int
    total_calls: int
    successful_calls: int
    is_active: bool
    created_at: str


class ChannelListResponse(BaseModel):
    """Response model for channel list."""
    success: bool = True
    data: List[ChannelResponse]
    count: int


class HealthResponse(BaseModel):
    """Response model for health check."""
    status: str = "ok"
    service: str = "telegram-listener"
    version: str = "1.0.0"


class AlertResponse(BaseModel):
    """Response model for a single price alert."""
    id: str
    contract_address: str
    source: str
    source_name: str
    token_symbol: Optional[str] = None
    entry_mcap: float
    current_mcap: float
    multiplier: float
    threshold: float
    is_read: bool
    triggered_at: str


class AlertListResponse(BaseModel):
    """Response model for alert list."""
    success: bool = True
    data: List[AlertResponse]
    count: int


class MarkAlertReadResponse(BaseModel):
    """Response model for marking alert as read."""
    success: bool = True
    message: str = ""


# Request models for POST endpoints
class AddChannelRequest(BaseModel):
    """Request model for adding a channel."""
    username: str = Field(..., min_length=1, max_length=255)
    credibility_score: int = Field(default=50, ge=0, le=100)


class AddChannelResponse(BaseModel):
    """Response model for adding a channel."""
    success: bool = True
    message: str = ""
    data: Optional[ChannelResponse] = None


class AddContractRequest(BaseModel):
    """Request model for adding a contract."""
    contract_address: str = Field(..., min_length=32, max_length=44)
    source_channel: str = Field(default="manual_entry")
    score: int = Field(default=60, ge=0, le=100)
    classification: str = Field(default="CALL")
    detected_mcap: Optional[float] = Field(default=None)  # Entry market cap for alerts


class AddContractResponse(BaseModel):
    """Response model for adding a contract."""
    success: bool = True
    message: str = ""
    data: Optional[ContractResponse] = None


# Subscription models
class SubscriptionResponse(BaseModel):
    """Response model for a subscription."""
    id: str
    user_id: str
    channel_id: str
    channel_username: str
    subscribed_at: str


class SubscriptionListResponse(BaseModel):
    """Response model for subscription list."""
    success: bool = True
    data: List[SubscriptionResponse]
    count: int


class SubscribeRequest(BaseModel):
    """Request model for subscribing to a channel."""
    user_id: str = Field(..., min_length=1, max_length=255)
    channel_username: str = Field(..., min_length=1, max_length=255)


class SubscribeResponse(BaseModel):
    """Response model for subscribe action."""
    success: bool = True
    message: str = ""
    channel_joined: bool = False  # True if Telegram channel was newly joined
    data: Optional[SubscriptionResponse] = None


class UnsubscribeResponse(BaseModel):
    """Response model for unsubscribe action."""
    success: bool = True
    message: str = ""
    channel_left: bool = False  # True if Telegram channel was left (no more subscribers)


# Routes
@router.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    """
    Health check endpoint.
    
    Returns service status and version.
    """
    return HealthResponse()


@router.get("/api/ca/latest", response_model=ContractListResponse, tags=["Contracts"])
async def get_latest_contracts(
    limit: int = Query(default=50, ge=1, le=200, description="Number of contracts to return"),
    user_id: Optional[str] = Query(default=None, description="User ID to filter by subscribed channels"),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Get the latest detected contract addresses.
    
    Returns contracts sorted by first_seen_at descending.
    If user_id is provided, only returns contracts from channels the user is subscribed to.
    """
    try:
        repo = ContractRepository(session)
        contracts = await repo.get_latest(limit=limit)
        
        # Filter by user subscriptions if user_id provided
        if user_id:
            sub_repo = SubscriptionRepository(session)
            subscribed_channels = await sub_repo.get_user_channel_usernames(user_id)
            
            if subscribed_channels:
                # Filter contracts to only those from subscribed channels
                contracts = [
                    c for c in contracts 
                    if c.first_source_channel in subscribed_channels
                ]
                logger.info(f"Filtered to {len(contracts)} contracts for user {user_id[:20]}... ({len(subscribed_channels)} channels)")
            else:
                # User has no subscriptions - return empty list
                logger.info(f"User {user_id[:20]}... has no subscriptions, returning empty list")
                return ContractListResponse(
                    success=True,
                    data=[],
                    count=0,
                )
        
        data = [ContractResponse(**c.to_dict()) for c in contracts]
        
        logger.info(f"Retrieved {len(data)} latest contracts")
        
        return ContractListResponse(
            success=True,
            data=data,
            count=len(data),
        )
    except Exception as e:
        logger.error(f"Error fetching latest contracts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/ca/{contract_address}", response_model=SingleContractResponse, tags=["Contracts"])
async def get_contract_by_address(
    contract_address: str,
    session: AsyncSession = Depends(get_db_session),
):
    """
    Get a specific contract by its address.
    
    Args:
        contract_address: Solana contract address (32-44 characters)
    """
    # Validate address length
    if not (32 <= len(contract_address) <= 44):
        return SingleContractResponse(
            success=False,
            data=None,
            error="Invalid contract address length (must be 32-44 characters)",
        )
    
    try:
        repo = ContractRepository(session)
        contract = await repo.get_by_address(contract_address)
        
        if contract is None:
            return SingleContractResponse(
                success=False,
                data=None,
                error="Contract not found",
            )
        
        data = ContractResponse(**contract.to_dict())
        
        logger.info(f"Retrieved contract: {contract_address[:12]}...")
        
        return SingleContractResponse(
            success=True,
            data=data,
        )
    except Exception as e:
        logger.error(f"Error fetching contract {contract_address[:12]}...: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/channels", response_model=ChannelListResponse, tags=["Channels"])
async def get_channels(
    session: AsyncSession = Depends(get_db_session),
):
    """
    Get all tracked channels with their stats.
    
    Returns list of channels with credibility scores and call counts.
    """
    try:
        repo = ChannelRepository(session)
        channels = await repo.get_all_active()
        
        data = [ChannelResponse(**c.to_dict()) for c in channels]
        
        logger.info(f"Retrieved {len(data)} channels")
        
        return ChannelListResponse(
            success=True,
            data=data,
            count=len(data),
        )
    except Exception as e:
        logger.error(f"Error fetching channels: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/channels", response_model=AddChannelResponse, tags=["Channels"])
async def add_channel(
    request: AddChannelRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """
    Add a new Telegram channel to track.
    
    Admin-only endpoint for manually adding channels.
    """
    try:
        # Clean username (remove @ if present)
        username = request.username.lstrip('@').strip()
        
        if not username:
            return AddChannelResponse(
                success=False,
                message="Username cannot be empty",
            )
        
        repo = ChannelRepository(session)
        channel = await repo.get_or_create(username)
        
        # Try to add to live telegram listener
        listener = TelegramListener.get_instance()
        if listener:
            added_live = await listener.add_channel(username)
            if added_live:
                logger.info(f"Added channel @{username} to database and live listener")
            else:
                logger.info(f"Added channel @{username} to database (will be active on restart)")
        else:
            logger.info(f"Added channel @{username} to database (listener not available)")
        
        return AddChannelResponse(
            success=True,
            message=f"Channel @{username} added successfully",
            data=ChannelResponse(**channel.to_dict()),
        )
    except Exception as e:
        logger.error(f"Error adding channel: {e}")
        return AddChannelResponse(
            success=False,
            message=str(e),
        )


class DeleteChannelResponse(BaseModel):
    """Response model for delete channel."""
    success: bool = True
    message: str = ""


@router.delete("/api/channels/{username}", response_model=DeleteChannelResponse, tags=["Channels"])
async def delete_channel(
    username: str,
    session: AsyncSession = Depends(get_db_session),
):
    """
    Delete a Telegram channel from tracking.
    """
    try:
        # Clean username (remove @ if present)
        username = username.lstrip('@').strip()
        
        if not username:
            return DeleteChannelResponse(
                success=False,
                message="Username cannot be empty",
            )
        
        repo = ChannelRepository(session)
        deleted = await repo.delete_by_username(username)
        
        if deleted:
            logger.info(f"Deleted channel: @{username}")
            return DeleteChannelResponse(
                success=True,
                message=f"Channel @{username} deleted successfully",
            )
        else:
            return DeleteChannelResponse(
                success=False,
                message=f"Channel @{username} not found",
            )
    except Exception as e:
        logger.error(f"Error deleting channel: {e}")
        return DeleteChannelResponse(
            success=False,
            message=str(e),
        )


@router.post("/api/ca", response_model=AddContractResponse, tags=["Contracts"])
async def add_contract(
    request: AddContractRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """
    Add a new contract address manually.
    
    Admin-only endpoint for manually adding CAs.
    """
    try:
        contract_repo = ContractRepository(session)
        channel_repo = ChannelRepository(session)
        
        # Check if already exists
        existing = await contract_repo.get_by_address(request.contract_address)
        if existing:
            # Increment mention count
            await contract_repo.increment_mention(request.contract_address)
            return AddContractResponse(
                success=True,
                message=f"CA already exists, mention count incremented",
                data=ContractResponse(**existing.to_dict()),
            )
        
        # Ensure channel exists
        await channel_repo.get_or_create(request.source_channel)
        
        # Determine risk level
        risk_level = "LOW" if request.score >= 70 else ("MEDIUM" if request.score >= 50 else "HIGH")
        
        # Create contract
        contract = await contract_repo.create(
            contract_address=request.contract_address,
            source_channel=request.source_channel,
            score=request.score,
            risk_level=risk_level,
            classification=request.classification,
            confidence=0.9,
            detected_mcap=request.detected_mcap,
        )
        
        source_type = "KOL" if request.source_channel.startswith("kol_") else "manual"
        logger.info(f"Added contract ({source_type}): {request.contract_address[:12]}... mcap: {request.detected_mcap}")
        
        return AddContractResponse(
            success=True,
            message=f"Contract added successfully",
            data=ContractResponse(**contract.to_dict()),
        )
    except Exception as e:
        logger.error(f"Error adding contract: {e}")
        return AddContractResponse(
            success=False,
            message=str(e),
        )


@router.delete("/api/ca/clear", response_model=ClearResponse, tags=["Contracts"])
async def clear_all_contracts(
    session: AsyncSession = Depends(get_db_session),
):
    """
    Clear all tracked contracts from the database.
    
    Admin-only endpoint for clearing call history.
    """
    try:
        repo = ContractRepository(session)
        deleted_count = await repo.clear_all()
        await session.commit()
        
        logger.info(f"Cleared all contracts: {deleted_count} deleted")
        
        return ClearResponse(
            success=True,
            message=f"Cleared {deleted_count} contracts",
            deleted_count=deleted_count,
        )
    except Exception as e:
        logger.error(f"Error clearing contracts: {e}")
        return ClearResponse(
            success=False,
            message=str(e),
        )


# ============ ALERTS ENDPOINTS ============

@router.get("/api/alerts", response_model=AlertListResponse, tags=["Alerts"])
async def get_alerts(
    unread_only: bool = Query(default=True, description="Only return unread alerts"),
    limit: int = Query(default=10, ge=1, le=50, description="Number of alerts to return"),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Get price alerts (2x, 5x, 10x notifications).
    
    Returns alerts sorted by triggered_at descending.
    """
    try:
        repo = AlertRepository(session)
        
        if unread_only:
            alerts = await repo.get_unread(limit=limit)
        else:
            alerts = await repo.get_all(limit=limit)
        
        data = [AlertResponse(**a.to_dict()) for a in alerts]
        
        return AlertListResponse(
            success=True,
            data=data,
            count=len(data),
        )
    except Exception as e:
        logger.error(f"Error fetching alerts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/alerts/{alert_id}/read", response_model=MarkAlertReadResponse, tags=["Alerts"])
async def mark_alert_read(
    alert_id: str,
    session: AsyncSession = Depends(get_db_session),
):
    """
    Mark a specific alert as read.
    """
    try:
        repo = AlertRepository(session)
        success = await repo.mark_as_read(alert_id)
        await session.commit()
        
        if success:
            return MarkAlertReadResponse(
                success=True,
                message="Alert marked as read",
            )
        else:
            return MarkAlertReadResponse(
                success=False,
                message="Alert not found",
            )
    except Exception as e:
        logger.error(f"Error marking alert as read: {e}")
        return MarkAlertReadResponse(
            success=False,
            message=str(e),
        )


@router.post("/api/alerts/read-all", response_model=MarkAlertReadResponse, tags=["Alerts"])
async def mark_all_alerts_read(
    session: AsyncSession = Depends(get_db_session),
):
    """
    Mark all alerts as read.
    """
    try:
        repo = AlertRepository(session)
        count = await repo.mark_all_as_read()
        await session.commit()
        
        return MarkAlertReadResponse(
            success=True,
            message=f"Marked {count} alerts as read",
        )
    except Exception as e:
        logger.error(f"Error marking all alerts as read: {e}")
        return MarkAlertReadResponse(
            success=False,
            message=str(e),
        )


# ============ SUBSCRIPTION ENDPOINTS ============

@router.post("/api/subscriptions", response_model=SubscribeResponse, tags=["Subscriptions"])
async def subscribe_to_channel(
    request: SubscribeRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """
    Subscribe a user to a Telegram channel.
    
    If the channel is new, it will be created and the Telegram listener will join it.
    If the channel already exists, just add the user subscription.
    """
    try:
        username = request.channel_username.lstrip('@').strip()
        
        if not username:
            return SubscribeResponse(
                success=False,
                message="Channel username cannot be empty",
            )
        
        channel_repo = ChannelRepository(session)
        sub_repo = SubscriptionRepository(session)
        
        # Check if channel exists
        channel = await channel_repo.get_by_username(username)
        channel_joined = False
        
        if channel is None:
            # New channel - create it and join Telegram
            channel = await channel_repo.get_or_create(username)
            
            # Try to join the Telegram channel
            listener = TelegramListener.get_instance()
            if listener and listener.client:
                try:
                    joined = await listener.join_channel(username)
                    if joined:
                        channel_joined = True
                        logger.info(f"Joined Telegram channel: @{username}")
                except Exception as e:
                    logger.warning(f"Could not join Telegram channel @{username}: {e}")
            else:
                logger.warning(f"Telegram listener not available, channel @{username} added to DB only")
        
        # Create subscription
        subscription = await sub_repo.subscribe(request.user_id, channel.id)
        await session.commit()
        
        return SubscribeResponse(
            success=True,
            message=f"Subscribed to @{username}" + (" (joined Telegram)" if channel_joined else ""),
            channel_joined=channel_joined,
            data=SubscriptionResponse(
                id=subscription.id,
                user_id=subscription.user_id,
                channel_id=subscription.channel_id,
                channel_username=username,
                subscribed_at=subscription.subscribed_at.isoformat() + "Z",
            ),
        )
    except Exception as e:
        logger.error(f"Error subscribing to channel: {e}")
        return SubscribeResponse(
            success=False,
            message=str(e),
        )


@router.delete("/api/subscriptions/{channel_username}", response_model=UnsubscribeResponse, tags=["Subscriptions"])
async def unsubscribe_from_channel(
    channel_username: str,
    user_id: str = Query(..., description="User ID to unsubscribe"),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Unsubscribe a user from a Telegram channel.
    
    If this is the last subscriber, the channel will be deleted and Telegram listener will leave.
    """
    try:
        username = channel_username.lstrip('@').strip()
        
        if not username:
            return UnsubscribeResponse(
                success=False,
                message="Channel username cannot be empty",
            )
        
        channel_repo = ChannelRepository(session)
        sub_repo = SubscriptionRepository(session)
        
        # Get channel
        channel = await channel_repo.get_by_username(username)
        if channel is None:
            return UnsubscribeResponse(
                success=False,
                message=f"Channel @{username} not found",
            )
        
        # Remove subscription
        unsubscribed = await sub_repo.unsubscribe(user_id, channel.id)
        
        if not unsubscribed:
            return UnsubscribeResponse(
                success=False,
                message="Subscription not found",
            )
        
        # Check if any subscribers remain
        subscriber_count = await sub_repo.get_subscriber_count(channel.id)
        channel_left = False
        
        if subscriber_count == 0:
            # No more subscribers - leave Telegram and delete channel
            listener = TelegramListener.get_instance()
            if listener and listener.client:
                try:
                    left = await listener.leave_channel(username)
                    if left:
                        channel_left = True
                        logger.info(f"Left Telegram channel: @{username}")
                except Exception as e:
                    logger.warning(f"Could not leave Telegram channel @{username}: {e}")
            
            # Delete channel from database
            await channel_repo.delete_by_username(username)
        
        await session.commit()
        
        return UnsubscribeResponse(
            success=True,
            message=f"Unsubscribed from @{username}" + (" (left Telegram)" if channel_left else ""),
            channel_left=channel_left,
        )
    except Exception as e:
        logger.error(f"Error unsubscribing from channel: {e}")
        return UnsubscribeResponse(
            success=False,
            message=str(e),
        )


@router.get("/api/subscriptions", response_model=SubscriptionListResponse, tags=["Subscriptions"])
async def get_user_subscriptions(
    user_id: str = Query(..., description="User ID to get subscriptions for"),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Get all channel subscriptions for a user.
    """
    try:
        sub_repo = SubscriptionRepository(session)
        channels = await sub_repo.get_user_channels(user_id)
        
        # Build response with channel usernames
        from sqlalchemy import select
        from database.models import UserSubscription
        
        result = await session.execute(
            select(UserSubscription).where(UserSubscription.user_id == user_id)
        )
        subscriptions = list(result.scalars().all())
        
        # Map channel_id to username
        channel_map = {ch.id: ch.username for ch in channels}
        
        data = [
            SubscriptionResponse(
                id=sub.id,
                user_id=sub.user_id,
                channel_id=sub.channel_id,
                channel_username=channel_map.get(sub.channel_id, "unknown"),
                subscribed_at=sub.subscribed_at.isoformat() + "Z",
            )
            for sub in subscriptions
            if sub.channel_id in channel_map
        ]
        
        return SubscriptionListResponse(
            success=True,
            data=data,
            count=len(data),
        )
    except Exception as e:
        logger.error(f"Error fetching subscriptions: {e}")
        raise HTTPException(status_code=500, detail=str(e))

