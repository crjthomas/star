"""Signal detection agent using LangChain."""
from typing import Dict, Any, Optional, List
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI
from utils.logger import get_logger
from utils.helpers import get_settings, get_env_var, normalize_ticker
from mcp_tools.stock_data_mcp_server import StockDataMCPServer
from processing.volume_analyzer import VolumeAnalyzer
from processing.technical_indicators import TechnicalIndicators

logger = get_logger(__name__)

class SignalDetectionAgent:
    """LangChain agent for detecting trading signals."""
    
    def __init__(self):
        self.settings = get_settings()
        self.llm = ChatOpenAI(
            model=self.settings["apis"]["openai"]["model"],
            temperature=0.3,
            api_key=get_env_var("OPENAI_API_KEY")
        )
        
        self.stock_data_server = StockDataMCPServer()
        self.volume_analyzer = VolumeAnalyzer()
        self.technical_indicators = TechnicalIndicators()
        
        self.agent_executor: Optional[AgentExecutor] = None
        
    async def connect(self):
        """Initialize connections and create agent."""
        await self.stock_data_server.connect()
        await self.volume_analyzer.connect()
        await self.technical_indicators.connect()
        
        # Create tools from MCP server
        tools = self._create_tools()
        
        # Create prompt
        prompt = ChatPromptTemplate.from_messages([
            ("system", """You are a stock signal detection agent. Your job is to:
1. Analyze volume patterns to detect volume spikes
2. Calculate technical indicators (RSI, MACD, moving averages)
3. Detect price breakouts and trend reversals
4. Identify multi-day upward momentum patterns
5. Return a comprehensive analysis of trading signals

Always provide detailed reasoning for your analysis."""),
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
        
        logger.info("Signal Detection Agent connected")
    
    async def disconnect(self):
        """Close connections."""
        await self.stock_data_server.disconnect()
        await self.volume_analyzer.disconnect()
        await self.technical_indicators.disconnect()
    
    def _create_tools(self) -> List:
        """Create LangChain tools from MCP server tools.
        
        Returns:
            List of LangChain tools
        """
        from langchain_core.tools import tool
        
        # Get MCP server tools
        mcp_tools = self.stock_data_server.get_tools()
        
        @tool
        async def get_stock_price(ticker: str) -> str:
            """Get current stock price data."""
            result = await self.stock_data_server.call_tool(
                "get_stock_price",
                {"ticker": ticker}
            )
            return str(result)
        
        @tool
        async def get_volume_statistics(ticker: str, days: int = 20) -> str:
            """Get volume statistics for a ticker."""
            result = await self.stock_data_server.call_tool(
                "get_volume_statistics",
                {"ticker": ticker, "days": days}
            )
            return str(result)
        
        @tool
        async def detect_volume_spike(ticker: str, current_volume: int) -> str:
            """Detect volume spike for a ticker."""
            result = await self.volume_analyzer.detect_volume_spike(
                ticker,
                current_volume
            )
            return str(result)
        
        @tool
        async def calculate_technical_indicators(ticker: str, days: int = 50) -> str:
            """Calculate technical indicators for a ticker."""
            result = await self.technical_indicators.calculate_all_indicators(ticker, days)
            return str(result)
        
        @tool
        async def detect_breakout(ticker: str) -> str:
            """Detect price breakout for a ticker."""
            result = await self.technical_indicators.detect_breakout(ticker)
            return str(result)
        
        return [
            get_stock_price,
            get_volume_statistics,
            detect_volume_spike,
            calculate_technical_indicators,
            detect_breakout
        ]
    
    async def detect_signals(self, ticker: str) -> Dict[str, Any]:
        """Detect trading signals for a ticker.
        
        Args:
            ticker: Ticker symbol
            
        Returns:
            Signal detection analysis
        """
        if not self.agent_executor:
            await self.connect()
        
        ticker = normalize_ticker(ticker)
        
        prompt = f"""Analyze {ticker} for trading signals:
1. Check for volume spikes (>2.5x average)
2. Calculate technical indicators (RSI, MACD, SMAs)
3. Detect price breakouts
4. Assess multi-day momentum
5. Provide a comprehensive signal analysis

Focus on identifying swing play opportunities (multi-day moves)."""
        
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
            logger.error(f"Error in signal detection for {ticker}: {e}")
            return {
                "ticker": ticker,
                "analysis": str(e),
                "success": False,
                "error": str(e)
            }

