"""Short squeeze detector."""
from typing import Dict, Any, Optional
from datetime import datetime
from utils.logger import get_logger
from utils.helpers import get_settings, normalize_ticker, safe_divide
from mcp_tools.fundamentals_mcp_server import FundamentalsMCPServer
from processing.volume_analyzer import VolumeAnalyzer

logger = get_logger(__name__)

class ShortSqueezeDetector:
    """Detects short squeeze potential."""
    
    def __init__(self):
        self.settings = get_settings()
        self.fundamentals_server = FundamentalsMCPServer()
        self.volume_analyzer = VolumeAnalyzer()
        
        short_squeeze_config = self.settings.get("short_squeeze", {})
        self.min_short_interest = short_squeeze_config.get("min_short_interest_pct", 20)
        self.min_days_to_cover = short_squeeze_config.get("min_days_to_cover", 5)
        self.min_short_increase = short_squeeze_config.get("min_short_interest_increase_pct", 10)
        
    async def connect(self):
        """Initialize connections."""
        await self.fundamentals_server.connect()
        await self.volume_analyzer.connect()
        logger.info("Short Squeeze Detector connected")
    
    async def disconnect(self):
        """Close connections."""
        await self.fundamentals_server.disconnect()
        await self.volume_analyzer.disconnect()
    
    async def detect_short_squeeze_potential(
        self,
        ticker: str
    ) -> Dict[str, Any]:
        """Detect short squeeze potential for a ticker.
        
        Args:
            ticker: Ticker symbol
            
        Returns:
            Short squeeze detection result
        """
        ticker = normalize_ticker(ticker)
        
        # Get short interest data
        short_interest_result = await self.fundamentals_server.call_tool(
            "get_short_interest",
            {"ticker": ticker}
        )
        
        if not short_interest_result.get("success"):
            return {
                "ticker": ticker,
                "has_squeeze_potential": False,
                "score": 0.0,
                "error": short_interest_result.get("error")
            }
        
        short_data = short_interest_result.get("data", {})
        
        if "error" in short_data:
            return {
                "ticker": ticker,
                "has_squeeze_potential": False,
                "score": 0.0,
                "error": short_data["error"]
            }
        
        short_percent_float = short_data.get("short_percent_float")
        days_to_cover = short_data.get("days_to_cover")
        shares_short = short_data.get("shares_short")
        shares_outstanding = short_data.get("shares_outstanding")
        avg_volume = short_data.get("average_volume")
        
        # Calculate squeeze score
        score = 0.0
        factors = []
        
        # Short interest percentage
        if short_percent_float:
            if short_percent_float >= self.min_short_interest:
                score += 0.35
                factors.append(f"High short interest: {short_percent_float:.2f}%")
            elif short_percent_float >= self.min_short_interest * 0.7:
                score += 0.2
                factors.append(f"Moderate short interest: {short_percent_float:.2f}%")
        
        # Days to cover
        if days_to_cover:
            if days_to_cover >= self.min_days_to_cover:
                score += 0.25
                factors.append(f"High days to cover: {days_to_cover:.2f}")
            elif days_to_cover >= self.min_days_to_cover * 0.7:
                score += 0.15
                factors.append(f"Moderate days to cover: {days_to_cover:.2f}")
        
        # Float size (smaller float = easier squeeze)
        if shares_outstanding and avg_volume:
            float_ratio = safe_divide(shares_short or 0, shares_outstanding, 0)
            if float_ratio < 0.5:
                score += 0.2
                factors.append(f"Constrained float")
        
        # Check for volume spike (indicator of squeeze starting)
        volume_analysis = await self.volume_analyzer.detect_volume_spike(ticker, avg_volume or 0)
        if volume_analysis.get("has_spike"):
            score += 0.2
            factors.append("Volume spike detected")
        
        # Normalize score to 0-100
        score = min(score * 100, 100)
        
        has_potential = (
            short_percent_float and short_percent_float >= self.min_short_interest and
            days_to_cover and days_to_cover >= self.min_days_to_cover and
            score >= 50
        )
        
        return {
            "ticker": ticker,
            "has_squeeze_potential": has_potential,
            "score": score,
            "short_percent_float": short_percent_float,
            "days_to_cover": days_to_cover,
            "shares_short": shares_short,
            "factors": factors,
            "timestamp": datetime.now().isoformat()
        }

