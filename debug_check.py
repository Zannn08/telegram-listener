"""Debug script to check database status."""
import asyncio
import sys
sys.path.insert(0, '.')

from database.connection import init_db, close_db, get_db
from database.repository import ChannelRepository, ContractRepository

async def check():
    print("=" * 50)
    print("DATABASE STATUS CHECK")
    print("=" * 50)
    
    await init_db()
    
    async with get_db() as session:
        # Check channels
        ch_repo = ChannelRepository(session)
        channels = await ch_repo.get_all_active()
        
        print("\n[CHANNELS]")
        if channels:
            for ch in channels:
                print(f"  - @{ch.username} (credibility: {ch.credibility_score})")
        else:
            print("  No channels found!")
        print(f"  Total: {len(channels)}")
        
        # Check contracts
        ca_repo = ContractRepository(session)
        contracts = await ca_repo.get_latest(10)
        
        print("\n[RECENT CONTRACTS]")
        if contracts:
            for ca in contracts:
                print(f"  - {ca.contract_address[:16]}... | score: {ca.score} | from: @{ca.first_source_channel}")
        else:
            print("  No contracts found!")
        print(f"  Total shown: {len(contracts)}")
    
    await close_db()
    print("\n" + "=" * 50)

if __name__ == "__main__":
    asyncio.run(check())

