"""
Message processing pipeline.
Orchestrates text cleaning, CA detection, classification, scoring, and storage.
"""

from typing import Optional
import httpx

from processors.text_cleaner import TextCleaner
from processors.ca_detector import CADetector
from classifier.groq_classifier import GroqClassifier
from scoring.score_calculator import ScoreCalculator
from database.connection import get_db
from database.repository import ContractRepository, ChannelRepository
from utils.logger import get_logger

logger = get_logger(__name__)


async def fetch_token_info(contract_address: str) -> tuple[Optional[float], Optional[str]]:
    """
    Fetch current market cap and symbol for a token.
    Tries Birdeye first (more accurate), then falls back to DexScreener.
    
    Args:
        contract_address: Solana token address
        
    Returns:
        Tuple of (market_cap, token_symbol) or (None, None) if not found
    """
    mcap = None
    symbol = None
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Try Birdeye first (more accurate for Solana)
            try:
                birdeye_url = f"https://public-api.birdeye.so/defi/token_overview?address={contract_address}"
                birdeye_headers = {
                    "X-API-KEY": "e003202668264f1c8fdc16e688bf4e29",  # Paid tier API key
                    "x-chain": "solana"
                }
                response = await client.get(birdeye_url, headers=birdeye_headers)
                
                if response.status_code == 200:
                    data = response.json()
                    if data.get("success") and data.get("data"):
                        token_data = data["data"]
                        # Get symbol
                        symbol = token_data.get("symbol")
                        if symbol:
                            symbol = f"${symbol}"
                        # Try mc, realMc, then fdv as fallback
                        mcap = token_data.get("mc") or token_data.get("realMc") or token_data.get("fdv")
                        if mcap and mcap > 0:
                            logger.info(f"Fetched from Birdeye: {symbol or contract_address[:8]} mcap=${mcap:,.0f}")
                            return float(mcap), symbol
            except Exception as e:
                logger.warning(f"Birdeye failed for {contract_address[:8]}...: {e}")
            
            # Fallback to DexScreener
            url = f"https://api.dexscreener.com/latest/dex/tokens/{contract_address}"
            response = await client.get(url)
            
            if response.status_code == 200:
                data = response.json()
                pairs = data.get("pairs", [])
                if pairs and len(pairs) > 0:
                    pair = pairs[0]
                    # Get symbol from baseToken
                    if pair.get("baseToken"):
                        symbol = pair["baseToken"].get("symbol")
                        if symbol:
                            symbol = f"${symbol}"
                    # Get mcap from the first pair
                    mcap = pair.get("marketCap") or pair.get("fdv")
                    if mcap:
                        logger.info(f"Fetched from DexScreener: {symbol or contract_address[:8]} mcap=${mcap:,.0f}")
                        return float(mcap), symbol
            
            logger.warning(f"Could not fetch token info for {contract_address[:8]}...")
            return None, None
            
    except Exception as e:
        logger.error(f"Error fetching token info for {contract_address[:8]}...: {e}")
        return None, None


async def fetch_token_mcap(contract_address: str) -> Optional[float]:
    """Backwards compatible wrapper for fetch_token_info."""
    mcap, _ = await fetch_token_info(contract_address)
    return mcap


class MessageHandler:
    """
    Handles the complete message processing pipeline.
    
    Flow:
    1. Clean text (strip emojis, normalize whitespace)
    2. Detect Solana CA
    3. If CA found, classify message with LLM
    4. If classification is CALL, deduplicate and score
    5. Store in database
    """
    
    def __init__(self):
        self.classifier = GroqClassifier()
        self.score_calculator = ScoreCalculator()
    
    async def process_message(self, channel: str, raw_text: str) -> Optional[dict]:
        """
        Process a single message from a Telegram channel.
        
        Args:
            channel: Channel username (without @)
            raw_text: Raw message text
            
        Returns:
            Dict with processing result, or None if message was discarded
        """
        # Step 1: Validate and clean text
        if not TextCleaner.is_valid_message(raw_text):
            return None
        
        cleaned_text = TextCleaner.clean(raw_text)
        
        # Step 2: Detect Solana CA
        contract_address = CADetector.extract_first(cleaned_text)
        
        if not contract_address:
            # No CA found, discard message
            return None
        
        logger.info(f"CA detected: {contract_address[:12]}... from @{channel}")
        
        # Step 3: Fetch real-time market cap and token symbol
        detected_mcap, token_symbol = await fetch_token_info(contract_address)
        
        # Step 4: Classify message with LLM
        classification_result = await self.classifier.classify(cleaned_text)
        
        if not classification_result:
            logger.warning(f"Classification failed for CA {contract_address[:12]}...")
            return None
        
        classification = classification_result["classification"]
        confidence = classification_result.get("confidence", 0.0)
        
        logger.info(f"Classification: {classification} (confidence: {confidence:.2f})")
        
        # Step 4: Store ALL detected CAs (regardless of classification)
        # Classification is stored for reference but doesn't filter
        async with get_db() as session:
            contract_repo = ContractRepository(session)
            channel_repo = ChannelRepository(session)
            
            # Check if CA already exists
            existing = await contract_repo.get_by_address(contract_address)
            
            if existing:
                # Increment mention count
                await contract_repo.increment_mention(contract_address)
                logger.info(f"Duplicate CA, incremented mention count: {contract_address[:12]}...")
                
                return {
                    "action": "duplicate",
                    "contract_address": contract_address,
                    "mention_count": existing.mention_count + 1,
                }
            
            # New CA - get channel credibility and calculate score
            channel_entity = await channel_repo.get_or_create(channel)
            credibility = channel_entity.credibility_score
            
            # Calculate score
            score_result = self.score_calculator.calculate(
                first_seen_delta_seconds=0,  # Just discovered
                channel_credibility=credibility,
            )
            
            # Create new contract record with real-time mcap and symbol
            contract = await contract_repo.create(
                contract_address=contract_address,
                source_channel=channel,
                score=score_result["score"],
                risk_level=score_result["risk_level"],
                classification=classification,
                confidence=confidence,
                detected_mcap=detected_mcap,
                token_symbol=token_symbol,
            )
            
            # Increment channel call count
            await channel_repo.increment_call_count(channel)
            
            logger.info(
                f"New CA stored: {contract_address[:12]}... "
                f"(score: {score_result['score']}, risk: {score_result['risk_level']})"
            )
            
            return {
                "action": "created",
                "contract_address": contract_address,
                "score": score_result["score"],
                "risk_level": score_result["risk_level"],
                "channel": channel,
                "classification": classification,
                "confidence": confidence,
            }

