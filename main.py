"""Main entry point for the Stock Trading Assistant."""
import asyncio
import signal
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import List, Dict, Any, Optional
from utils.logger import setup_logging, get_logger
from utils.helpers import get_settings, get_env_var, normalize_ticker
from ingestion.websocket_handler import WebSocketHandler
import httpx
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
        # Per-ticker cooldown (all-stocks mode): don't re-run full score too often
        self._ticker_last_check: Dict[str, float] = {}
        # Limit concurrent scoring to avoid exhausting Postgres connections (each score uses many pools)
        max_concurrent_scoring = self.settings.get("apis", {}).get("polygon", {}).get("max_concurrent_scoring", 1)
        self._scoring_semaphore = asyncio.Semaphore(max_concurrent_scoring)
        
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
        polygon_cfg = self.settings.get("apis", {}).get("polygon", {})
        monitor_all = polygon_cfg.get("monitor_all_stocks", False)
        poll_tickers = tickers  # for news/fundamentals; empty when monitoring all stocks
        
        if self.settings["apis"]["polygon"]["enabled"]:
            await self.ws_handler.connect()
            
            if monitor_all:
                # Subscribe to all stocks (Polygon A.*); any stock can trigger an alert
                await self.ws_handler.subscribe(["*"])
                logger.info("WebSocket handler started: monitoring ALL stocks")
                poll_tickers = []  # news/fundamentals fetched on demand during scoring
            else:
                await self.ws_handler.subscribe(tickers)
                logger.info(f"WebSocket handler started for {len(tickers)} tickers")
            
            # Register message handler for volume spike detection
            self.ws_handler.register_handler(self._handle_market_data)
            
            # Start listening in background
            asyncio.create_task(self.ws_handler.listen())
        
        # Start news fetcher (skip when monitoring all stocks)
        if poll_tickers:
            asyncio.create_task(self.news_fetcher.start_polling(poll_tickers))
            logger.info("News fetcher started")
        # Start fundamentals updater
        if poll_tickers:
            asyncio.create_task(self.fundamentals_updater.start_updating(poll_tickers))
            logger.info("Fundamentals updater started")

        # Start REST API poller (gainers + most-active) — works on most Polygon plans
        polygon_cfg = self.settings.get("apis", {}).get("polygon", {})
        if polygon_cfg.get("rest_poll_enabled", True):
            asyncio.create_task(self._poll_rest_api())
            logger.info("REST API poller started (gainers + losers, market hours only)")

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
                ticker = message.get("sym", "").replace("A.", "").strip()
                if not ticker:
                    return
                ticker = normalize_ticker(ticker)
                volume = message.get("v", 0) or 0
                close = message.get("c", 0)
                
                polygon_cfg = self.settings.get("apis", {}).get("polygon", {})
                monitor_all = polygon_cfg.get("monitor_all_stocks", False)
                min_volume = polygon_cfg.get("min_volume_to_consider", 50_000)
                cooldown_sec = polygon_cfg.get("per_ticker_cooldown_seconds", 120)
                
                if volume <= 0:
                    return
                # In all-stocks mode: only run full score when volume is meaningful and cooldown passed
                if monitor_all:
                    if volume < min_volume:
                        return
                    now = time.monotonic()
                    if ticker in self._ticker_last_check and (now - self._ticker_last_check[ticker]) < cooldown_sec:
                        return
                    self._ticker_last_check[ticker] = now
                
                # Limit concurrent scoring so we don't exhaust DB connections (each score uses many pools)
                async with self._scoring_semaphore:
                    alert = await self.alert_manager.check_and_create_alert(ticker, volume)
                if alert:
                    logger.info(f"Alert created for {ticker}: {alert['score']:.1f}/100")
                    asyncio.create_task(self._push_alert_to_dashboard(alert))
        
        except Exception as e:
            logger.error(f"Error handling market data: {e}")

    def _get_trading_session(self) -> Optional[str]:
        """Return the current US trading session or None if markets are fully closed.

        Sessions (ET, Mon–Fri):
          pre_market  : 04:00 – 09:29
          regular     : 09:30 – 15:59
          after_hours : 16:00 – 20:00
        """
        et = ZoneInfo("America/New_York")
        now = datetime.now(tz=et)
        if now.weekday() >= 5:  # Saturday / Sunday
            return None
        t = now.hour * 60 + now.minute  # minutes since midnight
        if 4 * 60 <= t < 9 * 60 + 30:
            return "pre_market"
        if 9 * 60 + 30 <= t < 16 * 60:
            return "regular"
        if 16 * 60 <= t <= 20 * 60:
            return "after_hours"
        return None

    async def _poll_rest_api(self):
        """Poll Polygon REST API for gainers/losers and score them.

        Covers pre-market (4–9:30 AM ET), regular (9:30–4 PM ET), and
        after-hours (4–8 PM ET) sessions. Uses the correct volume field for each.
        """
        polygon_cfg = self.settings.get("apis", {}).get("polygon", {})
        api_key = get_env_var("POLYGON_API_KEY")
        base_url = polygon_cfg.get("base_url", "https://api.polygon.io")
        interval = polygon_cfg.get("rest_poll_interval_seconds", 60)
        min_volume = polygon_cfg.get("rest_poll_min_volume", 500_000)
        max_tickers = polygon_cfg.get("rest_poll_max_tickers", 20)
        cooldown_sec = polygon_cfg.get("per_ticker_cooldown_seconds", 120)

        # Lower volume threshold for extended-hours (thinner markets)
        extended_min_volume = max(min_volume // 5, 50_000)

        logger.info("REST API poller started (pre-market, regular, after-hours; every %ss)", interval)

        while self.running:
            session = self._get_trading_session()
            if session is None:
                et = ZoneInfo("America/New_York")
                now_et = datetime.now(tz=et)
                logger.info(
                    "All sessions closed (ET %s). REST poller waiting %ss.",
                    now_et.strftime("%H:%M"), interval,
                )
                await asyncio.sleep(interval)
                continue

            # Volume field per session
            vol_key = {"pre_market": "preMarket", "regular": "day", "after_hours": "afterHours"}.get(session, "day")
            vol_threshold = min_volume if session == "regular" else extended_min_volume

            tickers_to_score: Dict[str, int] = {}
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    for endpoint in [
                        f"{base_url}/v2/snapshot/locale/us/markets/stocks/gainers?apiKey={api_key}",
                        f"{base_url}/v2/snapshot/locale/us/markets/stocks/losers?apiKey={api_key}",
                    ]:
                        resp = await client.get(endpoint)
                        if resp.status_code != 200:
                            logger.warning("REST poll %s → HTTP %s", endpoint.split("?")[0], resp.status_code)
                            continue
                        for item in resp.json().get("tickers", []):
                            sym = normalize_ticker(item.get("ticker", ""))
                            if not sym:
                                continue
                            # Use session-specific block; fall back to 'day'
                            block = item.get(vol_key) or item.get("day") or {}
                            vol = int(block.get("v", 0) or 0)
                            if vol >= vol_threshold:
                                tickers_to_score[sym] = vol
            except Exception as e:
                logger.warning("REST poll request failed: %s", e)
                await asyncio.sleep(interval)
                continue

            if not tickers_to_score:
                logger.info(
                    "REST poll [%s]: no qualifying tickers (vol >= %s). Sleeping %ss.",
                    session, vol_threshold, interval,
                )
                await asyncio.sleep(interval)
                continue

            scored = 0
            mono_now = time.monotonic()
            for sym, vol in list(tickers_to_score.items())[:max_tickers]:
                if sym in self._ticker_last_check and (mono_now - self._ticker_last_check[sym]) < cooldown_sec:
                    continue
                self._ticker_last_check[sym] = mono_now
                try:
                    async with self._scoring_semaphore:
                        alert = await self.alert_manager.check_and_create_alert(sym, vol)
                    if alert:
                        logger.info("REST poll alert [%s]: %s score=%.1f", session, sym, alert["score"])
                        asyncio.create_task(self._push_alert_to_dashboard(alert))
                    scored += 1
                except Exception as e:
                    logger.error("REST poll scoring error for %s: %s", sym, e)

            logger.info(
                "REST poll [%s]: scored %s tickers (vol>=%s). Sleeping %ss.",
                session, scored, vol_threshold, interval,
            )
            await asyncio.sleep(interval)

    async def _push_alert_to_dashboard(self, alert: Dict[str, Any]):
        """POST alert to webhook server so the dashboard shows it in real time."""
        base = get_env_var("WEBHOOK_SERVER_URL", "http://localhost:8000").rstrip("/")
        url = f"{base}/api/v1/alerts/push"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.post(url, json=alert)
                if r.status_code != 200:
                    logger.warning("Dashboard push failed: %s %s", r.status_code, r.text)
        except Exception as e:
            logger.debug("Could not push alert to dashboard (is webhook server running?): %s", e)

async def main():
    """Main entry point."""
    assistant = StockTradingAssistant()
    settings = get_settings()
    polygon_cfg = settings.get("apis", {}).get("polygon", {})
    
    # When monitor_all_stocks is true in config, we subscribe to A.* (all stocks).
    # Otherwise use a fixed list of tickers.
    if polygon_cfg.get("monitor_all_stocks", False):
        tickers = ["*"]  # subscribe_all is handled in start()
    else:
        tickers = ["AAPL", "MSFT", "GOOGL", "TSLA", "NVDA"]  # or from config
    
    try:
        await assistant.start(tickers)
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    finally:
        await assistant.stop()

if __name__ == "__main__":
    asyncio.run(main())

