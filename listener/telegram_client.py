"""
Telegram client using Telethon for listening to public channels.
"""

import asyncio
from typing import Callable, List, Optional

from telethon import TelegramClient, events
from telethon.tl.types import Channel, Message

from config import settings
from utils.logger import get_logger

logger = get_logger(__name__)


class TelegramListener:
    """
    Telegram client for listening to public channels.
    Uses Telethon to connect and subscribe to channel messages.
    """
    
    # Class-level instance for access from API
    _instance: Optional["TelegramListener"] = None
    
    def __init__(self, channels: List[str]):
        """
        Initialize the Telegram listener.
        
        Args:
            channels: List of channel usernames to monitor (without @)
        """
        self.channels = channels
        self.client: Optional[TelegramClient] = None
        self._message_handler: Optional[Callable] = None
        self._running = False
        self._resolved_channels: List = []
        TelegramListener._instance = self
    
    @classmethod
    def get_instance(cls) -> Optional["TelegramListener"]:
        """Get the current listener instance."""
        return cls._instance
    
    async def add_channel(self, username: str) -> bool:
        """
        Dynamically add a channel to listen to.
        
        Args:
            username: Channel username (without @)
            
        Returns:
            True if successfully added, False otherwise
        """
        if not self.client:
            logger.warning("Cannot add channel - client not connected")
            return False
        
        username = username.lstrip('@').strip()
        
        if username in self.channels:
            logger.info(f"Channel @{username} already being monitored")
            return True
        
        try:
            entity = await self.client.get_entity(username)
            if isinstance(entity, Channel):
                self.channels.append(username)
                self._resolved_channels.append(entity)
                
                # Add handler for this new channel
                @self.client.on(events.NewMessage(chats=[entity]))
                async def new_channel_handler(event: events.NewMessage.Event):
                    message: Message = event.message
                    if not message.text:
                        return
                    chat = await event.get_chat()
                    channel_username = getattr(chat, 'username', None) or str(chat.id)
                    try:
                        if self._message_handler:
                            await self._message_handler(channel_username, message.text)
                    except Exception as e:
                        logger.error(f"Error in message handler: {e}")
                
                logger.info(f"✓ Dynamically added channel: @{username}")
                return True
            else:
                logger.warning(f"Entity @{username} is not a channel")
                return False
        except Exception as e:
            logger.error(f"Failed to add channel @{username}: {e}")
            return False
    
    async def connect(self) -> None:
        """
        Connect to Telegram and authenticate.
        Creates session file for subsequent logins.
        """
        logger.info("Connecting to Telegram...")
        
        self.client = TelegramClient(
            "telegram_listener_session",
            settings.telegram_api_id,
            settings.telegram_api_hash,
        )
        
        await self.client.connect()
        
        if not await self.client.is_user_authorized():
            logger.info("User not authorized, sending code request...")
            await self.client.send_code_request(settings.telegram_phone)
            
            # In production, this would be handled differently
            # For MVP, prompt for code
            code = input("Enter the code you received: ")
            await self.client.sign_in(settings.telegram_phone, code)
        
        logger.info("Connected to Telegram successfully")
    
    async def disconnect(self) -> None:
        """Disconnect from Telegram."""
        self._running = False
        
        if self.client:
            logger.info("Disconnecting from Telegram...")
            await self.client.disconnect()
            self.client = None
            logger.info("Disconnected from Telegram")
    
    def set_message_handler(self, handler: Callable) -> None:
        """
        Set the message handler callback.
        
        Args:
            handler: Async function to call for each new message.
                     Signature: async def handler(channel: str, message: str) -> None
        """
        self._message_handler = handler
    
    async def _resolve_channels(self) -> List[Channel]:
        """
        Resolve channel usernames to Telegram entities.
        
        Returns:
            List of resolved Channel entities
        """
        self._resolved_channels = []
        
        for username in self.channels:
            try:
                entity = await self.client.get_entity(username)
                if isinstance(entity, Channel):
                    self._resolved_channels.append(entity)
                    logger.info(f"Resolved channel: @{username}")
                else:
                    logger.warning(f"Entity @{username} is not a channel, skipping")
            except Exception as e:
                logger.error(f"Failed to resolve channel @{username}: {e}")
        
        return self._resolved_channels
    
    async def start_listening(self) -> None:
        """
        Start listening for new messages in configured channels.
        This method blocks until disconnect() is called.
        """
        if not self.client:
            raise RuntimeError("Not connected. Call connect() first.")
        
        if not self._message_handler:
            raise RuntimeError("No message handler set. Call set_message_handler() first.")
        
        if not self.channels:
            logger.warning("No channels configured to monitor")
            return
        
        # Resolve channels
        resolved_channels = await self._resolve_channels()
        
        if not resolved_channels:
            logger.error("No valid channels found to monitor")
            return
        
        logger.info(f"Monitoring {len(resolved_channels)} channel(s)")
        
        # Create event handler for new messages
        @self.client.on(events.NewMessage(chats=resolved_channels))
        async def new_message_handler(event: events.NewMessage.Event):
            """Handle incoming messages from monitored channels."""
            message: Message = event.message
            
            # Skip non-text messages
            if not message.text:
                return
            
            # Get channel username
            chat = await event.get_chat()
            channel_username = getattr(chat, 'username', None) or str(chat.id)
            
            # Call the registered handler
            try:
                await self._message_handler(channel_username, message.text)
            except Exception as e:
                logger.error(f"Error in message handler: {e}")
        
        self._running = True
        logger.info("Started listening for messages...")
        
        # Keep running until stopped
        await self.client.run_until_disconnected()
    
    async def run(self) -> None:
        """
        Main entry point: connect and start listening.
        """
        try:
            await self.connect()
            await self.start_listening()
        except asyncio.CancelledError:
            logger.info("Listener cancelled")
        except Exception as e:
            logger.error(f"Listener error: {e}")
            raise
        finally:
            await self.disconnect()

