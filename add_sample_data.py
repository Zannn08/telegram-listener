"""
Script to add sample channels and contract addresses for testing.
Run this to populate the database with test data.
"""

import asyncio
from datetime import datetime, timedelta
import random

# Add parent directory to path
import sys
sys.path.insert(0, '.')

from database.connection import init_db, close_db, get_db
from database.repository import ContractRepository, ChannelRepository


# Sample Telegram channels
SAMPLE_CHANNELS = [
    {"username": "solana_alpha", "credibility": 75},
    {"username": "crypto_gems", "credibility": 65},
    {"username": "degen_calls", "credibility": 55},
    {"username": "whale_alerts", "credibility": 80},
    {"username": "pump_signals", "credibility": 45},
]

# Sample Solana contract addresses (fake for testing)
SAMPLE_CAS = [
    "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
    "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "So11111111111111111111111111111111111111112",
    "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R",
    "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So",
    "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
    "orcaEKTdK7LKz57vaAYr9QeNsVEPfiu6QeMU1kektZE",
    "HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3",
]


async def add_sample_data():
    """Add sample channels and CAs to the database."""
    print("Initializing database...")
    await init_db()
    
    async with get_db() as session:
        channel_repo = ChannelRepository(session)
        contract_repo = ContractRepository(session)
        
        # Add channels
        print("\nAdding sample channels...")
        for ch in SAMPLE_CHANNELS:
            channel = await channel_repo.get_or_create(ch["username"])
            print(f"  + @{ch['username']} (credibility: {ch['credibility']})")
        
        # Add sample CAs
        print("\nAdding sample contract addresses...")
        for i, ca in enumerate(SAMPLE_CAS):
            # Check if already exists
            if await contract_repo.exists(ca):
                print(f"  - {ca[:12]}... already exists")
                continue
            
            # Random data for testing
            channel = random.choice(SAMPLE_CHANNELS)
            score = random.randint(45, 85)
            risk_level = "LOW" if score >= 70 else ("MEDIUM" if score >= 50 else "HIGH")
            
            await contract_repo.create(
                contract_address=ca,
                source_channel=channel["username"],
                score=score,
                risk_level=risk_level,
                classification="CALL",
                confidence=random.uniform(0.7, 0.95),
            )
            print(f"  + {ca[:12]}... (score: {score}, risk: {risk_level})")
    
    await close_db()
    print("\n[OK] Sample data added successfully!")
    print("Refresh the Calls tab in your frontend to see the data.")


if __name__ == "__main__":
    asyncio.run(add_sample_data())

