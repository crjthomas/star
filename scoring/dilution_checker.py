"""Dilution risk checker."""
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
from utils.logger import get_logger
from utils.helpers import get_settings, normalize_ticker
from mcp_tools.fundamentals_mcp_server import FundamentalsMCPServer

logger = get_logger(__name__)

logger = get_logger(__name__)

class DilutionChecker:
    """Checks for dilution risks and reverse stock splits."""
    
    def __init__(self):
        self.settings = get_settings()
        self.fundamentals_server = FundamentalsMCPServer()
        
        dilution_config = self.settings.get("risk_filters", {}).get("dilution_checks", {})
        self.max_dilution_90_days = dilution_config.get("max_dilution_last_90_days", 0.15)
        self.exclude_upcoming_rs = dilution_config.get("exclude_upcoming_rs", True)
        self.exclude_recent_rs_days = dilution_config.get("exclude_recent_rs_days", 90)
        
    async def connect(self):
        """Initialize connections."""
        await self.fundamentals_server.connect()
        logger.info("Dilution Checker connected")
    
    async def disconnect(self):
        """Close connections."""
        await self.fundamentals_server.disconnect()
    
    async def check_dilution_risk(
        self,
        ticker: str,
        days: int = 90
    ) -> Dict[str, Any]:
        """Check for dilution risks.
        
        Args:
            ticker: Ticker symbol
            days: Days to look back
            
        Returns:
            Dilution risk assessment
        """
        ticker = normalize_ticker(ticker)
        
        # Check dilution risk
        dilution_result = await self.fundamentals_server.call_tool(
            "check_dilution_risk",
            {"ticker": ticker, "days": days}
        )
        
        if not dilution_result.get("success"):
            return {
                "ticker": ticker,
                "has_dilution_risk": False,
                "has_recent_dilution": False,
                "risk_score": 0.0,
                "error": dilution_result.get("error")
            }
        
        dilution_data = dilution_result.get("data", {})
        
        if "error" in dilution_data:
            return {
                "ticker": ticker,
                "has_dilution_risk": False,
                "has_recent_dilution": False,
                "risk_score": 0.0,
                "error": dilution_data["error"]
            }
        
        # Check reverse split
        rs_result = await self.fundamentals_server.call_tool(
            "check_reverse_split",
            {"ticker": ticker, "days": days}
        )
        
        rs_data = {}
        if rs_result.get("success"):
            rs_data = rs_result.get("data", {})
        
        has_recent_dilution = dilution_data.get("has_recent_dilution", False)
        dilution_risk_score = dilution_data.get("dilution_risk_score", 0.0)
        has_reverse_split = rs_data.get("has_reverse_split", False)
        rs_date = rs_data.get("reverse_split_date")
        
        # Calculate overall risk
        risk_factors = []
        risk_score = 0.0
        
        if has_recent_dilution:
            risk_factors.append("Recent dilution detected")
            risk_score += 0.5
        
        if dilution_risk_score > 0.3:
            risk_factors.append(f"High dilution risk score: {dilution_risk_score:.2f}")
            risk_score += 0.3
        
        if has_reverse_split:
            risk_factors.append("Recent reverse split detected")
            risk_score += 0.4
            
            # Check if RS was recent
            if rs_date:
                try:
                    rs_datetime = datetime.fromisoformat(rs_date.replace("Z", "+00:00"))
                    days_since_rs = (datetime.now() - rs_datetime.replace(tzinfo=None)).days
                    
                    if days_since_rs < self.exclude_recent_rs_days:
                        risk_factors.append(f"Reverse split within last {days_since_rs} days")
                        risk_score += 0.2
                except:
                    pass
        
        # Check for upcoming RS (would need SEC filing data)
        if self.exclude_upcoming_rs:
            # Placeholder - in production would check SEC EDGAR
            pass
        
        has_dilution_risk = risk_score > 0.3
        
        return {
            "ticker": ticker,
            "has_dilution_risk": has_dilution_risk,
            "has_recent_dilution": has_recent_dilution,
            "has_reverse_split": has_reverse_split,
            "reverse_split_date": rs_date,
            "risk_score": min(risk_score, 1.0),
            "dilution_risk_score": dilution_risk_score,
            "risk_factors": risk_factors,
            "lookback_days": days,
            "timestamp": datetime.now().isoformat()
        }

