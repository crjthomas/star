"""Catalyst detector for news classification."""
from typing import Dict, Any, List, Optional
from datetime import datetime
from utils.logger import get_logger
from utils.helpers import get_settings, normalize_ticker
from mcp_tools.news_analysis_mcp_server import NewsAnalysisMCPServer

logger = get_logger(__name__)

class CatalystDetector:
    """Detects and classifies news catalysts."""
    
    def __init__(self):
        self.settings = get_settings()
        self.news_server = NewsAnalysisMCPServer()
        self.catalyst_keywords = self.settings.get("news_analysis", {}).get("catalyst_keywords", {})
        
    async def connect(self):
        """Initialize connections."""
        await self.news_server.connect()
        logger.info("Catalyst Detector connected")
    
    async def disconnect(self):
        """Close connections."""
        await self.news_server.disconnect()
    
    async def classify_news_article(
        self,
        title: str,
        content: str = ""
    ) -> Dict[str, Any]:
        """Classify a news article's catalyst type.
        
        Args:
            title: Article title
            content: Article content
            
        Returns:
            Catalyst classification result
        """
        result = await self.news_server.call_tool(
            "classify_catalyst",
            {"title": title, "content": content}
        )
        
        if result.get("success"):
            return result.get("data", {})
        
        return {
            "catalyst_type": "other",
            "confidence": 0.0,
            "relevance": "low"
        }
    
    async def analyze_catalyst_strength(
        self,
        ticker: str,
        hours: int = 24
    ) -> Dict[str, Any]:
        """Analyze catalyst strength for a ticker based on recent news.
        
        Args:
            ticker: Ticker symbol
            hours: Hours to look back
            
        Returns:
            Catalyst strength analysis
        """
        ticker = normalize_ticker(ticker)
        
        # Get recent news
        news_result = await self.news_server.call_tool(
            "get_recent_news_for_ticker",
            {"ticker": ticker, "hours": hours}
        )
        
        if not news_result.get("success"):
            return {
                "ticker": ticker,
                "catalyst_score": 0.0,
                "catalysts": [],
                "strongest_catalyst": None
            }
        
        news_articles = news_result.get("data", [])
        
        catalysts = []
        catalyst_weights = {
            "biotech_phase3": 1.0,
            "buyout_merger": 0.95,
            "partnership": 0.80,
            "funding": 0.70,
            "short_squeeze": 0.85,
            "other": 0.50
        }
        
        total_score = 0.0
        strongest = None
        max_weight = 0.0
        
        for article in news_articles:
            catalyst_type = article.get("catalyst_type", "other")
            sentiment_score = article.get("sentiment_score", 0.0)
            confidence = 1.0  # Could be from classification
            
            weight = catalyst_weights.get(catalyst_type, 0.5)
            score = weight * abs(sentiment_score) * confidence
            
            catalysts.append({
                "catalyst_type": catalyst_type,
                "title": article.get("title", ""),
                "sentiment_score": sentiment_score,
                "weight": weight,
                "score": score,
                "published_at": article.get("published_at")
            })
            
            total_score += score
            
            if score > max_weight:
                max_weight = score
                strongest = catalyst_type
        
        # Normalize score (max possible is sum of weights * 1.0 sentiment)
        max_possible = sum(catalyst_weights.values())
        normalized_score = (total_score / max_possible) * 100 if max_possible > 0 else 0
        
        return {
            "ticker": ticker,
            "catalyst_score": normalized_score,
            "catalysts": catalysts,
            "strongest_catalyst": strongest,
            "total_articles": len(news_articles)
        }
    
    def check_keyword_match(self, text: str, catalyst_type: str) -> bool:
        """Check if text matches keywords for a catalyst type.
        
        Args:
            text: Text to check
            catalyst_type: Catalyst type to match
            
        Returns:
            True if keywords match
        """
        text_lower = text.lower()
        keywords = self.catalyst_keywords.get(catalyst_type, [])
        
        for keyword in keywords:
            if keyword.lower() in text_lower:
                return True
        
        return False

