"""
Main entry point for the Telegram CA Listener service.

Runs both the Telegram listener and the REST API concurrently.
"""

import asyncio
import signal
import sys
from typing import Optional

import uvicorn

from config import settings
from utils.logger import setup_logger, get_logger
from database.connection import init_db, close_db
from listener.telegram_client import TelegramListener
from listener.message_handler import MessageHandler
from api.app import create_app
from services.price_monitor import price_monitor

# Setup logging
setup_logger(settings.log_level)
logger = get_logger(__name__)


class Application:
    """
    Main application class.
    Orchestrates the Telegram listener and API server.
    """
    
    def __init__(self):
        self.telegram_listener: Optional[TelegramListener] = None
        self.message_handler: Optional[MessageHandler] = None
        self._shutdown_event = asyncio.Event()
        self._api_server: Optional[uvicorn.Server] = None
    
    async def setup(self) -> None:
        """Initialize application components."""
        logger.info("=" * 50)
        logger.info("Telegram CA Listener - Starting up")
        logger.info("=" * 50)
        
        # Initialize database
        await init_db()
        
        # Initialize message handler
        self.message_handler = MessageHandler()
        
        # Initialize Telegram listener (only if credentials are configured)
        if settings.telegram_configured:
            # Load channels from database
            channels = await self._load_channels_from_db()
            
            if not channels:
                logger.warning("No channels in database. Add channels via the web admin panel.")
                logger.warning("API is running - add channels at /api/channels")
            else:
                logger.info(f"Loaded {len(channels)} channel(s) from database: {', '.join(channels)}")
            
            self.telegram_listener = TelegramListener(channels)
            self.telegram_listener.set_message_handler(self.message_handler.process_message)
        else:
            logger.warning("=" * 50)
            logger.warning("Telegram credentials not configured!")
            logger.warning("Running in API-ONLY mode.")
            logger.warning("Edit .env file to add your Telegram credentials.")
            logger.warning("=" * 50)
            self.telegram_listener = None
    
    async def _load_channels_from_db(self) -> list:
        """Load active channel usernames from database."""
        from database.connection import get_db
        from database.repository import ChannelRepository
        
        try:
            async with get_db() as session:
                repo = ChannelRepository(session)
                channels = await repo.get_all_active()
                return [ch.username for ch in channels]
        except Exception as e:
            logger.error(f"Failed to load channels from DB: {e}")
            return []
    
    async def run_api_server(self) -> None:
        """Run the FastAPI server."""
        app = create_app()
        
        config = uvicorn.Config(
            app=app,
            host=settings.api_host,
            port=settings.api_port,
            log_level="warning",  # Reduce uvicorn logging noise
        )
        
        self._api_server = uvicorn.Server(config)
        
        logger.info(f"API server starting on http://{settings.api_host}:{settings.api_port}")
        
        await self._api_server.serve()
    
    async def run_telegram_listener(self) -> None:
        """Run the Telegram listener."""
        if not self.telegram_listener:
            logger.info("Telegram listener disabled - running API only")
            # Keep running so API stays up
            await self._shutdown_event.wait()
            return
        
        if not self.telegram_listener.channels:
            logger.warning("No channels to monitor. Add channels via the web admin panel.")
            # Keep running so API stays up
            await self._shutdown_event.wait()
            return
        
        try:
            await self.telegram_listener.run()
        except Exception as e:
            logger.error(f"Telegram listener error: {e}")
    
    async def run_price_monitor(self) -> None:
        """Run the price monitoring service for alerts."""
        logger.info("Starting price monitor for +25%/+50%/2x/5x/10x alerts...")
        await price_monitor.start()
        # Keep running until shutdown
        await self._shutdown_event.wait()
        await price_monitor.stop()
    
    async def run(self) -> None:
        """Run all application components concurrently."""
        await self.setup()
        
        # Run API, Telegram listener, and price monitor concurrently
        tasks = [
            asyncio.create_task(self.run_api_server(), name="api_server"),
            asyncio.create_task(self.run_telegram_listener(), name="telegram_listener"),
            asyncio.create_task(self.run_price_monitor(), name="price_monitor"),
        ]
        
        try:
            # Wait for any task to complete (or fail)
            done, pending = await asyncio.wait(
                tasks,
                return_when=asyncio.FIRST_COMPLETED,
            )
            
            # Check for exceptions
            for task in done:
                if task.exception():
                    logger.error(f"Task {task.get_name()} failed: {task.exception()}")
            
            # Cancel remaining tasks
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                    
        except asyncio.CancelledError:
            logger.info("Application cancelled")
        finally:
            await self.shutdown()
    
    async def shutdown(self) -> None:
        """Clean shutdown of all components."""
        logger.info("Shutting down...")
        
        self._shutdown_event.set()
        
        # Stop price monitor
        await price_monitor.stop()
        
        # Close Telegram connection
        if self.telegram_listener:
            await self.telegram_listener.disconnect()
        
        # Close message handler resources
        if self.message_handler and hasattr(self.message_handler, 'classifier'):
            await self.message_handler.classifier.close()
        
        # Close database
        await close_db()
        
        logger.info("Shutdown complete")


def handle_signals(app: Application, loop: asyncio.AbstractEventLoop):
    """Setup signal handlers for graceful shutdown."""
    
    def signal_handler():
        logger.info("Received shutdown signal")
        for task in asyncio.all_tasks(loop):
            task.cancel()
    
    # Handle SIGINT and SIGTERM
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, signal_handler)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass


def main():
    """Main entry point."""
    logger.info("Starting Telegram CA Listener service...")
    
    app = Application()
    
    # Get or create event loop
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    # Setup signal handlers
    handle_signals(app, loop)
    
    try:
        loop.run_until_complete(app.run())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)
    finally:
        loop.close()
        logger.info("Application terminated")


if __name__ == "__main__":
    main()

