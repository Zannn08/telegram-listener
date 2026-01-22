"""
Text cleaner for Telegram messages.
Strips emojis, extra whitespace, and normalizes text.
"""

import re
from typing import Optional


class TextCleaner:
    """Cleans and normalizes text from Telegram messages."""
    
    # Regex to match emoji characters
    EMOJI_PATTERN = re.compile(
        "["
        "\U0001F600-\U0001F64F"  # Emoticons
        "\U0001F300-\U0001F5FF"  # Symbols & pictographs
        "\U0001F680-\U0001F6FF"  # Transport & map symbols
        "\U0001F1E0-\U0001F1FF"  # Flags
        "\U00002702-\U000027B0"  # Dingbats
        "\U000024C2-\U0001F251"  # Enclosed characters
        "\U0001F900-\U0001F9FF"  # Supplemental symbols
        "\U0001FA00-\U0001FA6F"  # Chess symbols
        "\U0001FA70-\U0001FAFF"  # Symbols extended
        "\U00002600-\U000026FF"  # Misc symbols
        "\U00002700-\U000027BF"  # Dingbats
        "]+",
        flags=re.UNICODE
    )
    
    # Regex to match multiple whitespace
    WHITESPACE_PATTERN = re.compile(r'\s+')
    
    @classmethod
    def clean(cls, text: Optional[str]) -> str:
        """
        Clean and normalize text.
        
        Args:
            text: Raw text from Telegram message
            
        Returns:
            Cleaned text with emojis removed and whitespace normalized
        """
        if not text:
            return ""
        
        # Remove emojis
        cleaned = cls.EMOJI_PATTERN.sub(' ', text)
        
        # Normalize whitespace (multiple spaces/newlines -> single space)
        cleaned = cls.WHITESPACE_PATTERN.sub(' ', cleaned)
        
        # Strip leading/trailing whitespace
        cleaned = cleaned.strip()
        
        return cleaned
    
    @classmethod
    def is_valid_message(cls, text: Optional[str]) -> bool:
        """
        Check if text is valid for processing.
        
        Args:
            text: Text to validate
            
        Returns:
            True if text is non-empty and contains alphanumeric characters
        """
        if not text:
            return False
        
        cleaned = cls.clean(text)
        
        # Must have at least some alphanumeric content
        return bool(cleaned) and any(c.isalnum() for c in cleaned)

