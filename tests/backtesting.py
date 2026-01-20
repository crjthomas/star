"""Backtesting module for validating scoring model."""
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from utils.logger import get_logger
from utils.helpers import get_settings, get_scoring_weights, normalize_ticker
from storage.timeseries_client import TimeseriesClient
from scoring.swing_score_calculator import SwingScoreCalculator

logger = get_logger(__name__)

class Backtester:
    """Backtests scoring model using historical data."""
    
    def __init__(self):
        self.settings = get_settings()
        self.scoring_weights = get_scoring_weights()
        self.ts_client = TimeseriesClient()
        self.score_calculator = SwingScoreCalculator()
        
    async def connect(self):
        """Initialize connections."""
        await self.ts_client.connect()
        await self.score_calculator.connect()
        logger.info("Backtester connected")
    
    async def disconnect(self):
        """Close connections."""
        await self.ts_client.disconnect()
        await self.score_calculator.disconnect()
    
    async def backtest_ticker(
        self,
        ticker: str,
        start_date: datetime,
        end_date: datetime,
        lookback_days: int = 5
    ) -> Dict[str, Any]:
        """Backtest scoring model for a single ticker.
        
        Args:
            ticker: Ticker symbol
            start_date: Start date for backtesting
            end_date: End date for backtesting
            lookback_days: Days to look ahead to measure performance
            
        Returns:
            Backtest results
        """
        ticker = normalize_ticker(ticker)
        
        # Get historical prices
        prices = await self.ts_client.get_price_history(ticker, start_date, end_date)
        
        if len(prices) < lookback_days:
            return {
                "ticker": ticker,
                "error": "Insufficient data",
                "total_signals": 0
            }
        
        signals = []
        wins = 0
        losses = 0
        total_return = 0.0
        
        # Test each day
        for i in range(len(prices) - lookback_days):
            current_date = prices[i]["time"]
            current_price = prices[i]["close"]
            current_volume = prices[i]["volume"]
            
            # Calculate score at this point
            try:
                score_result = await self.score_calculator.calculate_score(
                    ticker,
                    current_volume
                )
            except Exception as e:
                logger.warning(f"Error calculating score for {ticker} at {current_date}: {e}")
                continue
            
            if not score_result.get("qualifies"):
                continue
            
            # Get future price
            future_idx = i + lookback_days
            if future_idx >= len(prices):
                continue
            
            future_price = prices[future_idx]["close"]
            future_date = prices[future_idx]["time"]
            
            # Calculate return
            return_pct = ((future_price - current_price) / current_price) * 100
            
            is_win = return_pct > 0
            
            signal = {
                "date": current_date.isoformat() if hasattr(current_date, 'isoformat') else str(current_date),
                "entry_price": current_price,
                "exit_price": future_price,
                "exit_date": future_date.isoformat() if hasattr(future_date, 'isoformat') else str(future_date),
                "return_pct": return_pct,
                "score": score_result.get("total_score", 0),
                "is_win": is_win
            }
            
            signals.append(signal)
            
            if is_win:
                wins += 1
            else:
                losses += 1
            
            total_return += return_pct
        
        win_rate = (wins / len(signals) * 100) if signals else 0
        avg_return = (total_return / len(signals)) if signals else 0
        
        return {
            "ticker": ticker,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "total_signals": len(signals),
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate,
            "avg_return_pct": avg_return,
            "total_return_pct": total_return,
            "signals": signals
        }
    
    async def backtest_multiple_tickers(
        self,
        tickers: List[str],
        start_date: datetime,
        end_date: datetime,
        lookback_days: int = 5
    ) -> Dict[str, Any]:
        """Backtest scoring model for multiple tickers.
        
        Args:
            tickers: List of ticker symbols
            start_date: Start date for backtesting
            end_date: End date for backtesting
            lookback_days: Days to look ahead to measure performance
            
        Returns:
            Aggregate backtest results
        """
        results = []
        
        for ticker in tickers:
            try:
                result = await self.backtest_ticker(
                    ticker,
                    start_date,
                    end_date,
                    lookback_days
                )
                results.append(result)
            except Exception as e:
                logger.error(f"Error backtesting {ticker}: {e}")
        
        # Aggregate results
        total_signals = sum(r.get("total_signals", 0) for r in results)
        total_wins = sum(r.get("wins", 0) for r in results)
        total_losses = sum(r.get("losses", 0) for r in results)
        total_return = sum(r.get("total_return_pct", 0) for r in results)
        
        overall_win_rate = (total_wins / total_signals * 100) if total_signals > 0 else 0
        overall_avg_return = (total_return / total_signals) if total_signals > 0 else 0
        
        return {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "lookback_days": lookback_days,
            "tickers_tested": len(tickers),
            "total_signals": total_signals,
            "total_wins": total_wins,
            "total_losses": total_losses,
            "overall_win_rate": overall_win_rate,
            "overall_avg_return_pct": overall_avg_return,
            "total_return_pct": total_return,
            "ticker_results": results
        }
    
    async def optimize_weights(
        self,
        tickers: List[str],
        start_date: datetime,
        end_date: datetime,
        lookback_days: int = 5
    ) -> Dict[str, Any]:
        """Optimize scoring weights based on backtest performance.
        
        Args:
            tickers: List of ticker symbols to test
            start_date: Start date for backtesting
            end_date: End date for backtesting
            lookback_days: Days to look ahead
            
        Returns:
            Optimization results with suggested weights
        """
        # This is a simplified optimization - in production, you'd use
        # more sophisticated methods (genetic algorithms, grid search, etc.)
        
        logger.info("Optimizing scoring weights...")
        
        # Test with current weights
        current_results = await self.backtest_multiple_tickers(
            tickers,
            start_date,
            end_date,
            lookback_days
        )
        
        # For now, return current results with note about optimization
        # In production, this would test different weight combinations
        
        return {
            "optimization_complete": False,
            "message": "Weight optimization requires more sophisticated implementation",
            "current_performance": current_results,
            "suggested_weights": self.scoring_weights.get("weights", {}),
            "note": "Consider using grid search or genetic algorithms for weight optimization"
        }

