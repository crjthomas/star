"""Volume spike detection analyzer."""
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from utils.logger import get_logger
from utils.helpers import get_settings, normalize_ticker, safe_divide
from storage.timeseries_client import TimeseriesClient

logger = get_logger(__name__)

class VolumeAnalyzer:
    """Analyzes volume patterns and detects spikes."""
    
    def __init__(self):
        self.settings = get_settings()
        self.ts_client = TimeseriesClient()
        self.volume_multiplier = self.settings.get("signal_detection", {}).get("volume_spike_multiplier", 2.5)
        self.sustained_periods = self.settings.get("signal_detection", {}).get("volume_sustained_periods", 3)
        self.lookback_days = self.settings.get("signal_detection", {}).get("volume_lookback_days", 20)
        
    async def connect(self):
        """Initialize database connection."""
        await self.ts_client.connect()
        logger.info("Volume Analyzer connected")
    
    async def disconnect(self):
        """Close database connection."""
        await self.ts_client.disconnect()
    
    async def detect_volume_spike(
        self,
        ticker: str,
        current_volume: int,
        current_time: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """Detect if there's a volume spike.
        
        Args:
            ticker: Ticker symbol
            current_volume: Current volume
            current_time: Current timestamp
            
        Returns:
            Volume spike detection result
        """
        if current_time is None:
            current_time = datetime.now()
        
        ticker = normalize_ticker(ticker)
        
        # Get volume statistics
        volume_stats = await self.ts_client.get_volume_statistics(
            ticker,
            self.lookback_days
        )
        
        avg_volume = volume_stats.get("average_volume", 0)
        median_volume = volume_stats.get("median_volume", 0)
        
        if avg_volume == 0:
            return {
                "ticker": ticker,
                "has_spike": False,
                "current_volume": current_volume,
                "average_volume": 0,
                "multiplier": 0.0,
                "reason": "Insufficient historical data"
            }
        
        # Calculate multiplier
        multiplier = safe_divide(current_volume, avg_volume, 0.0)
        
        # Check if it's a spike
        has_spike = multiplier >= self.volume_multiplier
        
        # Check if volume is sustained (if we have recent data)
        is_sustained = await self._check_sustained_volume(
            ticker,
            current_time
        )
        
        result = {
            "ticker": ticker,
            "has_spike": has_spike,
            "current_volume": current_volume,
            "average_volume": avg_volume,
            "median_volume": median_volume,
            "multiplier": multiplier,
            "is_sustained": is_sustained,
            "timestamp": current_time.isoformat()
        }
        
        if has_spike:
            logger.info(f"Volume spike detected for {ticker}: {multiplier:.2f}x average")
        
        return result
    
    async def _check_sustained_volume(
        self,
        ticker: str,
        current_time: datetime
    ) -> bool:
        """Check if volume is sustained over multiple periods.
        
        Args:
            ticker: Ticker symbol
            current_time: Current timestamp
            
        Returns:
            True if volume is sustained
        """
        try:
            # Get recent price history
            end_time = current_time
            start_time = current_time - timedelta(hours=self.sustained_periods)
            
            prices = await self.ts_client.get_price_history(
                ticker,
                start_time,
                end_time
            )
            
            if len(prices) < self.sustained_periods:
                return False
            
            # Get volume statistics for comparison
            volume_stats = await self.ts_client.get_volume_statistics(
                ticker,
                self.lookback_days
            )
            avg_volume = volume_stats.get("average_volume", 0)
            
            if avg_volume == 0:
                return False
            
            # Check if recent periods all have elevated volume
            elevated_periods = 0
            for price_data in prices[-self.sustained_periods:]:
                volume = price_data.get("volume", 0)
                if volume >= avg_volume * (self.volume_multiplier * 0.7):  # 70% of spike threshold
                    elevated_periods += 1
            
            return elevated_periods >= (self.sustained_periods * 0.7)
        
        except Exception as e:
            logger.error(f"Error checking sustained volume for {ticker}: {e}")
            return False
    
    async def analyze_volume_pattern(
        self,
        ticker: str,
        days: int = 5
    ) -> Dict[str, Any]:
        """Analyze volume pattern over multiple days.
        
        Args:
            ticker: Ticker symbol
            days: Number of days to analyze
            
        Returns:
            Volume pattern analysis
        """
        ticker = normalize_ticker(ticker)
        
        end_time = datetime.now()
        start_time = end_time - timedelta(days=days)
        
        prices = await self.ts_client.get_price_history(
            ticker,
            start_time,
            end_time
        )
        
        if not prices:
            return {
                "ticker": ticker,
                "pattern": "unknown",
                "avg_volume": 0,
                "trend": "unknown"
            }
        
        volumes = [p.get("volume", 0) for p in prices]
        avg_volume = sum(volumes) / len(volumes) if volumes else 0
        
        # Calculate trend (increasing, decreasing, stable)
        if len(volumes) >= 3:
            recent_avg = sum(volumes[-3:]) / 3
            earlier_avg = sum(volumes[:3]) / 3 if len(volumes) > 3 else recent_avg
            
            if recent_avg > earlier_avg * 1.2:
                trend = "increasing"
            elif recent_avg < earlier_avg * 0.8:
                trend = "decreasing"
            else:
                trend = "stable"
        else:
            trend = "unknown"
        
        # Determine pattern
        if avg_volume == 0:
            pattern = "no_data"
        elif max(volumes) > avg_volume * self.volume_multiplier:
            pattern = "spike_detected"
        elif trend == "increasing":
            pattern = "increasing_volume"
        else:
            pattern = "normal"
        
        return {
            "ticker": ticker,
            "pattern": pattern,
            "avg_volume": avg_volume,
            "max_volume": max(volumes) if volumes else 0,
            "trend": trend,
            "days_analyzed": len(prices)
        }

