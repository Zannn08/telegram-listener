"""
Quick script to add a contract address to the database.
Usage: python add_ca.py <contract_address> [channel] [score]
"""

import asyncio
import sys

sys.path.insert(0, '.')

from database.connection import init_db, close_db, get_db
from database.repository import ContractRepository, ChannelRepository


async def add_ca(contract_address: str, channel: str = "manual_entry", score: int = 60):
    """Add a contract address to the database."""
    print(f"Adding CA: {contract_address[:20]}...")
    
    await init_db()
    
    async with get_db() as session:
        contract_repo = ContractRepository(session)
        channel_repo = ChannelRepository(session)
        
        # Check if already exists
        if await contract_repo.exists(contract_address):
            print(f"[!] CA already exists, incrementing mention count...")
            await contract_repo.increment_mention(contract_address)
        else:
            # Ensure channel exists
            await channel_repo.get_or_create(channel)
            
            # Determine risk level
            risk_level = "LOW" if score >= 70 else ("MEDIUM" if score >= 50 else "HIGH")
            
            await contract_repo.create(
                contract_address=contract_address,
                source_channel=channel,
                score=score,
                risk_level=risk_level,
                classification="CALL",
                confidence=0.85,
            )
            print(f"[OK] CA added (score: {score}, risk: {risk_level}, channel: @{channel})")
    
    await close_db()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python add_ca.py <contract_address> [channel] [score]")
        print("Example: python add_ca.py 7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU solana_alpha 75")
        sys.exit(1)
    
    ca = sys.argv[1]
    channel = sys.argv[2] if len(sys.argv) > 2 else "manual_entry"
    score = int(sys.argv[3]) if len(sys.argv) > 3 else 60
    
    asyncio.run(add_ca(ca, channel, score))

