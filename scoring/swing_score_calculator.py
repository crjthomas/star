"""Swing play score calculator."""
from typing import Dict, Any, Optional, List
from datetime import datetime
from utils.logger import get_logger
from utils.helpers import get_settings, get_scoring_weights, normalize_ticker
from processing.volume_analyzer import VolumeAnalyzer
from processing.technical_indicators import TechnicalIndicators
from processing.catalyst_detector import CatalystDetector
from processing.short_squeeze_detector import ShortSqueezeDetector
from processing.pump_potential_detector import PumpPotentialDetector
from scoring.fundamental_analyzer import FundamentalAnalyzer
from scoring.dilution_checker import DilutionChecker

logger = get_logger(__name__)

class SwingScoreCalculator:
    """Calculates swing play scores combining all signals."""
    
    def __init__(self):
        self.settings = get_settings()
        self.scoring_weights = get_scoring_weights()
        
        # Initialize analyzers
        self.volume_analyzer = VolumeAnalyzer()
        self.technical_indicators = TechnicalIndicators()
        self.catalyst_detector = CatalystDetector()
        self.short_squeeze_detector = ShortSqueezeDetector()
        self.pump_potential_detector = PumpPotentialDetector()
        self.fundamental_analyzer = FundamentalAnalyzer()
        self.dilution_checker = DilutionChecker()
        
        # Get weights
        weights = self.scoring_weights.get("weights", {})
        self.volume_technical_weight = weights.get("volume_technical", 0.30)
        self.catalyst_weight = weights.get("catalyst", 0.35)
        self.short_squeeze_weight = weights.get("short_squeeze", 0.15)
        self.fundamental_weight = weights.get("fundamental", 0.20)
        
        # Get thresholds
        thresholds = self.scoring_weights.get("thresholds", {})
        self.min_total_score = thresholds.get("min_total_score", 75)
        self.min_volume_technical_score = thresholds.get("min_volume_technical_score", 20)
        self.min_catalyst_score = thresholds.get("min_catalyst_score", 25)
        self.min_fundamental_score = thresholds.get("min_fundamental_score", 12)
        
        # Get penalties and bonuses
        self.penalties = self.scoring_weights.get("penalties", {})
        self.bonuses = self.scoring_weights.get("bonuses", {})
        
    async def connect(self):
        """Initialize all connections."""
        await self.volume_analyzer.connect()
        await self.technical_indicators.connect()
        await self.catalyst_detector.connect()
        await self.short_squeeze_detector.connect()
        await self.pump_potential_detector.connect()
        await self.fundamental_analyzer.connect()
        await self.dilution_checker.connect()
        logger.info("Swing Score Calculator connected")
    
    async def disconnect(self):
        """Close all connections."""
        await self.volume_analyzer.disconnect()
        await self.technical_indicators.disconnect()
        await self.catalyst_detector.disconnect()
        await self.short_squeeze_detector.disconnect()
        await self.pump_potential_detector.disconnect()
        await self.fundamental_analyzer.disconnect()
        await self.dilution_checker.disconnect()
    
    async def calculate_score(
        self,
        ticker: str,
        current_volume: Optional[int] = None
    ) -> Dict[str, Any]:
        """Calculate comprehensive swing play score for a ticker.
        
        Args:
            ticker: Ticker symbol
            current_volume: Current volume (if available)
            
        Returns:
            Complete score analysis
        """
        ticker = normalize_ticker(ticker)
        
        logger.info(f"Calculating swing score for {ticker}")
        
        # Get current price/volume if not provided
        if current_volume is None:
            current_price_data = await self.volume_analyzer.ts_client.get_current_price(ticker)
            if current_price_data:
                current_volume = current_price_data.get("volume", 0)
        
        # 1. Volume/Technical Analysis
        volume_score = await self._calculate_volume_technical_score(ticker, current_volume)
        
        # 2. Catalyst Analysis
        catalyst_score = await self._calculate_catalyst_score(ticker)
        
        # 3. Short Squeeze Analysis
        short_squeeze_score = await self._calculate_short_squeeze_score(ticker)
        
        # 4. Fundamental Analysis
        fundamental_score = await self._calculate_fundamental_score(ticker)
        
        # 5. Pump Potential (low float, high short, volume spike)
        pump_potential = await self.pump_potential_detector.detect_pump_potential(
            ticker, current_volume
        )
        
        # 6. Dilution Risk Check
        dilution_risk = await self.dilution_checker.check_dilution_risk(ticker)
        
        # Calculate weighted total score
        total_score = (
            volume_score["score"] * self.volume_technical_weight +
            catalyst_score["score"] * self.catalyst_weight +
            short_squeeze_score["score"] * self.short_squeeze_weight +
            fundamental_score["score"] * self.fundamental_weight
        )
        
        # Apply penalties
        penalties_total = 0.0
        penalty_reasons = []
        
        if dilution_risk.get("has_recent_dilution"):
            penalty = self.penalties.get("recent_dilution", -15)
            penalties_total += abs(penalty)
            penalty_reasons.append("Recent dilution")
        
        if dilution_risk.get("has_reverse_split"):
            penalty = self.penalties.get("upcoming_rs", -20)
            penalties_total += abs(penalty)
            penalty_reasons.append("Reverse split detected")
        
        if not fundamental_score.get("passes_filters"):
            penalty = self.penalties.get("negative_cash_flow", -10)
            penalties_total += abs(penalty)
            penalty_reasons.append("Financial filters failed")
        
        # Apply bonuses
        bonuses_total = 0.0
        bonus_reasons = []
        
        if volume_score.get("exceptional_volume"):
            bonus = self.bonuses.get("exceptional_volume", 5)
            bonuses_total += bonus
            bonus_reasons.append("Exceptional volume spike")
        
        if len(catalyst_score.get("catalysts", [])) > 1:
            bonus = self.bonuses.get("multiple_catalysts", 3)
            bonuses_total += bonus
            bonus_reasons.append("Multiple catalysts")
        
        if catalyst_score.get("strong_sentiment"):
            bonus = self.bonuses.get("strong_sentiment", 3)
            bonuses_total += bonus
            bonus_reasons.append("Strong sentiment")
        
        if pump_potential.get("has_pump_potential"):
            bonus = self.bonuses.get("pump_potential", 8)
            bonuses_total += bonus
            bonus_reasons.append("Pump potential")
        
        # Final score
        final_score = total_score - penalties_total + bonuses_total
        final_score = max(0.0, min(100.0, final_score))
        
        # Check if qualifies for alert
        qualifies = (
            final_score >= self.min_total_score and
            volume_score["score"] >= self.min_volume_technical_score and
            catalyst_score["score"] >= self.min_catalyst_score and
            fundamental_score["score"] >= self.min_fundamental_score and
            not dilution_risk.get("has_dilution_risk")
        )
        
        return {
            "ticker": ticker,
            "total_score": final_score,
            "qualifies": qualifies,
            "volume_technical": volume_score,
            "catalyst": catalyst_score,
            "short_squeeze": short_squeeze_score,
            "fundamental": fundamental_score,
            "pump_potential": pump_potential,
            "dilution_risk": dilution_risk,
            "penalties": {
                "total": penalties_total,
                "reasons": penalty_reasons
            },
            "bonuses": {
                "total": bonuses_total,
                "reasons": bonus_reasons
            },
            "timestamp": datetime.now().isoformat()
        }
    
    async def _calculate_volume_technical_score(
        self,
        ticker: str,
        current_volume: Optional[int]
    ) -> Dict[str, Any]:
        """Calculate volume and technical score.
        
        Args:
            ticker: Ticker symbol
            current_volume: Current volume
            
        Returns:
            Volume/technical score
        """
        score = 0.0
        factors = []
        exceptional_volume = False
        
        # Volume analysis
        if current_volume:
            volume_spike = await self.volume_analyzer.detect_volume_spike(
                ticker,
                current_volume
            )
            
            if volume_spike.get("has_spike"):
                multiplier = volume_spike.get("multiplier", 0.0)
                score += min(multiplier / self.volume_analyzer.volume_multiplier, 1.0) * 40
                factors.append(f"Volume spike: {multiplier:.2f}x average")
                
                if multiplier > 5.0:
                    exceptional_volume = True
            
            if volume_spike.get("is_sustained"):
                score += 20
                factors.append("Sustained volume")
        
        # Technical indicators
        technical_data = await self.technical_indicators.calculate_all_indicators(ticker)
        
        if "error" not in technical_data:
            signals = technical_data.get("signals", {})
            
            if signals.get("bullish_crossover"):
                score += 15
                factors.append("Bullish SMA crossover")
            
            if signals.get("macd_bullish"):
                score += 10
                factors.append("MACD bullish")
            
            if signals.get("price_above_sma"):
                score += 10
                factors.append("Price above SMA")
            
            if signals.get("rsi_oversold"):
                score += 5
                factors.append("RSI oversold (potential bounce)")
            
            # Check for breakout
            breakout = await self.technical_indicators.detect_breakout(ticker)
            if breakout.get("has_breakout"):
                score += 15
                factors.append("Price breakout detected")
        
        return {
            "score": min(score, 100.0),
            "factors": factors,
            "exceptional_volume": exceptional_volume
        }
    
    async def _calculate_catalyst_score(self, ticker: str) -> Dict[str, Any]:
        """Calculate catalyst score.
        
        Args:
            ticker: Ticker symbol
            
        Returns:
            Catalyst score
        """
        catalyst_analysis = await self.catalyst_detector.analyze_catalyst_strength(ticker)
        
        score = catalyst_analysis.get("catalyst_score", 0.0)
        catalysts = catalyst_analysis.get("catalysts", [])
        
        # Check for strong sentiment
        strong_sentiment = False
        if catalysts:
            avg_sentiment = sum(c.get("sentiment_score", 0) for c in catalysts) / len(catalysts)
            strong_sentiment = avg_sentiment > 0.7
        
        return {
            "score": score,
            "catalysts": catalysts,
            "strongest_catalyst": catalyst_analysis.get("strongest_catalyst"),
            "strong_sentiment": strong_sentiment
        }
    
    async def _calculate_short_squeeze_score(self, ticker: str) -> Dict[str, Any]:
        """Calculate short squeeze score.
        
        Args:
            ticker: Ticker symbol
            
        Returns:
            Short squeeze score
        """
        squeeze_analysis = await self.short_squeeze_detector.detect_short_squeeze_potential(ticker)
        
        score = squeeze_analysis.get("score", 0.0)
        
        return {
            "score": score,
            "has_potential": squeeze_analysis.get("has_squeeze_potential", False),
            "factors": squeeze_analysis.get("factors", [])
        }
    
    async def _calculate_fundamental_score(self, ticker: str) -> Dict[str, Any]:
        """Calculate fundamental score.
        
        Args:
            ticker: Ticker symbol
            
        Returns:
            Fundamental score
        """
        fundamental_analysis = await self.fundamental_analyzer.analyze_fundamentals(ticker)
        
        return {
            "score": fundamental_analysis.get("score", 0.0),
            "passes_filters": fundamental_analysis.get("passes_filters", False),
            "factors": fundamental_analysis.get("factors", []),
            "risk_factors": fundamental_analysis.get("risk_factors", [])
        }

