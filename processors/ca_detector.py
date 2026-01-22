"""
Solana Contract Address (CA) detector.
Uses regex to find base58 encoded addresses (32-44 characters).
"""

import re
from typing import List, Optional

from utils.logger import get_logger

logger = get_logger(__name__)


class CADetector:
    """Detects Solana contract addresses in text."""
    
    # Solana addresses are base58 encoded, 32-44 characters
    # Base58 alphabet: 123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz
    # (no 0, O, I, l to avoid confusion)
    SOLANA_CA_PATTERN = re.compile(r'\b[1-9A-HJ-NP-Za-km-z]{32,44}\b')
    
    # Known system program addresses to ignore
    SYSTEM_ADDRESSES = {
        "So11111111111111111111111111111111111111112",  # Wrapped SOL
        "11111111111111111111111111111111",  # System Program
        "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",  # Token Program
        "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL",  # Associated Token Program
    }
    
    @classmethod
    def extract_addresses(cls, text: str) -> List[str]:
        """
        Extract all potential Solana addresses from text.
        
        Args:
            text: Text to search for addresses
            
        Returns:
            List of unique addresses found (excluding system addresses)
        """
        if not text:
            return []
        
        # Find all matches
        matches = cls.SOLANA_CA_PATTERN.findall(text)
        
        # Filter and deduplicate
        addresses = []
        seen = set()
        
        for addr in matches:
            # Skip if already seen
            if addr in seen:
                continue
            
            # Skip system addresses
            if addr in cls.SYSTEM_ADDRESSES:
                continue
            
            # Skip if too short (likely false positive)
            if len(addr) < 32:
                continue
            
            seen.add(addr)
            addresses.append(addr)
        
        if addresses:
            logger.debug(f"Found {len(addresses)} potential CA(s) in message")
        
        return addresses
    
    @classmethod
    def extract_first(cls, text: str) -> Optional[str]:
        """
        Extract the first valid Solana address from text.
        
        Args:
            text: Text to search for addresses
            
        Returns:
            First address found, or None
        """
        addresses = cls.extract_addresses(text)
        return addresses[0] if addresses else None
    
    @classmethod
    def is_valid_address(cls, address: str) -> bool:
        """
        Validate if a string is a valid Solana address format.
        
        Args:
            address: String to validate
            
        Returns:
            True if valid Solana address format
        """
        if not address:
            return False
        
        # Check length
        if not (32 <= len(address) <= 44):
            return False
        
        # Check if it matches the pattern
        if not cls.SOLANA_CA_PATTERN.fullmatch(address):
            return False
        
        # Check if it's a system address
        if address in cls.SYSTEM_ADDRESSES:
            return False
        
        return True

