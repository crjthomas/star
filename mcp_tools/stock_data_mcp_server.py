"""MCP server for stock data tools."""
from typing import Any, Dict, List, Optional
from datetime import datetime
from utils.logger import get_logger
from utils.helpers import get_settings, normalize_ticker
from storage.timeseries_client import TimeseriesClient
import yfinance as yf

logger = get_logger(__name__)

class StockDataMCPServer:
    """MCP server exposing stock data tools."""
    
    def __init__(self):
        self.settings = get_settings()
        self.ts_client = TimeseriesClient()
        self._connected = False
    
    async def connect(self):
        """Initialize database connection."""
        if not self._connected:
            await self.ts_client.connect()
            self._connected = True
            logger.info("Stock Data MCP Server connected")
    
    async def disconnect(self):
        """Close database connection."""
        if self._connected:
            await self.ts_client.disconnect()
            self._connected = False
    
    def get_tools(self) -> List[Dict[str, Any]]:
        """Get available tools as MCP tool definitions.
        
        Returns:
            List of tool definitions
        """
        return [
            {
                "name": "get_stock_price",
                "description": "Get current/latest stock price data for a ticker",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "ticker": {
                            "type": "string",
                            "description": "Stock ticker symbol (e.g., 'AAPL')"
                        }
                    },
                    "required": ["ticker"]
                }
            },
            {
                "name": "get_volume_statistics",
                "description": "Get volume statistics (average, max, min) for a ticker over specified days",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "ticker": {
                            "type": "string",
                            "description": "Stock ticker symbol"
                        },
                        "days": {
                            "type": "integer",
                            "description": "Number of days to look back (default: 20)",
                            "default": 20
                        }
                    },
                    "required": ["ticker"]
                }
            },
            {
                "name": "get_price_history",
                "description": "Get historical price data for a ticker within a date range",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "ticker": {
                            "type": "string",
                            "description": "Stock ticker symbol"
                        },
                        "start_date": {
                            "type": "string",
                            "description": "Start date (YYYY-MM-DD)",
                            "format": "date"
                        },
                        "end_date": {
                            "type": "string",
                            "description": "End date (YYYY-MM-DD)",
                            "format": "date"
                        }
                    },
                    "required": ["ticker", "start_date", "end_date"]
                }
            },
            {
                "name": "get_price_range",
                "description": "Get price range (high, low, close) for a ticker over specified days",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "ticker": {
                            "type": "string",
                            "description": "Stock ticker symbol"
                        },
                        "days": {
                            "type": "integer",
                            "description": "Number of days to look back (default: 20)",
                            "default": 20
                        }
                    },
                    "required": ["ticker"]
                }
            },
            {
                "name": "get_multi_day_trend",
                "description": "Get multi-day price trend (direction, change percentage) for a ticker",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "ticker": {
                            "type": "string",
                            "description": "Stock ticker symbol"
                        },
                        "days": {
                            "type": "integer",
                            "description": "Number of days to analyze (default: 5)",
                            "default": 5
                        }
                    },
                    "required": ["ticker"]
                }
            },
            {
                "name": "get_real_time_quote",
                "description": "Get real-time stock quote from Yahoo Finance",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "ticker": {
                            "type": "string",
                            "description": "Stock ticker symbol"
                        }
                    },
                    "required": ["ticker"]
                }
            }
        ]
    
    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Call a tool by name with arguments.
        
        Args:
            name: Tool name
            arguments: Tool arguments
            
        Returns:
            Tool result
        """
        if not self._connected:
            await self.connect()
        
        ticker = normalize_ticker(arguments.get("ticker", ""))
        
        try:
            if name == "get_stock_price":
                result = await self.ts_client.get_current_price(ticker)
                return {"success": True, "data": result}
            
            elif name == "get_volume_statistics":
                days = arguments.get("days", 20)
                result = await self.ts_client.get_volume_statistics(ticker, days)
                return {"success": True, "data": result}
            
            elif name == "get_price_history":
                start_date = datetime.fromisoformat(arguments["start_date"])
                end_date = datetime.fromisoformat(arguments["end_date"])
                result = await self.ts_client.get_price_history(ticker, start_date, end_date)
                return {"success": True, "data": result}
            
            elif name == "get_price_range":
                days = arguments.get("days", 20)
                result = await self.ts_client.get_price_range(ticker, days)
                return {"success": True, "data": result}
            
            elif name == "get_multi_day_trend":
                days = arguments.get("days", 5)
                result = await self.ts_client.get_multi_day_trend(ticker, days)
                return {"success": True, "data": result}
            
            elif name == "get_real_time_quote":
                result = await self._get_yahoo_quote(ticker)
                return {"success": True, "data": result}
            
            else:
                return {"success": False, "error": f"Unknown tool: {name}"}
        
        except Exception as e:
            logger.error(f"Error calling tool {name}: {e}")
            return {"success": False, "error": str(e)}
    
    async def _get_yahoo_quote(self, ticker: str) -> Dict[str, Any]:
        """Get real-time quote from Yahoo Finance.
        
        Args:
            ticker: Ticker symbol
            
        Returns:
            Quote data
        """
        try:
            stock = yf.Ticker(ticker)
            info = stock.info
            history = stock.history(period="1d", interval="1m")
            
            if history.empty:
                return {"error": "No data available"}
            
            latest = history.iloc[-1]
            
            return {
                "ticker": ticker,
                "current_price": float(latest["Close"]),
                "open": float(latest["Open"]),
                "high": float(latest["High"]),
                "low": float(latest["Low"]),
                "volume": int(latest["Volume"]),
                "market_cap": info.get("marketCap"),
                "avg_volume": info.get("averageVolume"),
                "previous_close": info.get("previousClose"),
                "timestamp": latest.name.isoformat() if hasattr(latest.name, 'isoformat') else str(latest.name)
            }
        except Exception as e:
            logger.error(f"Error fetching Yahoo Finance quote for {ticker}: {e}")
            return {"error": str(e)}

