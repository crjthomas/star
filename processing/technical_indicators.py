"""Technical indicator calculations."""
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
from utils.logger import get_logger
from utils.helpers import get_settings
from storage.timeseries_client import TimeseriesClient

logger = get_logger(__name__)

class TechnicalIndicators:
    """Calculates technical indicators."""
    
    def __init__(self):
        self.settings = get_settings()
        self.ts_client = TimeseriesClient()
        signal_config = self.settings.get("signal_detection", {}).get("technical_indicators", {})
        self.rsi_period = 14
        self.rsi_oversold = signal_config.get("rsi_oversold", 30)
        self.rsi_overbought = signal_config.get("rsi_overbought", 70)
        self.macd_fast = 12
        self.macd_slow = 26
        self.macd_signal = signal_config.get("macd_signal_period", 9)
        self.sma_short = signal_config.get("sma_short_period", 10)
        self.sma_long = signal_config.get("sma_long_period", 50)
        
    async def connect(self):
        """Initialize database connection."""
        await self.ts_client.connect()
        logger.info("Technical Indicators connected")
    
    async def disconnect(self):
        """Close database connection."""
        await self.ts_client.disconnect()
    
    async def calculate_all_indicators(
        self,
        ticker: str,
        days: int = 50
    ) -> Dict[str, Any]:
        """Calculate all technical indicators for a ticker.
        
        Args:
            ticker: Ticker symbol
            days: Number of days of data to use
            
        Returns:
            Dictionary with all indicators
        """
        end_time = datetime.now()
        start_time = end_time - timedelta(days=days)
        
        prices = await self.ts_client.get_price_history(
            ticker,
            start_time,
            end_time
        )
        
        if len(prices) < self.sma_long:
            return {"error": "Insufficient data"}
        
        # Convert to DataFrame
        df = pd.DataFrame(prices)
        df['time'] = pd.to_datetime(df['time'])
        df.set_index('time', inplace=True)
        df.sort_index(inplace=True)
        
        closes = df['close'].values
        
        # Calculate indicators
        rsi = self._calculate_rsi(closes)
        macd_data = self._calculate_macd(closes)
        sma_short = self._calculate_sma(closes, self.sma_short)
        sma_long = self._calculate_sma(closes, self.sma_long)
        
        # Get current values
        current_rsi = rsi[-1] if len(rsi) > 0 else None
        current_price = closes[-1] if len(closes) > 0 else None
        current_sma_short = sma_short[-1] if len(sma_short) > 0 else None
        current_sma_long = sma_long[-1] if len(sma_long) > 0 else None
        
        # Detect signals
        signals = {
            "rsi_oversold": current_rsi is not None and current_rsi < self.rsi_oversold,
            "rsi_overbought": current_rsi is not None and current_rsi > self.rsi_overbought,
            "bullish_crossover": current_sma_short is not None and current_sma_long is not None and \
                                len(sma_short) > 1 and len(sma_long) > 1 and \
                                sma_short[-1] > sma_long[-1] and sma_short[-2] <= sma_long[-2],
            "macd_bullish": macd_data["signal"] == "bullish",
            "price_above_sma": current_price is not None and current_sma_short is not None and \
                              current_price > current_sma_short
        }
        
        return {
            "ticker": ticker,
            "rsi": current_rsi,
            "macd": macd_data,
            "sma_short": current_sma_short,
            "sma_long": current_sma_long,
            "current_price": current_price,
            "signals": signals,
            "timestamp": datetime.now().isoformat()
        }
    
    def _calculate_rsi(self, closes: np.ndarray, period: int = None) -> np.ndarray:
        """Calculate RSI (Relative Strength Index).
        
        Args:
            closes: Array of closing prices
            period: RSI period (default: self.rsi_period)
            
        Returns:
            Array of RSI values
        """
        if period is None:
            period = self.rsi_period
        
        if len(closes) < period + 1:
            return np.array([])
        
        deltas = np.diff(closes)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        
        avg_gains = np.zeros_like(closes)
        avg_losses = np.zeros_like(closes)
        
        # Initial average
        avg_gains[period] = np.mean(gains[:period])
        avg_losses[period] = np.mean(losses[:period])
        
        # Smooth averages
        for i in range(period + 1, len(closes)):
            avg_gains[i] = (avg_gains[i-1] * (period - 1) + gains[i-1]) / period
            avg_losses[i] = (avg_losses[i-1] * (period - 1) + losses[i-1]) / period
        
        # Calculate RSI
        rs = np.where(avg_losses != 0, avg_gains / avg_losses, 0)
        rsi = 100 - (100 / (1 + rs))
        
        return rsi[period:]
    
    def _calculate_macd(
        self,
        closes: np.ndarray
    ) -> Dict[str, Any]:
        """Calculate MACD (Moving Average Convergence Divergence).
        
        Args:
            closes: Array of closing prices
            
        Returns:
            Dictionary with MACD data
        """
        if len(closes) < self.macd_slow:
            return {"error": "Insufficient data"}
        
        ema_fast = self._calculate_ema(closes, self.macd_fast)
        ema_slow = self._calculate_ema(closes, self.macd_slow)
        
        if len(ema_fast) < len(ema_slow):
            ema_slow = ema_slow[-len(ema_fast):]
        elif len(ema_slow) < len(ema_fast):
            ema_fast = ema_fast[-len(ema_slow):]
        
        macd_line = ema_fast - ema_slow
        
        # Calculate signal line (EMA of MACD line)
        if len(macd_line) < self.macd_signal:
            signal_line = np.array([])
        else:
            signal_line = self._calculate_ema(macd_line, self.macd_signal)
        
        # Determine signal
        if len(signal_line) > 0 and len(macd_line) >= len(signal_line):
            current_macd = macd_line[-1]
            current_signal = signal_line[-1]
            
            if len(macd_line) > 1 and len(signal_line) > 1:
                prev_macd = macd_line[-2]
                prev_signal = signal_line[-2]
                
                # Bullish crossover
                if prev_macd <= prev_signal and current_macd > current_signal:
                    signal = "bullish"
                # Bearish crossover
                elif prev_macd >= prev_signal and current_macd < current_signal:
                    signal = "bearish"
                else:
                    signal = "neutral"
            else:
                signal = "neutral"
            
            histogram = current_macd - current_signal
        else:
            signal = "neutral"
            current_macd = macd_line[-1] if len(macd_line) > 0 else 0
            current_signal = 0
            histogram = 0
        
        return {
            "macd": float(current_macd),
            "signal": float(current_signal),
            "histogram": float(histogram),
            "trend": signal
        }
    
    def _calculate_sma(self, data: np.ndarray, period: int) -> np.ndarray:
        """Calculate Simple Moving Average.
        
        Args:
            data: Array of values
            period: SMA period
            
        Returns:
            Array of SMA values
        """
        if len(data) < period:
            return np.array([])
        
        sma = np.zeros(len(data) - period + 1)
        for i in range(len(sma)):
            sma[i] = np.mean(data[i:i + period])
        
        return sma
    
    def _calculate_ema(self, data: np.ndarray, period: int) -> np.ndarray:
        """Calculate Exponential Moving Average.
        
        Args:
            data: Array of values
            period: EMA period
            
        Returns:
            Array of EMA values
        """
        if len(data) < period:
            return np.array([])
        
        ema = np.zeros(len(data) - period + 1)
        multiplier = 2.0 / (period + 1)
        
        # Initial value
        ema[0] = np.mean(data[:period])
        
        # Calculate subsequent values
        for i in range(1, len(ema)):
            ema[i] = (data[period + i - 1] - ema[i - 1]) * multiplier + ema[i - 1]
        
        return ema
    
    async def detect_breakout(
        self,
        ticker: str,
        days: int = 20
    ) -> Dict[str, Any]:
        """Detect price breakouts.
        
        Args:
            ticker: Ticker symbol
            days: Number of days to analyze
            
        Returns:
            Breakout detection result
        """
        price_range = await self.ts_client.get_price_range(ticker, days)
        current_price_data = await self.ts_client.get_current_price(ticker)
        
        if not current_price_data or not price_range.get("high"):
            return {"has_breakout": False}
        
        current_price = current_price_data.get("close", 0)
        resistance = price_range.get("high", 0)
        
        # Breakout if price exceeds recent high
        has_breakout = current_price > resistance * 1.02  # 2% above resistance
        
        return {
            "ticker": ticker,
            "has_breakout": has_breakout,
            "current_price": current_price,
            "resistance": resistance,
            "breakout_percent": ((current_price - resistance) / resistance * 100) if resistance > 0 else 0
        }

