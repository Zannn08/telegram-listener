"""
Price monitoring service that checks for multiplier thresholds.
Triggers alerts when tokens hit 2x, 5x, 10x from entry price.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, List

import httpx

from database.connection import get_db
from database.repository import ContractRepository, AlertRepository
from utils.logger import get_logger

logger = get_logger(__name__)

# Birdeye API configuration
BIRDEYE_API_KEY = "e003202668264f1c8fdc16e688bf4e29"
BIRDEYE_API_URL = "https://public-api.birdeye.so/defi/token_overview"

# Alert thresholds (multipliers)
# 1.25 = +25%, 1.5 = +50%, 2.0 = 2x, 5.0 = 5x, 10.0 = 10x
PUMP_THRESHOLDS = [1.25, 1.5, 2.0, 5.0, 10.0]

# Dump thresholds (negative alerts)
# 0.75 = -25%, 0.5 = -50%
DUMP_THRESHOLDS = [0.75, 0.5]

# How often to check prices (seconds)
CHECK_INTERVAL = 30

# Only check tokens from the last N hours
MAX_TOKEN_AGE_HOURS = 24


class PriceMonitor:
    """
    Background service that monitors token prices and triggers alerts.
    
    Runs on an interval, checks all tracked tokens against current prices,
    and creates alerts when thresholds are hit.
    """
    
    def __init__(self):
        self.running = False
        self._task: Optional[asyncio.Task] = None
        self._checked_thresholds: Dict[str, List[float]] = {}  # contract -> [triggered thresholds]
    
    async def start(self):
        """Start the price monitoring service."""
        if self.running:
            logger.warning("Price monitor already running")
            return
        
        self.running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Price monitor started")
    
    async def stop(self):
        """Stop the price monitoring service."""
        self.running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Price monitor stopped")
    
    async def _run_loop(self):
        """Main monitoring loop."""
        while self.running:
            try:
                await self._check_all_tokens()
            except Exception as e:
                logger.error(f"Error in price monitor loop: {e}")
            
            await asyncio.sleep(CHECK_INTERVAL)
    
    async def _check_all_tokens(self):
        """Check all tracked tokens for price changes."""
        async with get_db() as session:
            contract_repo = ContractRepository(session)
            alert_repo = AlertRepository(session)
            
            # Get recent contracts with entry mcap
            contracts = await contract_repo.get_latest(limit=100)
            
            # Filter to only tokens with detected_mcap and within age limit
            cutoff_time = datetime.utcnow() - timedelta(hours=MAX_TOKEN_AGE_HOURS)
            valid_contracts = [
                c for c in contracts 
                if c.detected_mcap and c.detected_mcap > 0 
                and c.first_seen_at > cutoff_time
            ]
            
            if not valid_contracts:
                logger.info(f"[SKIP] No valid contracts to check (total: {len(contracts)}, with mcap: {sum(1 for c in contracts if c.detected_mcap)})")
                return
            
            logger.info(f"[CHECK] Checking {len(valid_contracts)} tokens for price changes...")
            
            for contract in valid_contracts:
                await self._check_token(contract, alert_repo)
            
            await session.commit()
    
    async def _check_token(self, contract, alert_repo: AlertRepository):
        """Check a single token for threshold hits."""
        try:
            current_mcap = await self._fetch_current_mcap(contract.contract_address)
            
            if not current_mcap or current_mcap <= 0:
                logger.info(f"  [DEAD] {contract.contract_address[:8]}... - No current mcap (token may be dead)")
                return
            
            entry_mcap = contract.detected_mcap
            multiplier = current_mcap / entry_mcap
            
            # Log current status
            pct_change = (multiplier - 1) * 100
            logger.info(f"  [PRICE] {contract.contract_address[:8]}... | Entry: ${entry_mcap:,.0f} -> Now: ${current_mcap:,.0f} | {pct_change:+.1f}%")
            
            contract_key = contract.contract_address
            if contract_key not in self._checked_thresholds:
                self._checked_thresholds[contract_key] = []
            
            # Check PUMP thresholds (price going UP)
            for threshold in PUMP_THRESHOLDS:
                if multiplier >= threshold:
                    if threshold in self._checked_thresholds[contract_key]:
                        continue  # Already triggered
                    
                    exists = await alert_repo.exists_for_threshold(contract.contract_address, threshold)
                    if exists:
                        self._checked_thresholds[contract_key].append(threshold)
                        continue
                    
                    await self._create_alert(contract, alert_repo, entry_mcap, current_mcap, multiplier, threshold, is_dump=False)
            
            # Check DUMP thresholds (price going DOWN)
            for threshold in DUMP_THRESHOLDS:
                if multiplier <= threshold:
                    if threshold in self._checked_thresholds[contract_key]:
                        continue  # Already triggered
                    
                    exists = await alert_repo.exists_for_threshold(contract.contract_address, threshold)
                    if exists:
                        self._checked_thresholds[contract_key].append(threshold)
                        continue
                    
                    await self._create_alert(contract, alert_repo, entry_mcap, current_mcap, multiplier, threshold, is_dump=True)
        
        except Exception as e:
            logger.error(f"Error checking token {contract.contract_address[:8]}: {e}")
    
    async def _create_alert(self, contract, alert_repo: AlertRepository, entry_mcap: float, 
                           current_mcap: float, multiplier: float, threshold: float, is_dump: bool):
        """Create an alert for a threshold hit."""
        contract_key = contract.contract_address
        
        # Fetch token symbol
        token_symbol = await self._fetch_token_symbol(contract.contract_address)
        
        # Determine source type and friendly name
        source_channel = contract.first_source_channel or ""
        if source_channel == "Auto Scanner" or source_channel.startswith("kol_"):
            source_type = "scanner"
            source_display = "Auto Scanner"
        else:
            source_type = "telegram"
            source_display = source_channel
        
        # Create the alert
        await alert_repo.create(
            contract_address=contract.contract_address,
            source=source_type,
            source_name=source_display,
            token_symbol=token_symbol,
            entry_mcap=entry_mcap,
            current_mcap=current_mcap,
            multiplier=multiplier,
            threshold=threshold,
        )
        
        # Mark as triggered
        self._checked_thresholds[contract_key].append(threshold)
        
        # Format threshold nicely
        if is_dump:
            pct = int((1 - threshold) * 100)
            threshold_str = f"-{pct}%"
            alert_type = "DUMP"
        elif threshold < 2:
            threshold_str = f"+{int((threshold - 1) * 100)}%"
            alert_type = "PUMP"
        else:
            threshold_str = f"{threshold}x"
            alert_type = "PUMP"
        
        logger.info(
            f"[{alert_type}] {source_display} hit {threshold_str}! "
            f"({token_symbol or contract.contract_address[:8]})"
        )
    
    async def _fetch_current_mcap(self, contract_address: str) -> Optional[float]:
        """Fetch current market cap from Birdeye API."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                url = f"{BIRDEYE_API_URL}?address={contract_address}"
                headers = {
                    "X-API-KEY": BIRDEYE_API_KEY,
                    "x-chain": "solana"
                }
                
                response = await client.get(url, headers=headers)
                
                if response.status_code == 200:
                    data = response.json()
                    if data.get("success") and data.get("data"):
                        mcap = data["data"].get("marketCap") or data["data"].get("mc")
                        if mcap:
                            return float(mcap)
                        # Try FDV as fallback
                        fdv = data["data"].get("fdv")
                        if fdv:
                            return float(fdv)
                
                return None
                
        except Exception as e:
            logger.debug(f"Failed to fetch mcap for {contract_address[:8]}: {e}")
            return None
    
    async def _fetch_token_symbol(self, contract_address: str) -> Optional[str]:
        """Fetch token symbol from Birdeye API."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                url = f"{BIRDEYE_API_URL}?address={contract_address}"
                headers = {
                    "X-API-KEY": BIRDEYE_API_KEY,
                    "x-chain": "solana"
                }
                
                response = await client.get(url, headers=headers)
                
                if response.status_code == 200:
                    data = response.json()
                    if data.get("success") and data.get("data"):
                        symbol = data["data"].get("symbol")
                        if symbol:
                            return f"${symbol}"
                
                return None
                
        except Exception:
            return None


# Global instance
price_monitor = PriceMonitor()
