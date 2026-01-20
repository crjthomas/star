"""News fetcher for polling news APIs."""
import asyncio
import httpx
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from utils.logger import get_logger
from utils.helpers import get_settings, get_env_var, normalize_ticker
from storage.sql_client import SQLClient
from storage.vector_db_client import VectorDBClient
from mcp_tools.news_analysis_mcp_server import NewsAnalysisMCPServer

logger = get_logger(__name__)

class NewsFetcher:
    """Fetches and processes news from multiple sources."""
    
    def __init__(self):
        self.settings = get_settings()
        self.sql_client = SQLClient()
        self.vector_client = VectorDBClient()
        self.news_server = NewsAnalysisMCPServer()
        self.running = False
        self.poll_interval = self.settings.get("news_analysis", {}).get("poll_interval_minutes", 10)
        
    async def connect(self):
        """Initialize database connections."""
        await self.sql_client.connect()
        await self.vector_client.connect()
        await self.news_server.connect()
        logger.info("News Fetcher connected")
    
    async def disconnect(self):
        """Close database connections."""
        await self.sql_client.disconnect()
        await self.news_server.disconnect()
        logger.info("News Fetcher disconnected")
    
    async def fetch_news_for_ticker(self, ticker: str, hours: int = 24) -> List[Dict[str, Any]]:
        """Fetch news for a specific ticker.
        
        Args:
            ticker: Ticker symbol
            hours: Hours to look back
            
        Returns:
            List of news articles
        """
        result = await self.news_server.call_tool(
            "fetch_news_for_ticker",
            {"ticker": ticker, "hours": hours}
        )
        
        if result.get("success"):
            return result.get("data", [])
        return []
    
    async def process_and_store_news(
        self,
        ticker: str,
        news_articles: List[Dict[str, Any]]
    ):
        """Process news articles (sentiment, catalyst classification) and store them.
        
        Args:
            ticker: Ticker symbol
            news_articles: List of news articles
        """
        for article in news_articles:
            try:
                title = article.get("title", "")
                content = article.get("content", "") or article.get("description", "")
                source = article.get("source", "")
                url = article.get("url", "")
                published_at_str = article.get("published_at", "")
                
                # Parse published_at
                published_at = None
                if published_at_str:
                    try:
                        published_at = datetime.fromisoformat(
                            published_at_str.replace("Z", "+00:00")
                        )
                    except:
                        published_at = datetime.now()
                else:
                    published_at = datetime.now()
                
                # Skip if already exists
                async with self.sql_client.pool.acquire() as conn:
                    existing = await conn.fetchrow("""
                        SELECT id FROM news
                        WHERE ticker = $1 AND url = $2 AND published_at = $3;
                    """, normalize_ticker(ticker), url, published_at)
                    
                    if existing:
                        continue
                
                # Analyze sentiment
                sentiment_result = await self.news_server.call_tool(
                    "analyze_news_sentiment",
                    {"title": title, "content": content}
                )
                
                sentiment_data = sentiment_result.get("data", {})
                sentiment_score = sentiment_data.get("score", 0.0)
                
                # Classify catalyst
                catalyst_result = await self.news_server.call_tool(
                    "classify_catalyst",
                    {"title": title, "content": content}
                )
                
                catalyst_data = catalyst_result.get("data", {})
                catalyst_type = catalyst_data.get("catalyst_type", "other")
                
                # Store in database
                async with self.sql_client.pool.acquire() as conn:
                    await conn.execute("""
                        INSERT INTO news 
                        (ticker, title, content, source, url, published_at, 
                         sentiment_score, catalyst_type)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                        ON CONFLICT DO NOTHING;
                    """, 
                        normalize_ticker(ticker),
                        title,
                        content,
                        source,
                        url,
                        published_at,
                        float(sentiment_score),
                        catalyst_type
                    )
                
                logger.info(f"Stored news: {ticker} - {title[:50]}...")
            
            except Exception as e:
                logger.error(f"Error processing news article: {e}")
    
    async def fetch_all_tickers(self, tickers: List[str], hours: int = 24):
        """Fetch news for multiple tickers.
        
        Args:
            tickers: List of ticker symbols
            hours: Hours to look back
        """
        tasks = []
        for ticker in tickers:
            task = self.fetch_and_process_ticker(ticker, hours)
            tasks.append(task)
        
        # Process in batches to avoid rate limits
        batch_size = 5
        for i in range(0, len(tasks), batch_size):
            batch = tasks[i:i + batch_size]
            await asyncio.gather(*batch, return_exceptions=True)
            
            # Rate limiting delay between batches
            if i + batch_size < len(tasks):
                await asyncio.sleep(2)
    
    async def fetch_and_process_ticker(self, ticker: str, hours: int = 24):
        """Fetch and process news for a single ticker.
        
        Args:
            ticker: Ticker symbol
            hours: Hours to look back
        """
        try:
            news_articles = await self.fetch_news_for_ticker(ticker, hours)
            if news_articles:
                await self.process_and_store_news(ticker, news_articles)
        except Exception as e:
            logger.error(f"Error fetching news for {ticker}: {e}")
    
    async def start_polling(self, tickers: List[str]):
        """Start polling news for tickers at regular intervals.
        
        Args:
            tickers: List of ticker symbols to monitor
        """
        self.running = True
        logger.info(f"Starting news polling for {len(tickers)} tickers (interval: {self.poll_interval} min)")
        
        while self.running:
            try:
                await self.fetch_all_tickers(tickers)
                
                # Wait for next poll
                await asyncio.sleep(self.poll_interval * 60)
            
            except Exception as e:
                logger.error(f"Error in polling loop: {e}")
                await asyncio.sleep(60)  # Wait 1 minute before retry
    
    def stop_polling(self):
        """Stop polling."""
        self.running = False
        logger.info("Stopped news polling")

