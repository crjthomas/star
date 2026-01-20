"""Main entry point for the Stock Trading Assistant."""
import asyncio
import signal
from typing import List
from utils.logger import setup_logging, get_logger
from utils.helpers import get_settings
from ingestion.websocket_handler import WebSocketHandler
from ingestion.news_fetcher import NewsFetcher
from ingestion.fundamentals_updater import FundamentalsUpdater
from alerts.alert_manager import AlertManager
from storage.timeseries_client import TimeseriesClient

# Setup logging
setup_logging()

logger = get_logger(__name__)

class StockTradingAssistant:
    """Main application class."""
    
    def __init__(self):
        self.settings = get_settings()
        self.running = False
        
        # Initialize components
        self.ws_handler = WebSocketHandler()
        self.news_fetcher = NewsFetcher()
        self.fundamentals_updater = FundamentalsUpdater()
        self.alert_manager = AlertManager()
        self.ts_client = TimeseriesClient()
        
        # Track monitored tickers
        self.monitored_tickers: List[str] = []
        
    async def start(self, tickers: List[str]):
        """Start the trading assistant.
        
        Args:
            tickers: List of ticker symbols to monitor
        """
        logger.info("Starting Stock Trading Assistant...")
        
        self.monitored_tickers = tickers
        self.running = True
        
        # Connect to databases
        await self.ts_client.connect()
        await self.alert_manager.connect()
        
        # Register signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        # Start WebSocket handler
        if self.settings["apis"]["polygon"]["enabled"]:
            await self.ws_handler.connect()
            
            # Subscribe to tickers
            await self.ws_handler.subscribe(tickers)
            
            # Register message handler for volume spike detection
            self.ws_handler.register_handler(self._handle_market_data)
            
            # Start listening in background
            asyncio.create_task(self.ws_handler.listen())
            logger.info(f"WebSocket handler started for {len(tickers)} tickers")
        
        # Start news fetcher
        asyncio.create_task(self.news_fetcher.start_polling(tickers))
        logger.info("News fetcher started")
        
        # Start fundamentals updater (runs periodically)
        asyncio.create_task(self.fundamentals_updater.start_updating(tickers))
        logger.info("Fundamentals updater started")
        
        logger.info("Stock Trading Assistant started successfully")
        
        # Keep running
        try:
            while self.running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            logger.info("Stock Trading Assistant stopped")
    
    async def stop(self):
        """Stop the trading assistant."""
        logger.info("Stopping Stock Trading Assistant...")
        
        self.running = False
        
        # Disconnect components
        await self.ws_handler.disconnect()
        self.news_fetcher.stop_polling()
        self.fundamentals_updater.stop_updating()
        await self.alert_manager.disconnect()
        await self.ts_client.disconnect()
        
        logger.info("Stock Trading Assistant stopped")
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        logger.info(f"Received signal {signum}, shutting down...")
        self.running = False
    
    async def _handle_market_data(self, message: dict):
        """Handle incoming market data messages.
        
        Args:
            message: Market data message
        """
        try:
            event_type = message.get("ev")
            
            if event_type == "A":  # Aggregate (minute bars)
                ticker = message.get("sym", "").replace("A.", "")
                volume = message.get("v", 0)
                close = message.get("c", 0)
                
                # Check for volume spike and create alert if qualified
                if volume > 0:
                    alert = await self.alert_manager.check_and_create_alert(ticker, volume)
                    if alert:
                        logger.info(f"Alert created for {ticker}: {alert['score']:.1f}/100")
        
        except Exception as e:
            logger.error(f"Error handling market data: {e}")

async def main():
    """Main entry point."""
    assistant = StockTradingAssistant()
    
    # Example tickers to monitor
    # In production, this would come from config or user input
    tickers = ["AAPL", "MSFT", "GOOGL", "TSLA", "NVDA"]
    
    try:
        await assistant.start(tickers)
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    finally:
        await assistant.stop()

if __name__ == "__main__":
    asyncio.run(main())

