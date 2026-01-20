"""MCP server for news analysis tools."""
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta
import httpx
import openai
from utils.logger import get_logger
from utils.helpers import get_settings, get_env_var, normalize_ticker
from storage.sql_client import SQLClient
from storage.vector_db_client import VectorDBClient

logger = get_logger(__name__)

class NewsAnalysisMCPServer:
    """MCP server exposing news analysis tools."""
    
    def __init__(self):
        self.settings = get_settings()
        self.sql_client = SQLClient()
        self.vector_client = VectorDBClient()
        self._connected = False
        
        # Setup OpenAI client
        openai.api_key = get_env_var("OPENAI_API_KEY")
        self.openai_client = openai.AsyncOpenAI()
    
    async def connect(self):
        """Initialize database connections."""
        if not self._connected:
            await self.sql_client.connect()
            await self.vector_client.connect()
            self._connected = True
            logger.info("News Analysis MCP Server connected")
    
    async def disconnect(self):
        """Close database connections."""
        if self._connected:
            await self.sql_client.disconnect()
            # VectorDB doesn't have explicit disconnect
            self._connected = False
    
    def get_tools(self) -> List[Dict[str, Any]]:
        """Get available tools as MCP tool definitions.
        
        Returns:
            List of tool definitions
        """
        return [
            {
                "name": "fetch_news_for_ticker",
                "description": "Fetch recent news articles for a specific ticker from multiple sources",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "ticker": {
                            "type": "string",
                            "description": "Stock ticker symbol"
                        },
                        "hours": {
                            "type": "integer",
                            "description": "Number of hours to look back (default: 24)",
                            "default": 24
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of articles to return (default: 20)",
                            "default": 20
                        }
                    },
                    "required": ["ticker"]
                }
            },
            {
                "name": "analyze_news_sentiment",
                "description": "Analyze sentiment of news articles using LLM",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "News article title"
                        },
                        "content": {
                            "type": "string",
                            "description": "News article content/text"
                        }
                    },
                    "required": ["title"]
                }
            },
            {
                "name": "classify_catalyst",
                "description": "Classify news article catalyst type (phase 3, partnership, buyout, etc.)",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "News article title"
                        },
                        "content": {
                            "type": "string",
                            "description": "News article content/text"
                        }
                    },
                    "required": ["title"]
                }
            },
            {
                "name": "search_similar_news",
                "description": "Search for similar news articles using vector embeddings",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query_text": {
                            "type": "string",
                            "description": "Query text to search for"
                        },
                        "ticker": {
                            "type": "string",
                            "description": "Optional ticker to filter by"
                        },
                        "n_results": {
                            "type": "integer",
                            "description": "Number of results to return (default: 10)",
                            "default": 10
                        }
                    },
                    "required": ["query_text"]
                }
            },
            {
                "name": "get_recent_news_for_ticker",
                "description": "Get recent news articles for a ticker from database",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "ticker": {
                            "type": "string",
                            "description": "Stock ticker symbol"
                        },
                        "hours": {
                            "type": "integer",
                            "description": "Number of hours to look back (default: 24)",
                            "default": 24
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
        
        try:
            if name == "fetch_news_for_ticker":
                ticker = normalize_ticker(arguments["ticker"])
                hours = arguments.get("hours", 24)
                limit = arguments.get("limit", 20)
                result = await self._fetch_news(ticker, hours, limit)
                return {"success": True, "data": result}
            
            elif name == "analyze_news_sentiment":
                title = arguments["title"]
                content = arguments.get("content", "")
                result = await self._analyze_sentiment(title, content)
                return {"success": True, "data": result}
            
            elif name == "classify_catalyst":
                title = arguments["title"]
                content = arguments.get("content", "")
                result = await self._classify_catalyst(title, content)
                return {"success": True, "data": result}
            
            elif name == "search_similar_news":
                query_text = arguments["query_text"]
                ticker = arguments.get("ticker")
                n_results = arguments.get("n_results", 10)
                result = await self._search_similar(query_text, ticker, n_results)
                return {"success": True, "data": result}
            
            elif name == "get_recent_news_for_ticker":
                ticker = normalize_ticker(arguments["ticker"])
                hours = arguments.get("hours", 24)
                result = await self._get_recent_news(ticker, hours)
                return {"success": True, "data": result}
            
            else:
                return {"success": False, "error": f"Unknown tool: {name}"}
        
        except Exception as e:
            logger.error(f"Error calling tool {name}: {e}")
            return {"success": False, "error": str(e)}
    
    async def _fetch_news(self, ticker: str, hours: int, limit: int) -> List[Dict[str, Any]]:
        """Fetch news from multiple sources.
        
        Args:
            ticker: Ticker symbol
            hours: Hours to look back
            limit: Maximum number of articles
            
        Returns:
            List of news articles
        """
        news_articles = []
        since = datetime.now() - timedelta(hours=hours)
        
        # Fetch from NewsAPI
        newsapi_key = get_env_var("NEWSAPI_KEY", None)
        if newsapi_key:
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        f"https://newsapi.org/v2/everything",
                        params={
                            "q": ticker,
                            "sortBy": "publishedAt",
                            "from": since.isoformat(),
                            "pageSize": min(limit, 100),
                            "apiKey": newsapi_key
                        },
                        timeout=10.0
                    )
                    if response.status_code == 200:
                        data = response.json()
                        for article in data.get("articles", [])[:limit]:
                            news_articles.append({
                                "title": article.get("title", ""),
                                "content": article.get("description", ""),
                                "source": article.get("source", {}).get("name", ""),
                                "url": article.get("url", ""),
                                "published_at": article.get("publishedAt", "")
                            })
            except Exception as e:
                logger.warning(f"Error fetching from NewsAPI: {e}")
        
        return news_articles[:limit]
    
    async def _analyze_sentiment(self, title: str, content: str = "") -> Dict[str, Any]:
        """Analyze sentiment using OpenAI.
        
        Args:
            title: Article title
            content: Article content
            
        Returns:
            Sentiment analysis result
        """
        text = f"{title}\n\n{content}" if content else title
        
        prompt = f"""Analyze the sentiment of this financial news article. 
Return a JSON object with:
- sentiment: "positive", "negative", or "neutral"
- score: a number between -1.0 (very negative) and 1.0 (very positive)
- confidence: a number between 0.0 and 1.0

Article:
{text}

Return only valid JSON."""
        
        try:
            response = await self.openai_client.chat.completions.create(
                model=self.settings["apis"]["openai"]["model"],
                messages=[
                    {"role": "system", "content": "You are a financial sentiment analyzer. Always return valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=self.settings["apis"]["openai"]["temperature"],
                max_tokens=200
            )
            
            import json
            result = json.loads(response.choices[0].message.content)
            return result
        
        except Exception as e:
            logger.error(f"Error analyzing sentiment: {e}")
            return {"sentiment": "neutral", "score": 0.0, "confidence": 0.0}
    
    async def _classify_catalyst(self, title: str, content: str = "") -> Dict[str, Any]:
        """Classify catalyst type using OpenAI.
        
        Args:
            title: Article title
            content: Article content
            
        Returns:
            Catalyst classification result
        """
        text = f"{title}\n\n{content}" if content else title
        
        catalyst_types = [
            "biotech_phase3", "partnership", "buyout_merger", 
            "funding", "short_squeeze", "other"
        ]
        
        prompt = f"""Classify this financial news article into one of these catalyst types:
- biotech_phase3: Phase 3 clinical trial results, FDA approvals, biotech breakthroughs
- partnership: Strategic partnerships, collaborations, joint ventures
- buyout_merger: Acquisitions, mergers, takeovers, buyouts
- funding: Funding rounds, capital raises, investments
- short_squeeze: Short squeeze indicators, short interest news
- other: Any other significant news

Return a JSON object with:
- catalyst_type: one of the types above
- confidence: a number between 0.0 and 1.0
- relevance: "high", "medium", or "low"

Article:
{text}

Return only valid JSON."""
        
        try:
            response = await self.openai_client.chat.completions.create(
                model=self.settings["apis"]["openai"]["model"],
                messages=[
                    {"role": "system", "content": "You are a financial news classifier. Always return valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=self.settings["apis"]["openai"]["temperature"],
                max_tokens=200
            )
            
            import json
            result = json.loads(response.choices[0].message.content)
            return result
        
        except Exception as e:
            logger.error(f"Error classifying catalyst: {e}")
            return {"catalyst_type": "other", "confidence": 0.0, "relevance": "low"}
    
    async def _search_similar(self, query_text: str, ticker: Optional[str], n_results: int) -> Dict[str, Any]:
        """Search for similar news using vector embeddings.
        
        Args:
            query_text: Query text
            ticker: Optional ticker filter
            n_results: Number of results
            
        Returns:
            Search results
        """
        # For now, return empty results - vector search would require embeddings
        # This would need to be implemented with actual embedding generation
        return {"results": [], "count": 0}
    
    async def _get_recent_news(self, ticker: str, hours: int) -> List[Dict[str, Any]]:
        """Get recent news from database.
        
        Args:
            ticker: Ticker symbol
            hours: Hours to look back
            
        Returns:
            List of news articles
        """
        since = datetime.now() - timedelta(hours=hours)
        
        async with self.sql_client.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM news
                WHERE ticker = $1 AND published_at >= $2
                ORDER BY published_at DESC;
            """, ticker, since)
            
            return [dict(row) for row in rows]

