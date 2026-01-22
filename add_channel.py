"""
Quick script to add a Telegram channel to the database.
Usage: python add_channel.py <channel_username>
"""

import asyncio
import sys

sys.path.insert(0, '.')

from database.connection import init_db, close_db, get_db
from database.repository import ChannelRepository


async def add_channel(username: str):
    """Add a channel to the database."""
    # Remove @ if provided
    username = username.lstrip('@')
    
    print(f"Adding channel: @{username}")
    
    await init_db()
    
    async with get_db() as session:
        repo = ChannelRepository(session)
        channel = await repo.get_or_create(username)
        print(f"[OK] Channel @{username} added (credibility: {channel.credibility_score})")
    
    await close_db()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python add_channel.py <channel_username>")
        print("Example: python add_channel.py solana_alpha")
        sys.exit(1)
    
    asyncio.run(add_channel(sys.argv[1]))

