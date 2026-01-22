"""
LLM-based message classifier using Groq API.
Classifies messages into CALL, WARNING, EXIT, or SPAM categories.
"""

import json
from typing import Optional, Dict, Any

import httpx

from config import settings
from utils.logger import get_logger

logger = get_logger(__name__)


class GroqClassifier:
    """
    Classifies Telegram messages using Groq's LLM API.
    
    Classifications:
    - CALL: Buy recommendation, alpha call, entry signal
    - WARNING: Caution, potential rug, be careful
    - EXIT: Sell signal, take profit, dump warning
    - SPAM: Irrelevant, ads, unrelated content
    """
    
    GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
    MODEL = "llama-3.3-70b-versatile"
    
    SYSTEM_PROMPT = """You are a crypto message classifier. Analyze the given Telegram message about a cryptocurrency token and classify it into exactly ONE of these categories:

CALL - The message is recommending to buy, enter, or ape into a token. It's bullish, optimistic, or promoting the token as a good opportunity.

WARNING - The message is expressing caution about a token. It might mention potential red flags, rug pull risks, or advises to be careful.

EXIT - The message is recommending to sell, take profits, or exit a position. It's bearish or suggesting the token has peaked.

SPAM - The message is irrelevant, promotional spam, bot-generated, or unrelated to actual trading signals.

Respond with ONLY valid JSON in this exact format:
{"classification": "CALL", "confidence": 0.92}

The confidence should be a number between 0 and 1 representing how certain you are about the classification.

DO NOT include any explanation or text outside the JSON."""

    def __init__(self):
        self.api_key = settings.groq_api_key
        self._client: Optional[httpx.AsyncClient] = None
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client
    
    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
    
    async def classify(self, message_text: str) -> Optional[Dict[str, Any]]:
        """
        Classify a message using Groq LLM.
        
        Args:
            message_text: Cleaned message text to classify
            
        Returns:
            Dict with 'classification' and 'confidence' keys, or None on error
        """
        if not message_text or len(message_text.strip()) < 10:
            logger.debug("Message too short for classification")
            return {"classification": "SPAM", "confidence": 0.99}
        
        try:
            client = await self._get_client()
            
            response = await client.post(
                self.GROQ_API_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.MODEL,
                    "messages": [
                        {"role": "system", "content": self.SYSTEM_PROMPT},
                        {"role": "user", "content": message_text[:1000]},  # Limit length
                    ],
                    "max_tokens": 50,
                    "temperature": 0.1,  # Low temperature for consistency
                },
            )
            
            response.raise_for_status()
            data = response.json()
            
            # Extract the LLM response
            content = data["choices"][0]["message"]["content"].strip()
            
            # Parse JSON response
            result = self._parse_response(content)
            
            if result:
                return result
            
            logger.warning(f"Failed to parse LLM response: {content}")
            return None
            
        except httpx.HTTPStatusError as e:
            logger.error(f"Groq API HTTP error: {e.response.status_code}")
            return None
        except httpx.RequestError as e:
            logger.error(f"Groq API request error: {e}")
            return None
        except Exception as e:
            logger.error(f"Classification error: {e}")
            return None
    
    def _parse_response(self, content: str) -> Optional[Dict[str, Any]]:
        """
        Parse the LLM response into a structured result.
        
        Args:
            content: Raw LLM response text
            
        Returns:
            Parsed dict with classification and confidence, or None
        """
        try:
            # Try to parse as JSON directly
            result = json.loads(content)
            
            # Validate structure
            if "classification" not in result:
                return None
            
            classification = result["classification"].upper()
            
            # Validate classification value
            valid_classifications = {"CALL", "WARNING", "EXIT", "SPAM"}
            if classification not in valid_classifications:
                logger.warning(f"Invalid classification: {classification}")
                return None
            
            # Get confidence with default
            confidence = float(result.get("confidence", 0.5))
            confidence = max(0.0, min(1.0, confidence))  # Clamp to 0-1
            
            return {
                "classification": classification,
                "confidence": confidence,
            }
            
        except json.JSONDecodeError:
            # Try to extract classification from text if JSON parsing fails
            content_upper = content.upper()
            for cls in ["CALL", "WARNING", "EXIT", "SPAM"]:
                if cls in content_upper:
                    return {
                        "classification": cls,
                        "confidence": 0.6,  # Lower confidence for fallback
                    }
            return None
        except (KeyError, ValueError, TypeError) as e:
            logger.debug(f"Parse error: {e}")
            return None

