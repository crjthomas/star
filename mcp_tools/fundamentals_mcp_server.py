"""MCP server for fundamentals and financial data tools."""
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta
import asyncio
import time
import httpx
import yfinance as yf
from utils.logger import get_logger
from utils.helpers import get_settings, get_env_var, normalize_ticker
from storage.sql_client import SQLClient

logger = get_logger(__name__)

# Rate limit and cache to avoid Yahoo Finance 429 (Too Many Requests)
YAHOO_CACHE_TTL_SEC = 300
YAHOO_MIN_INTERVAL_SEC = 2.0


def _sync_fetch_yahoo_info(ticker: str) -> Dict[str, Any]:
    """Sync fetch of Yahoo .info only (single quoteSummary-style request)."""
    try:
        return yf.Ticker(ticker).info or {}
    except Exception as e:
        return {"error": str(e)}


class FundamentalsMCPServer:
    """MCP server exposing fundamentals and financial data tools."""
    
    def __init__(self):
        self.settings = get_settings()
        self.sql_client = SQLClient()
        self._connected = False
        self._yahoo_cache: Dict[str, tuple[float, Dict[str, Any]]] = {}
        self._last_yahoo_time: float = 0
        self._yahoo_lock: Optional[asyncio.Lock] = None
    
    async def connect(self):
        """Initialize database connection."""
        if not self._connected:
            await self.sql_client.connect()
            self._connected = True
            logger.info("Fundamentals MCP Server connected")
    
    async def disconnect(self):
        """Close database connection."""
        if self._connected:
            await self.sql_client.disconnect()
            self._connected = False

    async def _rate_limited_yahoo_sync(self, sync_fn, *args, **kwargs) -> Any:
        """Run a sync Yahoo-related call with global rate limiting to avoid 429."""
        if self._yahoo_lock is None:
            self._yahoo_lock = asyncio.Lock()
        async with self._yahoo_lock:
            now = time.monotonic()
            elapsed = now - self._last_yahoo_time
            if elapsed < YAHOO_MIN_INTERVAL_SEC:
                await asyncio.sleep(YAHOO_MIN_INTERVAL_SEC - elapsed)
            self._last_yahoo_time = time.monotonic()
            return await asyncio.to_thread(sync_fn, *args, **kwargs)

    async def _get_yahoo_info(self, ticker: str) -> Dict[str, Any]:
        """Single shared Yahoo .info fetch per ticker with cache and rate limiting to avoid 429."""
        now = time.monotonic()
        if ticker in self._yahoo_cache:
            ts, info = self._yahoo_cache[ticker]
            if now - ts < YAHOO_CACHE_TTL_SEC and info and "error" not in info:
                return info
        info = await self._rate_limited_yahoo_sync(_sync_fetch_yahoo_info, ticker)
        self._yahoo_cache[ticker] = (time.monotonic(), info)
        return info
    
    def get_tools(self) -> List[Dict[str, Any]]:
        """Get available tools as MCP tool definitions.
        
        Returns:
            List of tool definitions
        """
        return [
            {
                "name": "get_fundamentals",
                "description": "Get fundamental financial data for a ticker (balance sheet, income statement metrics)",
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
            },
            {
                "name": "check_dilution_risk",
                "description": "Check for potential dilution risks (reverse splits, share offerings)",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "ticker": {
                            "type": "string",
                            "description": "Stock ticker symbol"
                        },
                        "days": {
                            "type": "integer",
                            "description": "Number of days to look back for dilution events (default: 90)",
                            "default": 90
                        }
                    },
                    "required": ["ticker"]
                }
            },
            {
                "name": "get_financial_stability",
                "description": "Assess financial stability metrics (debt ratios, cash flow, revenue)",
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
            },
            {
                "name": "get_short_interest",
                "description": "Get short interest data for a ticker",
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
            },
            {
                "name": "check_reverse_split",
                "description": "Check for upcoming or recent reverse stock splits",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "ticker": {
                            "type": "string",
                            "description": "Stock ticker symbol"
                        },
                        "days": {
                            "type": "integer",
                            "description": "Number of days to look back/forward (default: 90)",
                            "default": 90
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
            if name == "get_fundamentals":
                result = await self._get_fundamentals(ticker)
                return {"success": True, "data": result}
            
            elif name == "check_dilution_risk":
                days = arguments.get("days", 90)
                result = await self._check_dilution_risk(ticker, days)
                return {"success": True, "data": result}
            
            elif name == "get_financial_stability":
                result = await self._get_financial_stability(ticker)
                return {"success": True, "data": result}
            
            elif name == "get_short_interest":
                result = await self._get_short_interest(ticker)
                return {"success": True, "data": result}
            
            elif name == "check_reverse_split":
                days = arguments.get("days", 90)
                result = await self._check_reverse_split(ticker, days)
                return {"success": True, "data": result}
            
            else:
                return {"success": False, "error": f"Unknown tool: {name}"}
        
        except Exception as e:
            logger.error(f"Error calling tool {name}: {e}")
            return {"success": False, "error": str(e)}
    
    async def _get_fundamentals(self, ticker: str) -> Dict[str, Any]:
        """Get fundamental data from Yahoo Finance (uses shared cache to avoid 429)."""
        try:
            info = await self._get_yahoo_info(ticker)
            if info.get("error"):
                return {"ticker": ticker, "error": info["error"]}
            fundamentals = {
                "ticker": ticker,
                "market_cap": info.get("marketCap"),
                "enterprise_value": info.get("enterpriseValue"),
                "shares_outstanding": info.get("sharesOutstanding"),
                "float_shares": info.get("floatShares"),
                "total_revenue": info.get("totalRevenue"),
                "revenue_growth": info.get("revenueGrowth"),
                "net_income": info.get("netIncomeToCommon"),
                "total_debt": info.get("totalDebt"),
                "total_cash": info.get("totalCash"),
                "total_cash_per_share": info.get("totalCashPerShare"),
                "book_value": info.get("bookValue"),
                "debt_to_equity": info.get("debtToEquity"),
                "current_ratio": info.get("currentRatio"),
                "quick_ratio": info.get("quickRatio"),
                "return_on_equity": info.get("returnOnEquity"),
                "return_on_assets": info.get("returnOnAssets"),
                "profit_margin": info.get("profitMargins"),
                "operating_margin": info.get("operatingMargins"),
                "earnings_growth": info.get("earningsGrowth"),
                "peg_ratio": info.get("pegRatio"),
            }
            db_data = await self.sql_client.get_fundamentals(ticker)
            if db_data:
                fundamentals.update(db_data)
            return fundamentals
        except Exception as e:
            logger.error(f"Error fetching fundamentals for {ticker}: {e}")
            return {"ticker": ticker, "error": str(e)}
    
    async def _check_dilution_risk(self, ticker: str, days: int) -> Dict[str, Any]:
        """Check for dilution risks (uses shared Yahoo cache)."""
        try:
            info = await self._get_yahoo_info(ticker)
            if info.get("error"):
                return {"ticker": ticker, "error": info["error"]}
            shares_outstanding = info.get("sharesOutstanding")
            shares_short = info.get("sharesShort")
            float_shares = info.get("floatShares")
            dilution_risk = {
                "ticker": ticker,
                "shares_outstanding": shares_outstanding,
                "float_shares": float_shares,
                "shares_short": shares_short,
                "has_recent_dilution": False,
                "dilution_risk_score": 0.0,
                "risk_factors": []
            }
            if shares_outstanding and float_shares:
                float_ratio = float_shares / shares_outstanding
                if float_ratio < 0.7:
                    dilution_risk["risk_factors"].append("Low float ratio may indicate recent dilution")
                    dilution_risk["dilution_risk_score"] += 0.3
            return dilution_risk
        except Exception as e:
            logger.error(f"Error checking dilution risk for {ticker}: {e}")
            return {"ticker": ticker, "error": str(e)}
    
    async def _get_financial_stability(self, ticker: str) -> Dict[str, Any]:
        """Assess financial stability.
        
        Args:
            ticker: Ticker symbol
            
        Returns:
            Financial stability metrics
        """
        fundamentals = await self._get_fundamentals(ticker)
        
        if "error" in fundamentals:
            return fundamentals
        
        stability = {
            "ticker": ticker,
            "debt_to_equity": fundamentals.get("debt_to_equity"),
            "current_ratio": fundamentals.get("current_ratio"),
            "quick_ratio": fundamentals.get("quick_ratio"),
            "cash_position": fundamentals.get("total_cash"),
            "revenue_growth": fundamentals.get("revenue_growth"),
            "profit_margin": fundamentals.get("profit_margin"),
            "stability_score": 0.0,
            "risk_factors": [],
            "strengths": []
        }
        
        # Assess stability
        debt_to_equity = fundamentals.get("debt_to_equity")
        if debt_to_equity:
            if debt_to_equity < 1.0:
                stability["strengths"].append("Low debt-to-equity ratio")
                stability["stability_score"] += 0.3
            elif debt_to_equity > 2.0:
                stability["risk_factors"].append("High debt-to-equity ratio")
                stability["stability_score"] -= 0.3
        
        current_ratio = fundamentals.get("current_ratio")
        if current_ratio:
            if current_ratio > 1.5:
                stability["strengths"].append("Strong current ratio")
                stability["stability_score"] += 0.2
            elif current_ratio < 1.0:
                stability["risk_factors"].append("Current ratio below 1.0")
                stability["stability_score"] -= 0.3
        
        revenue_growth = fundamentals.get("revenue_growth")
        if revenue_growth and revenue_growth > 0.1:
            stability["strengths"].append("Positive revenue growth")
            stability["stability_score"] += 0.2
        
        profit_margin = fundamentals.get("profit_margin")
        if profit_margin and profit_margin > 0:
            stability["strengths"].append("Positive profit margin")
            stability["stability_score"] += 0.3
        
        stability["stability_score"] = max(0.0, min(1.0, stability["stability_score"]))
        
        return stability
    
    async def _get_short_interest(self, ticker: str) -> Dict[str, Any]:
        """Get short interest data (uses shared Yahoo cache)."""
        try:
            info = await self._get_yahoo_info(ticker)
            if info.get("error"):
                return {"ticker": ticker, "error": info["error"]}
            shares_outstanding = info.get("sharesOutstanding")
            shares_short = info.get("sharesShort")
            short_ratio = info.get("shortRatio")
            short_percent_float = info.get("shortPercentOfFloat")
            avg_volume = info.get("averageVolume")
            days_to_cover = None
            if shares_short and avg_volume and avg_volume > 0:
                days_to_cover = shares_short / avg_volume
            return {
                "ticker": ticker,
                "shares_short": shares_short,
                "shares_outstanding": shares_outstanding,
                "short_ratio": short_ratio,
                "short_percent_float": short_percent_float,
                "days_to_cover": days_to_cover,
                "average_volume": avg_volume
            }
        except Exception as e:
            logger.error(f"Error fetching short interest for {ticker}: {e}")
            return {"ticker": ticker, "error": str(e)}
    
    async def _check_reverse_split(self, ticker: str, days: int) -> Dict[str, Any]:
        """Check for reverse stock splits (rate-limited to avoid Yahoo 429)."""
        try:
            def _fetch_history():
                return yf.Ticker(ticker).history(period=f"{days}d")
            history = await self._rate_limited_yahoo_sync(_fetch_history)
            
            if history.empty:
                return {"ticker": ticker, "has_reverse_split": False}
            
            # Look for sudden price jumps that might indicate reverse split
            prices = history["Close"].tolist()
            
            has_rs = False
            rs_date = None
            
            for i in range(1, len(prices)):
                if prices[i] > 0 and prices[i-1] > 0:
                    change_ratio = prices[i] / prices[i-1]
                    # Reverse split would cause significant price increase
                    if change_ratio > 2.0:
                        has_rs = True
                        rs_date = history.index[i]
                        break
            
            return {
                "ticker": ticker,
                "has_reverse_split": has_rs,
                "reverse_split_date": rs_date.isoformat() if rs_date else None,
                "lookback_days": days
            }
        
        except Exception as e:
            logger.error(f"Error checking reverse split for {ticker}: {e}")
            return {"ticker": ticker, "error": str(e)}

