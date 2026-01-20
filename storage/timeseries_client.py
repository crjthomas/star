"""TimescaleDB client wrapper for time-series operations."""
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from storage.sql_client import SQLClient
from utils.logger import get_logger
from utils.helpers import get_trading_days_ago

logger = get_logger(__name__)

class TimeseriesClient(SQLClient):
    """TimescaleDB client for time-series stock data."""
    
    async def get_volume_statistics(
        self,
        ticker: str,
        days: int = 20
    ) -> Dict[str, Any]:
        """Get volume statistics for a ticker.
        
        Args:
            ticker: Ticker symbol
            days: Number of days to look back
            
        Returns:
            Dictionary with average_volume, max_volume, min_volume
        """
        end_time = datetime.now()
        start_time = get_trading_days_ago(days, end_time)
        
        async with self.pool.acquire() as conn:
            stats = await conn.fetchrow("""
                SELECT 
                    AVG(volume) as avg_volume,
                    MAX(volume) as max_volume,
                    MIN(volume) as min_volume,
                    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY volume) as median_volume,
                    STDDEV(volume) as stddev_volume
                FROM stock_prices
                WHERE ticker = $1 
                AND time >= $2 
                AND time <= $3
                AND volume > 0;
            """, ticker.upper(), start_time, end_time)
            
            if stats and stats['avg_volume']:
                return {
                    "average_volume": float(stats['avg_volume']),
                    "max_volume": int(stats['max_volume']) if stats['max_volume'] else 0,
                    "min_volume": int(stats['min_volume']) if stats['min_volume'] else 0,
                    "median_volume": float(stats['median_volume']) if stats['median_volume'] else 0,
                    "stddev_volume": float(stats['stddev_volume']) if stats['stddev_volume'] else 0,
                }
            
            return {
                "average_volume": 0,
                "max_volume": 0,
                "min_volume": 0,
                "median_volume": 0,
                "stddev_volume": 0,
            }
    
    async def get_price_range(
        self,
        ticker: str,
        days: int = 20
    ) -> Dict[str, Any]:
        """Get price range for a ticker.
        
        Args:
            ticker: Ticker symbol
            days: Number of days to look back
            
        Returns:
            Dictionary with high, low, close
        """
        end_time = datetime.now()
        start_time = get_trading_days_ago(days, end_time)
        
        async with self.pool.acquire() as conn:
            stats = await conn.fetchrow("""
                SELECT 
                    MAX(high) as high,
                    MIN(low) as low,
                    (SELECT close FROM stock_prices 
                     WHERE ticker = $1 AND time <= $3 
                     ORDER BY time DESC LIMIT 1) as close
                FROM stock_prices
                WHERE ticker = $1 
                AND time >= $2 
                AND time <= $3;
            """, ticker.upper(), start_time, end_time)
            
            if stats:
                return {
                    "high": float(stats['high']) if stats['high'] else None,
                    "low": float(stats['low']) if stats['low'] else None,
                    "close": float(stats['close']) if stats['close'] else None,
                }
            
            return {"high": None, "low": None, "close": None}
    
    async def get_current_price(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Get current/latest price for a ticker.
        
        Args:
            ticker: Ticker symbol
            
        Returns:
            Dictionary with latest price data or None
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT time, open, high, low, close, volume, vwap
                FROM stock_prices
                WHERE ticker = $1
                ORDER BY time DESC
                LIMIT 1;
            """, ticker.upper())
            
            if row:
                return dict(row)
            return None
    
    async def get_multi_day_trend(
        self,
        ticker: str,
        days: int = 5
    ) -> Dict[str, Any]:
        """Get multi-day price trend.
        
        Args:
            ticker: Ticker symbol
            days: Number of days to analyze
            
        Returns:
            Dictionary with trend data (direction, change_pct, days_analyzed)
        """
        end_time = datetime.now()
        start_time = get_trading_days_ago(days, end_time)
        
        prices = await self.get_price_history(ticker, start_time, end_time)
        
        if len(prices) < 2:
            return {
                "direction": "neutral",
                "change_pct": 0.0,
                "days_analyzed": len(prices)
            }
        
        first_close = float(prices[0]['close'])
        last_close = float(prices[-1]['close'])
        change_pct = ((last_close - first_close) / first_close) * 100
        
        if change_pct > 5:
            direction = "strong_up"
        elif change_pct > 2:
            direction = "up"
        elif change_pct < -5:
            direction = "strong_down"
        elif change_pct < -2:
            direction = "down"
        else:
            direction = "neutral"
        
        return {
            "direction": direction,
            "change_pct": change_pct,
            "days_analyzed": len(prices),
            "first_close": first_close,
            "last_close": last_close
        }

