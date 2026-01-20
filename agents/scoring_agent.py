"""Scoring agent that combines all signals using LangChain."""
from typing import Dict, Any, Optional, List
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI
from utils.logger import get_logger
from utils.helpers import get_settings, get_env_var, normalize_ticker
from scoring.swing_score_calculator import SwingScoreCalculator
from agents.signal_detection_agent import SignalDetectionAgent
from agents.news_analysis_agent import NewsAnalysisAgent
from agents.risk_filtering_agent import RiskFilteringAgent

logger = get_logger(__name__)

class ScoringAgent:
    """LangChain agent that orchestrates scoring by combining all signals."""
    
    def __init__(self):
        self.settings = get_settings()
        self.llm = ChatOpenAI(
            model=self.settings["apis"]["openai"]["model"],
            temperature=0.3,
            api_key=get_env_var("OPENAI_API_KEY")
        )
        
        self.score_calculator = SwingScoreCalculator()
        self.signal_agent = SignalDetectionAgent()
        self.news_agent = NewsAnalysisAgent()
        self.risk_agent = RiskFilteringAgent()
        
        self.agent_executor: Optional[AgentExecutor] = None
        
    async def connect(self):
        """Initialize connections and create agent."""
        await self.score_calculator.connect()
        await self.signal_agent.connect()
        await self.news_agent.connect()
        await self.risk_agent.connect()
        
        # Create tools
        tools = self._create_tools()
        
        # Create prompt
        prompt = ChatPromptTemplate.from_messages([
            ("system", """You are a swing play scoring agent. Your job is to:
1. Coordinate signal detection (volume, technical indicators)
2. Coordinate news analysis (catalysts, sentiment)
3. Coordinate risk filtering (fundamentals, dilution)
4. Calculate comprehensive swing play score
5. Determine if the stock qualifies as a swing play candidate

Combine all signals into a final score and recommendation.
A swing play is a stock with multi-day upward potential, not a quick pump-and-dump."""),
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
        
        logger.info("Scoring Agent connected")
    
    async def disconnect(self):
        """Close connections."""
        await self.score_calculator.disconnect()
        await self.signal_agent.disconnect()
        await self.news_agent.disconnect()
        await self.risk_agent.disconnect()
    
    def _create_tools(self) -> List:
        """Create LangChain tools.
        
        Returns:
            List of LangChain tools
        """
        from langchain_core.tools import tool
        
        @tool
        async def calculate_swing_score(ticker: str, current_volume: int = None) -> str:
            """Calculate comprehensive swing play score for a ticker."""
            result = await self.score_calculator.calculate_score(ticker, current_volume)
            return str(result)
        
        @tool
        async def detect_signals(ticker: str) -> str:
            """Detect trading signals (volume, technical indicators)."""
            result = await self.signal_agent.detect_signals(ticker)
            return str(result)
        
        @tool
        async def analyze_news(ticker: str, hours: int = 24) -> str:
            """Analyze news and catalysts for a ticker."""
            result = await self.news_agent.analyze_news(ticker, hours)
            return str(result)
        
        @tool
        async def filter_risks(ticker: str) -> str:
            """Filter risks for a ticker."""
            result = await self.risk_agent.filter_risks(ticker)
            return str(result)
        
        return [
            calculate_swing_score,
            detect_signals,
            analyze_news,
            filter_risks
        ]
    
    async def score_ticker(self, ticker: str, current_volume: Optional[int] = None) -> Dict[str, Any]:
        """Score a ticker as a swing play candidate.
        
        Args:
            ticker: Ticker symbol
            current_volume: Current volume (optional)
            
        Returns:
            Scoring analysis
        """
        if not self.agent_executor:
            await self.connect()
        
        ticker = normalize_ticker(ticker)
        
        prompt = f"""Score {ticker} as a swing play candidate:
1. Detect trading signals (volume spikes, technical indicators)
2. Analyze news and catalysts
3. Filter risks (fundamentals, dilution)
4. Calculate comprehensive swing score
5. Determine if it qualifies as a swing play (multi-day upward potential)

Provide a detailed analysis with the final score and recommendation."""
        
        try:
            # Use the scoring calculator directly for now (more reliable)
            score_result = await self.score_calculator.calculate_score(ticker, current_volume)
            
            # Use agent for additional reasoning if needed
            agent_result = await self.agent_executor.ainvoke({
                "input": prompt
            })
            
            return {
                "ticker": ticker,
                "score": score_result,
                "agent_analysis": agent_result.get("output", ""),
                "success": True
            }
        
        except Exception as e:
            logger.error(f"Error scoring {ticker}: {e}")
            # Fallback to direct calculation
            try:
                score_result = await self.score_calculator.calculate_score(ticker, current_volume)
                return {
                    "ticker": ticker,
                    "score": score_result,
                    "success": True,
                    "warning": f"Agent error: {str(e)}, used direct calculation"
                }
            except Exception as e2:
                return {
                    "ticker": ticker,
                    "success": False,
                    "error": str(e2)
                }

