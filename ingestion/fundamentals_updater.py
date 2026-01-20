"""Fundamentals updater for periodic financial data updates."""
import asyncio
from typing import List, Dict, Any
from datetime import datetime
from utils.logger import get_logger
from utils.helpers import normalize_ticker
from storage.sql_client import SQLClient
from mcp_tools.fundamentals_mcp_server import FundamentalsMCPServer

logger = get_logger(__name__)

class FundamentalsUpdater:
    """Updates fundamental financial data periodically."""
    
    def __init__(self):
        self.sql_client = SQLClient()
        self.fundamentals_server = FundamentalsMCPServer()
        self.running = False
        self.update_interval_hours = 24  # Update once per day
        
    async def connect(self):
        """Initialize database connections."""
        await self.sql_client.connect()
        await self.fundamentals_server.connect()
        logger.info("Fundamentals Updater connected")
    
    async def disconnect(self):
        """Close database connections."""
        await self.sql_client.disconnect()
        await self.fundamentals_server.disconnect()
        logger.info("Fundamentals Updater disconnected")
    
    async def update_ticker_fundamentals(self, ticker: str):
        """Update fundamental data for a ticker.
        
        Args:
            ticker: Ticker symbol
        """
        try:
            # Get fundamentals
            result = await self.fundamentals_server.call_tool(
                "get_fundamentals",
                {"ticker": ticker}
            )
            
            if not result.get("success"):
                logger.error(f"Failed to get fundamentals for {ticker}: {result.get('error')}")
                return
            
            fundamentals = result.get("data", {})
            
            if "error" in fundamentals:
                logger.error(f"Error in fundamentals data for {ticker}: {fundamentals['error']}")
                return
            
            # Store in database
            await self.sql_client.insert_fundamentals(
                ticker=ticker,
                date=datetime.now(),
                market_cap=fundamentals.get("market_cap"),
                revenue=fundamentals.get("total_revenue"),
                net_income=fundamentals.get("net_income"),
                total_debt=fundamentals.get("total_debt"),
                total_equity=fundamentals.get("book_value"),  # Using book value as equity proxy
                cash_and_equivalents=fundamentals.get("total_cash"),
                shares_outstanding=fundamentals.get("shares_outstanding"),
                current_ratio=fundamentals.get("current_ratio"),
                debt_to_equity=fundamentals.get("debt_to_equity")
            )
            
            logger.info(f"Updated fundamentals for {ticker}")
        
        except Exception as e:
            logger.error(f"Error updating fundamentals for {ticker}: {e}")
    
    async def update_all_tickers(self, tickers: List[str]):
        """Update fundamentals for multiple tickers.
        
        Args:
            tickers: List of ticker symbols
        """
        # Process in batches to avoid rate limits
        batch_size = 10
        for i in range(0, len(tickers), batch_size):
            batch = tickers[i:i + batch_size]
            
            tasks = [self.update_ticker_fundamentals(t) for t in batch]
            await asyncio.gather(*tasks, return_exceptions=True)
            
            # Rate limiting delay between batches
            if i + batch_size < len(tickers):
                await asyncio.sleep(5)
    
    async def start_updating(self, tickers: List[str]):
        """Start periodic updates.
        
        Args:
            tickers: List of ticker symbols to monitor
        """
        self.running = True
        logger.info(f"Starting fundamentals updates for {len(tickers)} tickers (interval: {self.update_interval_hours} hours)")
        
        while self.running:
            try:
                await self.update_all_tickers(tickers)
                
                # Wait for next update
                await asyncio.sleep(self.update_interval_hours * 3600)
            
            except Exception as e:
                logger.error(f"Error in update loop: {e}")
                await asyncio.sleep(3600)  # Wait 1 hour before retry
    
    def stop_updating(self):
        """Stop periodic updates."""
        self.running = False
        logger.info("Stopped fundamentals updates")

