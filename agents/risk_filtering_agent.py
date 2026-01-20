"""Risk filtering agent using LangChain."""
from typing import Dict, Any, Optional, List
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI
from utils.logger import get_logger
from utils.helpers import get_settings, get_env_var, normalize_ticker
from mcp_tools.fundamentals_mcp_server import FundamentalsMCPServer
from scoring.fundamental_analyzer import FundamentalAnalyzer
from scoring.dilution_checker import DilutionChecker

logger = get_logger(__name__)

class RiskFilteringAgent:
    """LangChain agent for filtering based on risk factors."""
    
    def __init__(self):
        self.settings = get_settings()
        self.llm = ChatOpenAI(
            model=self.settings["apis"]["openai"]["model"],
            temperature=0.3,
            api_key=get_env_var("OPENAI_API_KEY")
        )
        
        self.fundamentals_server = FundamentalsMCPServer()
        self.fundamental_analyzer = FundamentalAnalyzer()
        self.dilution_checker = DilutionChecker()
        
        self.agent_executor: Optional[AgentExecutor] = None
        
    async def connect(self):
        """Initialize connections and create agent."""
        await self.fundamentals_server.connect()
        await self.fundamental_analyzer.connect()
        await self.dilution_checker.connect()
        
        # Create tools
        tools = self._create_tools()
        
        # Create prompt
        prompt = ChatPromptTemplate.from_messages([
            ("system", """You are a risk filtering agent. Your job is to:
1. Analyze fundamental financial metrics
2. Check for dilution risks (reverse splits, share offerings)
3. Assess financial stability (debt ratios, cash flow, revenue)
4. Filter out stocks with high risk factors
5. Return a comprehensive risk assessment

Focus on identifying stocks that are financially stable and have low dilution risk."""),
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
        
        logger.info("Risk Filtering Agent connected")
    
    async def disconnect(self):
        """Close connections."""
        await self.fundamentals_server.disconnect()
        await self.fundamental_analyzer.disconnect()
        await self.dilution_checker.disconnect()
    
    def _create_tools(self) -> List:
        """Create LangChain tools.
        
        Returns:
            List of LangChain tools
        """
        from langchain_core.tools import tool
        
        @tool
        async def get_fundamentals(ticker: str) -> str:
            """Get fundamental financial data for a ticker."""
            result = await self.fundamentals_server.call_tool(
                "get_fundamentals",
                {"ticker": ticker}
            )
            return str(result)
        
        @tool
        async def check_dilution_risk(ticker: str, days: int = 90) -> str:
            """Check for dilution risks."""
            result = await self.fundamentals_server.call_tool(
                "check_dilution_risk",
                {"ticker": ticker, "days": days}
            )
            return str(result)
        
        @tool
        async def get_financial_stability(ticker: str) -> str:
            """Assess financial stability metrics."""
            result = await self.fundamentals_server.call_tool(
                "get_financial_stability",
                {"ticker": ticker}
            )
            return str(result)
        
        @tool
        async def check_reverse_split(ticker: str, days: int = 90) -> str:
            """Check for reverse stock splits."""
            result = await self.fundamentals_server.call_tool(
                "check_reverse_split",
                {"ticker": ticker, "days": days}
            )
            return str(result)
        
        @tool
        async def analyze_fundamentals(ticker: str) -> str:
            """Analyze fundamental metrics."""
            result = await self.fundamental_analyzer.analyze_fundamentals(ticker)
            return str(result)
        
        @tool
        async def check_dilution(ticker: str, days: int = 90) -> str:
            """Check for dilution risks and reverse splits."""
            result = await self.dilution_checker.check_dilution_risk(ticker, days)
            return str(result)
        
        return [
            get_fundamentals,
            check_dilution_risk,
            get_financial_stability,
            check_reverse_split,
            analyze_fundamentals,
            check_dilution
        ]
    
    async def filter_risks(self, ticker: str) -> Dict[str, Any]:
        """Filter risks for a ticker.
        
        Args:
            ticker: Ticker symbol
            
        Returns:
            Risk filtering analysis
        """
        if not self.agent_executor:
            await self.connect()
        
        ticker = normalize_ticker(ticker)
        
        prompt = f"""Assess risk factors for {ticker}:
1. Analyze fundamental financial metrics (debt, cash flow, revenue)
2. Check for dilution risks (reverse splits, share offerings)
3. Assess financial stability
4. Determine if the stock passes risk filters
5. Provide a comprehensive risk assessment

Focus on identifying stocks with low dilution risk and good financial stability."""
        
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
            logger.error(f"Error in risk filtering for {ticker}: {e}")
            return {
                "ticker": ticker,
                "analysis": str(e),
                "success": False,
                "error": str(e)
            }

