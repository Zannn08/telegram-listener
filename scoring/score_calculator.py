"""
Score calculator for contract addresses.
Generates scores and risk levels based on timing and channel credibility.
"""

from typing import Dict, Any

from utils.logger import get_logger

logger = get_logger(__name__)


class ScoreCalculator:
    """
    Calculates scores and risk levels for detected contract addresses.
    
    Scoring formula:
    - Base score: 50
    - +10 if first seen < 60 seconds ago
    - +10 if channel credibility > 70
    - Score clamped between 0-100
    
    Risk levels:
    - HIGH: score < 40
    - MEDIUM: 40 <= score < 70
    - LOW: score >= 70
    """
    
    # Scoring constants
    BASE_SCORE = 50
    EARLY_DISCOVERY_BONUS = 10
    EARLY_DISCOVERY_THRESHOLD_SECONDS = 60
    CREDIBILITY_BONUS = 10
    CREDIBILITY_THRESHOLD = 70
    
    # Risk level thresholds
    HIGH_RISK_THRESHOLD = 40
    MEDIUM_RISK_THRESHOLD = 70
    
    def calculate(
        self,
        first_seen_delta_seconds: int,
        channel_credibility: int,
    ) -> Dict[str, Any]:
        """
        Calculate score and risk level for a contract address.
        
        Args:
            first_seen_delta_seconds: Seconds since first detection
                                      (0 for newly discovered CAs)
            channel_credibility: Channel's credibility score (0-100)
            
        Returns:
            Dict with 'score' (0-100) and 'risk_level' (LOW/MEDIUM/HIGH)
        """
        score = self.BASE_SCORE
        
        # Early discovery bonus
        if first_seen_delta_seconds < self.EARLY_DISCOVERY_THRESHOLD_SECONDS:
            score += self.EARLY_DISCOVERY_BONUS
            logger.debug(f"+{self.EARLY_DISCOVERY_BONUS} for early discovery")
        
        # Channel credibility bonus
        if channel_credibility > self.CREDIBILITY_THRESHOLD:
            score += self.CREDIBILITY_BONUS
            logger.debug(f"+{self.CREDIBILITY_BONUS} for high channel credibility ({channel_credibility})")
        
        # Clamp score to 0-100
        score = max(0, min(100, score))
        
        # Determine risk level
        risk_level = self._calculate_risk_level(score)
        
        logger.debug(f"Final score: {score}, risk level: {risk_level}")
        
        return {
            "score": score,
            "risk_level": risk_level,
        }
    
    def _calculate_risk_level(self, score: int) -> str:
        """
        Determine risk level based on score.
        
        Args:
            score: Calculated score (0-100)
            
        Returns:
            Risk level string: LOW, MEDIUM, or HIGH
        """
        if score < self.HIGH_RISK_THRESHOLD:
            return "HIGH"
        elif score < self.MEDIUM_RISK_THRESHOLD:
            return "MEDIUM"
        else:
            return "LOW"
    
    @classmethod
    def calculate_channel_credibility(
        cls,
        total_calls: int,
        successful_calls: int,
    ) -> int:
        """
        Calculate channel credibility based on historical performance.
        
        Args:
            total_calls: Total number of CALL messages from channel
            successful_calls: Number of successful calls (CAs that performed well)
            
        Returns:
            Credibility score (0-100)
        """
        if total_calls == 0:
            return 50  # Default for new channels
        
        accuracy = (successful_calls / total_calls) * 100
        credibility = max(0, min(100, int(accuracy)))
        
        return credibility

