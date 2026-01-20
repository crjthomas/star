"""Fundamental financial analyzer."""
from typing import Dict, Any, Optional
from datetime import datetime
from utils.logger import get_logger
from utils.helpers import get_settings, normalize_ticker, safe_divide
from mcp_tools.fundamentals_mcp_server import FundamentalsMCPServer

logger = get_logger(__name__)

class FundamentalAnalyzer:
    """Analyzes fundamental financial metrics."""
    
    def __init__(self):
        self.settings = get_settings()
        self.fundamentals_server = FundamentalsMCPServer()
        
        risk_filters = self.settings.get("risk_filters", {})
        self.min_market_cap = risk_filters.get("min_market_cap", 50000000)
        self.max_debt_to_equity = risk_filters.get("max_debt_to_equity", 2.0)
        self.min_current_ratio = risk_filters.get("min_current_ratio", 1.0)
        self.exclude_penny_stocks = risk_filters.get("exclude_penny_stocks", True)
        self.min_price = risk_filters.get("min_price", 1.0)
        
    async def connect(self):
        """Initialize connections."""
        await self.fundamentals_server.connect()
        logger.info("Fundamental Analyzer connected")
    
    async def disconnect(self):
        """Close connections."""
        await self.fundamentals_server.disconnect()
    
    async def analyze_fundamentals(
        self,
        ticker: str
    ) -> Dict[str, Any]:
        """Analyze fundamental metrics for a ticker.
        
        Args:
            ticker: Ticker symbol
            
        Returns:
            Fundamental analysis result
        """
        ticker = normalize_ticker(ticker)
        
        # Get financial stability
        stability_result = await self.fundamentals_server.call_tool(
            "get_financial_stability",
            {"ticker": ticker}
        )
        
        if not stability_result.get("success"):
            return {
                "ticker": ticker,
                "score": 0.0,
                "passes_filters": False,
                "error": stability_result.get("error")
            }
        
        stability = stability_result.get("data", {})
        
        if "error" in stability:
            return {
                "ticker": ticker,
                "score": 0.0,
                "passes_filters": False,
                "error": stability["error"]
            }
        
        # Get fundamentals for additional metrics
        fundamentals_result = await self.fundamentals_server.call_tool(
            "get_fundamentals",
            {"ticker": ticker}
        )
        
        fundamentals = {}
        if fundamentals_result.get("success"):
            fundamentals = fundamentals_result.get("data", {})
        
        # Calculate fundamental score
        score = 0.0
        factors = []
        risk_factors = []
        
        # Stability score (from financial stability analysis)
        stability_score = stability.get("stability_score", 0.0)
        score += stability_score * 0.35
        factors.extend(stability.get("strengths", []))
        risk_factors.extend(stability.get("risk_factors", []))
        
        # Cash flow (positive is good)
        cash_position = fundamentals.get("total_cash", 0)
        market_cap = fundamentals.get("market_cap", 0)
        if cash_position and market_cap:
            cash_ratio = cash_position / market_cap
            if cash_ratio > 0.1:
                score += 0.25
                factors.append("Strong cash position")
            elif cash_ratio < 0.05:
                risk_factors.append("Low cash position")
                score -= 0.1
        
        # Revenue growth (positive is good)
        revenue_growth = fundamentals.get("revenue_growth")
        if revenue_growth:
            if revenue_growth > 0.1:
                score += 0.2
                factors.append(f"Strong revenue growth: {revenue_growth*100:.1f}%")
            elif revenue_growth < -0.1:
                risk_factors.append(f"Declining revenue: {revenue_growth*100:.1f}%")
                score -= 0.15
        
        # Debt ratios (low is good)
        debt_to_equity = fundamentals.get("debt_to_equity")
        if debt_to_equity:
            if debt_to_equity > self.max_debt_to_equity:
                risk_factors.append(f"High debt-to-equity: {debt_to_equity:.2f}")
                score -= 0.2
            elif debt_to_equity < 1.0:
                score += 0.2
                factors.append("Low debt-to-equity")
        
        # Market cap filter
        if market_cap and market_cap < self.min_market_cap:
            risk_factors.append(f"Market cap below minimum: ${market_cap:,.0f}")
            score -= 0.3
        
        # Normalize score to 0-100
        score = max(0.0, min(1.0, score)) * 100
        
        # Check if passes filters
        passes_filters = (
            (not market_cap or market_cap >= self.min_market_cap) and
            (not debt_to_equity or debt_to_equity <= self.max_debt_to_equity) and
            (not self.exclude_penny_stocks or not fundamentals.get("current_price") or 
             fundamentals.get("current_price", 0) >= self.min_price)
        )
        
        return {
            "ticker": ticker,
            "score": score,
            "passes_filters": passes_filters,
            "stability_score": stability_score * 100,
            "market_cap": market_cap,
            "cash_position": cash_position,
            "revenue_growth": revenue_growth,
            "debt_to_equity": debt_to_equity,
            "factors": factors,
            "risk_factors": risk_factors,
            "timestamp": datetime.now().isoformat()
        }

