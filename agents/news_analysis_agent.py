"""News analysis agent using LangChain."""
from typing import Dict, Any, Optional, List
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI
from utils.logger import get_logger
from utils.helpers import get_settings, get_env_var, normalize_ticker
from mcp_tools.news_analysis_mcp_server import NewsAnalysisMCPServer
from processing.catalyst_detector import CatalystDetector

logger = get_logger(__name__)

class NewsAnalysisAgent:
    """LangChain agent for analyzing news and catalysts."""
    
    def __init__(self):
        self.settings = get_settings()
        self.llm = ChatOpenAI(
            model=self.settings["apis"]["openai"]["model"],
            temperature=0.3,
            api_key=get_env_var("OPENAI_API_KEY")
        )
        
        self.news_server = NewsAnalysisMCPServer()
        self.catalyst_detector = CatalystDetector()
        
        self.agent_executor: Optional[AgentExecutor] = None
        
    async def connect(self):
        """Initialize connections and create agent."""
        await self.news_server.connect()
        await self.catalyst_detector.connect()
        
        # Create tools
        tools = self._create_tools()
        
        # Create prompt
        prompt = ChatPromptTemplate.from_messages([
            ("system", """You are a financial news analysis agent. Your job is to:
1. Fetch and analyze news articles for specific stocks
2. Classify catalyst types (phase 3 clinical data, partnerships, buyouts, funding, short squeezes)
3. Analyze sentiment of news articles
4. Assess the strength and relevance of catalysts
5. Return a comprehensive analysis of news impact on stock price

Focus on identifying significant catalysts that could drive multi-day price movements."""),
            ("user", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ])
        
        # Create agent
        agent = create_tool_calling_agent(self.llm, tools, prompt)
        self.agent_executor = AgentExecutor(
            agent=agent,
            tools=tools,
            verbose=True,
            handle_parsing_errors=True
        )
        
        logger.info("News Analysis Agent connected")
    
    async def disconnect(self):
        """Close connections."""
        await self.news_server.disconnect()
        await self.catalyst_detector.disconnect()
    
    def _create_tools(self) -> List:
        """Create LangChain tools.
        
        Returns:
            List of LangChain tools
        """
        from langchain_core.tools import tool
        
        @tool
        async def fetch_news_for_ticker(ticker: str, hours: int = 24) -> str:
            """Fetch recent news articles for a ticker."""
            result = await self.news_server.call_tool(
                "fetch_news_for_ticker",
                {"ticker": ticker, "hours": hours}
            )
            return str(result)
        
        @tool
        async def analyze_news_sentiment(title: str, content: str = "") -> str:
            """Analyze sentiment of a news article."""
            result = await self.news_server.call_tool(
                "analyze_news_sentiment",
                {"title": title, "content": content}
            )
            return str(result)
        
        @tool
        async def classify_catalyst(title: str, content: str = "") -> str:
            """Classify catalyst type of a news article."""
            result = await self.news_server.call_tool(
                "classify_catalyst",
                {"title": title, "content": content}
            )
            return str(result)
        
        @tool
        async def analyze_catalyst_strength(ticker: str, hours: int = 24) -> str:
            """Analyze catalyst strength for a ticker based on recent news."""
            result = await self.catalyst_detector.analyze_catalyst_strength(ticker, hours)
            return str(result)
        
        return [
            fetch_news_for_ticker,
            analyze_news_sentiment,
            classify_catalyst,
            analyze_catalyst_strength
        ]
    
    async def analyze_news(self, ticker: str, hours: int = 24) -> Dict[str, Any]:
        """Analyze news for a ticker.
        
        Args:
            ticker: Ticker symbol
            hours: Hours to look back
            
        Returns:
            News analysis result
        """
        if not self.agent_executor:
            await self.connect()
        
        ticker = normalize_ticker(ticker)
        
        prompt = f"""Analyze news for {ticker}:
1. Fetch recent news articles (last {hours} hours)
2. Classify catalyst types (phase 3, partnerships, buyouts, etc.)
3. Analyze sentiment of each article
4. Assess overall catalyst strength
5. Provide a comprehensive analysis of how news could impact the stock

Focus on identifying significant catalysts that could drive multi-day price movements."""
        
        try:
            result = await self.agent_executor.ainvoke({
                "input": prompt
            })
            
            return {
                "ticker": ticker,
                "analysis": result.get("output", ""),
                "success": True
            }
        
        except Exception as e:
            logger.error(f"Error in news analysis for {ticker}: {e}")
            return {
                "ticker": ticker,
                "analysis": str(e),
                "success": False,
                "error": str(e)
            }

