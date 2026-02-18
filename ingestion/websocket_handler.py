"""WebSocket handler for real-time market data."""
import asyncio
import json
import ssl
import websockets
import certifi
from typing import Callable, List, Optional, Dict, Any
from datetime import datetime
from utils.logger import get_logger
from utils.helpers import get_settings, get_env_var, normalize_ticker
from storage.timeseries_client import TimeseriesClient

logger = get_logger(__name__)

class WebSocketHandler:
    """Handler for Polygon.io WebSocket streams."""
    
    def __init__(self):
        self.settings = get_settings()
        self.api_key = get_env_var("POLYGON_API_KEY")
        self.ws_url = self.settings["apis"]["polygon"]["websocket_url"]
        self.ts_client = TimeseriesClient()
        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        self.running = False
        self.subscribed_tickers: List[str] = []
        self.message_handlers: List[Callable] = []
        
    async def connect(self):
        """Connect to WebSocket and authenticate."""
        await self.ts_client.connect()
        
        # Use certifi CA bundle so SSL verify works on macOS (python.org installs)
        # Polygon URL is wss://socket.polygon.io/stocks (no /client); auth is sent after connect.
        ssl_ctx = ssl.create_default_context(cafile=certifi.where())
        self.websocket = await websockets.connect(
            self.ws_url,
            ssl=ssl_ctx,
        )
        
        # Authenticate
        auth_msg = {
            "action": "auth",
            "params": self.api_key
        }
        await self.websocket.send(json.dumps(auth_msg))
        response = await self.websocket.recv()
        logger.info(f"WebSocket authenticated: {response}")
        
        self.running = True
    
    async def disconnect(self):
        """Disconnect from WebSocket."""
        self.running = False
        if self.websocket:
            await self.websocket.close()
        await self.ts_client.disconnect()
        logger.info("WebSocket disconnected")
    
    async def subscribe(self, tickers: List[str]):
        """Subscribe to ticker symbols, or all stocks with ['*'].
        
        Args:
            tickers: List of ticker symbols, or ['*'] to subscribe to all stocks (A.*).
        """
        if not tickers or (len(tickers) == 1 and normalize_ticker(tickers[0]) == "*"):
            # Subscribe to all stock aggregates (Polygon wildcard).
            params = "A.*"
            self.subscribed_tickers = ["*"]
            logger.info("Subscribing to all stocks (A.*)")
        else:
            normalized_tickers = [normalize_ticker(t) for t in tickers]
            self.subscribed_tickers = normalized_tickers
            params = ",".join([f"A.{t}" for t in normalized_tickers])
            logger.info(f"Subscribed to {len(normalized_tickers)} tickers")

        subscribe_msg = {
            "action": "subscribe",
            "params": params
        }
        if self.websocket:
            await self.websocket.send(json.dumps(subscribe_msg))
            # Do not recv() here: Polygon often closes with 1000 (OK) if A.* is not allowed on this plan.
            # The listen loop will handle the next message or ConnectionClosed.
    
    async def unsubscribe(self, tickers: List[str]):
        """Unsubscribe from ticker symbols.
        
        Args:
            tickers: List of ticker symbols to unsubscribe from
        """
        normalized_tickers = [normalize_ticker(t) for t in tickers]
        self.subscribed_tickers = [
            t for t in self.subscribed_tickers 
            if t not in normalized_tickers
        ]
        
        unsubscribe_msg = {
            "action": "unsubscribe",
            "params": ",".join([f"A.{t}" for t in normalized_tickers])
        }
        
        if self.websocket:
            await self.websocket.send(json.dumps(unsubscribe_msg))
            logger.info(f"Unsubscribed from {len(normalized_tickers)} tickers")
    
    def register_handler(self, handler: Callable[[Dict[str, Any]], None]):
        """Register a message handler.
        
        Args:
            handler: Async function that processes messages
        """
        self.message_handlers.append(handler)
    
    async def _process_message(self, message: Dict[str, Any]):
        """Process incoming WebSocket message.
        
        Args:
            message: Message data
        """
        try:
            event_type = message.get("ev")
            
            if event_type == "A":  # Aggregate (minute bars)
                await self._handle_aggregate(message)
            elif event_type == "T":  # Trade
                await self._handle_trade(message)
            
            # Call registered handlers
            for handler in self.message_handlers:
                try:
                    await handler(message)
                except Exception as e:
                    logger.error(f"Error in message handler: {e}")
        
        except Exception as e:
            logger.error(f"Error processing message: {e}")
    
    async def _handle_aggregate(self, message: Dict[str, Any]):
        """Handle aggregate (minute bar) message.
        
        Args:
            message: Aggregate message data
        """
        ticker = message.get("sym", "").replace("A.", "")
        timestamp_ms = message.get("s", message.get("t", 0))
        timestamp = datetime.fromtimestamp(timestamp_ms / 1000)
        
        await self.ts_client.insert_price_data(
            ticker=ticker,
            time=timestamp,
            open=message.get("o", 0),
            high=message.get("h", 0),
            low=message.get("l", 0),
            close=message.get("c", 0),
            volume=message.get("v", 0),
            vwap=message.get("vw", None)
        )
        
        logger.debug(f"Inserted aggregate data for {ticker} at {timestamp}")
    
    async def _handle_trade(self, message: Dict[str, Any]):
        """Handle trade message.
        
        Args:
            message: Trade message data
        """
        # For real-time trade data, we might aggregate into minute bars
        # For now, just log it
        ticker = message.get("sym", "")
        logger.debug(f"Trade: {ticker} @ {message.get('p', 0)}")
    
    async def listen(self):
        """Listen for messages in a loop. Reconnects on disconnect so the scanner keeps running."""
        reconnect_backoff = 5.0
        max_backoff = 120.0
        
        while self.running:
            try:
                if not self.websocket:
                    await self.connect()
                if self.subscribed_tickers:
                    await self.subscribe(self.subscribed_tickers)
                reconnect_backoff = 5.0  # reset after successful connect
            except websockets.exceptions.ConnectionClosed as e:
                code = getattr(e, "code", "")
                reason = getattr(e, "reason", "") or "unknown"
                logger.warning(
                    f"WebSocket closed after subscribe (code={code}, reason={reason}). "
                    f"If code=1000, Polygon may not allow A.* on this plan; use a ticker list in config. Reconnecting in {int(reconnect_backoff)}s..."
                )
                self.websocket = None
                await asyncio.sleep(reconnect_backoff)
                reconnect_backoff = min(reconnect_backoff * 2, max_backoff)
                continue
            except Exception as e:
                logger.warning(f"Connect failed, retry in {int(reconnect_backoff)}s: {e}")
                await asyncio.sleep(reconnect_backoff)
                reconnect_backoff = min(reconnect_backoff * 2, max_backoff)
                continue

            try:
                while self.running and self.websocket:
                    try:
                        message = await asyncio.wait_for(
                            self.websocket.recv(),
                            timeout=30.0
                        )
                        data = json.loads(message)
                        if isinstance(data, list):
                            for msg in data:
                                await self._process_message(msg)
                        else:
                            await self._process_message(data)
                    except asyncio.TimeoutError:
                        if self.websocket:
                            await self.websocket.send(json.dumps({"action": "heartbeat"}))
                    except websockets.exceptions.ConnectionClosed as e:
                        code = getattr(e, "code", "")
                        reason = getattr(e, "reason", "") or "unknown"
                        logger.warning(
                            f"WebSocket closed (code={code}, reason={reason}), reconnecting in {int(reconnect_backoff)}s..."
                        )
                        self.websocket = None
                        await asyncio.sleep(reconnect_backoff)
                        reconnect_backoff = min(reconnect_backoff * 2, max_backoff)
                        break
                    except Exception as e:
                        logger.error(f"Error processing message: {e}")
                        continue
            except Exception as e:
                logger.error(f"Listen error: {e}")
                self.websocket = None
                await asyncio.sleep(reconnect_backoff)
                reconnect_backoff = min(reconnect_backoff * 2, max_backoff)

