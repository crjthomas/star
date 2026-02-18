"""Detects tickers with potential for a massive pump (low float, high short, volume spike, momentum)."""
from typing import Dict, Any, Optional
from datetime import datetime
from utils.logger import get_logger
from utils.helpers import get_settings, normalize_ticker
from mcp_tools.fundamentals_mcp_server import FundamentalsMCPServer
from processing.volume_analyzer import VolumeAnalyzer
from processing.technical_indicators import TechnicalIndicators

logger = get_logger(__name__)


class PumpPotentialDetector:
    """Scores tickers on factors that often precede a massive pump."""

    def __init__(self):
        self.settings = get_settings()
        self.fundamentals_server = FundamentalsMCPServer()
        self.volume_analyzer = VolumeAnalyzer()
        self.technical_indicators = TechnicalIndicators()

        cfg = self.settings.get("pump_potential", {})
        # Low float = easier to move (typical pump names have small float)
        self.max_float_shares_millions = cfg.get("max_float_shares_millions", 50)
        # Small cap = more volatile, pump-friendly
        self.max_market_cap_millions = cfg.get("max_market_cap_millions", 500)
        # High short % of float = squeeze + pump potential
        self.min_short_percent_float = cfg.get("min_short_percent_float", 15)
        # Score threshold to flag "has_pump_potential"
        self.min_score_for_flag = cfg.get("min_score_for_flag", 55)

    async def connect(self):
        """Initialize connections."""
        await self.fundamentals_server.connect()
        await self.volume_analyzer.connect()
        await self.technical_indicators.connect()
        logger.info("Pump Potential Detector connected")

    async def disconnect(self):
        """Close connections."""
        await self.fundamentals_server.disconnect()
        await self.volume_analyzer.disconnect()
        await self.technical_indicators.disconnect()

    async def detect_pump_potential(
        self,
        ticker: str,
        current_volume: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Score ticker on pump potential (low float, high short, volume spike, momentum).

        Args:
            ticker: Ticker symbol
            current_volume: Current volume if already available

        Returns:
            pump_score 0-100, has_pump_potential bool, factors list
        """
        ticker = normalize_ticker(ticker)
        score = 0.0
        factors = []

        # 1) Fundamentals: float size, market cap, short interest
        short_result = await self.fundamentals_server.call_tool(
            "get_short_interest", {"ticker": ticker}
        )
        fund_result = await self.fundamentals_server.call_tool(
            "get_fundamentals", {"ticker": ticker}
        )

        short_data = short_result.get("data", {}) if short_result.get("success") else {}
        fund_data = fund_result.get("data", {}) if fund_result.get("success") else {}

        if "error" in short_data or "error" in fund_data:
            return {
                "ticker": ticker,
                "score": 0.0,
                "has_pump_potential": False,
                "factors": factors,
                "error": short_data.get("error") or fund_data.get("error"),
                "timestamp": datetime.now().isoformat(),
            }

        float_shares = fund_data.get("float_shares") or short_data.get("shares_outstanding")
        market_cap = fund_data.get("market_cap")
        short_pct_float = short_data.get("short_percent_float")
        days_to_cover = short_data.get("days_to_cover")
        avg_volume = short_data.get("average_volume")

        # Low float (smaller = higher pump potential)
        if float_shares:
            float_millions = float_shares / 1_000_000
            if float_millions <= self.max_float_shares_millions * 0.3:
                score += 25
                factors.append(f"Very low float: {float_millions:.1f}M shares")
            elif float_millions <= self.max_float_shares_millions:
                score += 15
                factors.append(f"Low float: {float_millions:.1f}M shares")

        # Small market cap
        if market_cap is not None:
            cap_millions = market_cap / 1_000_000
            if cap_millions <= self.max_market_cap_millions * 0.2:
                score += 20
                factors.append(f"Small cap: ${cap_millions:.0f}M")
            elif cap_millions <= self.max_market_cap_millions:
                score += 10
                factors.append(f"Mid-small cap: ${cap_millions:.0f}M")

        # High short interest % of float
        if short_pct_float is not None:
            if short_pct_float >= self.min_short_percent_float * 1.5:
                score += 25
                factors.append(f"High short interest: {short_pct_float:.1f}% of float")
            elif short_pct_float >= self.min_short_percent_float:
                score += 15
                factors.append(f"Elevated short interest: {short_pct_float:.1f}%")

        # Days to cover (squeeze fuel)
        if days_to_cover is not None and days_to_cover >= 5:
            score += 10
            factors.append(f"Days to cover: {days_to_cover:.1f}")

        # 2) Volume spike (pump often starts with volume)
        if current_volume is None and avg_volume:
            current_volume = avg_volume
        if current_volume is None:
            try:
                price_data = await self.volume_analyzer.ts_client.get_current_price(ticker)
                if price_data:
                    current_volume = price_data.get("volume", 0)
            except Exception:
                pass
        if current_volume:
            volume_spike = await self.volume_analyzer.detect_volume_spike(
                ticker, current_volume
            )
            if volume_spike.get("has_spike"):
                mult = volume_spike.get("multiplier", 0)
                if mult >= 3.0:
                    score += 20
                    factors.append(f"Volume spike: {mult:.1f}x average")
                else:
                    score += 10
                    factors.append(f"Above-average volume: {mult:.1f}x")

        # 3) Technical: breakout / momentum (optional boost)
        try:
            breakout = await self.technical_indicators.detect_breakout(ticker)
            if breakout.get("has_breakout"):
                score += 15
                factors.append("Price breakout detected")
            tech = await self.technical_indicators.calculate_all_indicators(ticker)
            if "error" not in tech:
                signals = tech.get("signals", {})
                if signals.get("price_above_sma") or signals.get("macd_bullish"):
                    score += 5
                    factors.append("Bullish technicals")
        except Exception as e:
            logger.debug(f"Technical check for pump {ticker}: {e}")

        score = min(score, 100.0)
        has_pump_potential = score >= self.min_score_for_flag

        return {
            "ticker": ticker,
            "score": round(score, 1),
            "has_pump_potential": has_pump_potential,
            "factors": factors,
            "float_shares": float_shares,
            "market_cap": market_cap,
            "short_percent_float": short_pct_float,
            "days_to_cover": days_to_cover,
            "timestamp": datetime.now().isoformat(),
        }
