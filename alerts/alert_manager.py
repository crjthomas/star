"""Alert manager for threshold-based alerting and deduplication."""
from typing import Dict, Any, List, Optional, Set
from datetime import datetime, timedelta
from utils.logger import get_logger
from utils.helpers import get_settings, normalize_ticker
from storage.sql_client import SQLClient
from scoring.swing_score_calculator import SwingScoreCalculator

logger = get_logger(__name__)

class AlertManager:
    """Manages alerts with deduplication and threshold checks."""
    
    def __init__(self):
        self.settings = get_settings()
        self.sql_client = SQLClient()
        self.score_calculator = SwingScoreCalculator()
        
        alert_config = self.settings.get("alerts", {})
        self.deduplication_window = alert_config.get("deduplication_window_minutes", 60)
        self.max_alerts_per_hour = alert_config.get("max_alerts_per_hour", 10)
        self.cooldown_period = alert_config.get("cooldown_period_minutes", 30)
        
        # Track recent alerts for deduplication
        self.recent_alerts: Set[str] = set()
        self.alert_counts: Dict[str, int] = {}  # ticker -> count in last hour
        
    async def connect(self):
        """Initialize database connection."""
        await self.sql_client.connect()
        await self.score_calculator.connect()
        logger.info("Alert Manager connected")
    
    async def disconnect(self):
        """Close database connection."""
        await self.sql_client.disconnect()
        await self.score_calculator.disconnect()
    
    async def check_and_create_alert(
        self,
        ticker: str,
        current_volume: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """Check if ticker qualifies for alert and create it.
        
        Args:
            ticker: Ticker symbol
            current_volume: Current volume (optional)
            
        Returns:
            Alert data if created, None otherwise
        """
        ticker = normalize_ticker(ticker)
        
        # Check deduplication
        if await self._is_duplicate(ticker):
            logger.debug(f"Skipping duplicate alert for {ticker}")
            return None
        
        # Check rate limiting
        if await self._is_rate_limited(ticker):
            logger.debug(f"Rate limited for {ticker}")
            return None
        
        # Calculate score
        try:
            score_result = await self.score_calculator.calculate_score(ticker, current_volume)
            
            if not score_result.get("qualifies"):
                logger.debug(f"{ticker} does not qualify (score: {score_result.get('total_score', 0)})")
                return None
            
            # Create alert
            alert = await self._create_alert(ticker, score_result)
            
            # Track for deduplication
            self._track_alert(ticker)
            
            return alert
        
        except Exception as e:
            logger.error(f"Error checking alert for {ticker}: {e}")
            return None

    async def create_alert_from_score(
        self, ticker: str, score_result: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Create an alert from an already-computed score (e.g. from Check ticker). Skips dedup/rate limit."""
        ticker = normalize_ticker(ticker)
        if not score_result.get("qualifies"):
            return None
        try:
            alert = await self._create_alert(ticker, score_result)
            self._track_alert(ticker)
            return alert
        except Exception as e:
            logger.error(f"Error creating alert from score for {ticker}: {e}")
            return None
    
    async def _is_duplicate(self, ticker: str) -> bool:
        """Check if alert was recently created for this ticker.
        
        Args:
            ticker: Ticker symbol
            
        Returns:
            True if duplicate
        """
        # Check in-memory cache
        alert_key = f"{ticker}:{datetime.now().strftime('%Y-%m-%d-%H')}"
        if alert_key in self.recent_alerts:
            return True
        
        # Check database
        since = datetime.now() - timedelta(minutes=self.deduplication_window)
        recent = await self.sql_client.get_recent_alerts(limit=100, since=since)
        
        for alert in recent:
            if alert.get("ticker") == ticker:
                alert_time = alert.get("created_at")
                if isinstance(alert_time, str):
                    alert_time = datetime.fromisoformat(alert_time.replace("Z", "+00:00"))
                
                if alert_time and (datetime.now() - alert_time.replace(tzinfo=None)) < timedelta(minutes=self.deduplication_window):
                    return True
        
        return False
    
    async def _is_rate_limited(self, ticker: str) -> bool:
        """Check if ticker is rate limited.
        
        Args:
            ticker: Ticker symbol
            
        Returns:
            True if rate limited
        """
        # Check recent alert count for this ticker
        since = datetime.now() - timedelta(hours=1)
        recent = await self.sql_client.get_recent_alerts(limit=1000, since=since)
        
        ticker_alerts = [a for a in recent if a.get("ticker") == ticker]
        
        if len(ticker_alerts) >= self.max_alerts_per_hour:
            return True
        
        # Check cooldown period
        if ticker_alerts:
            last_alert = ticker_alerts[0]
            alert_time = last_alert.get("created_at")
            if isinstance(alert_time, str):
                alert_time = datetime.fromisoformat(alert_time.replace("Z", "+00:00"))
            
            if alert_time and (datetime.now() - alert_time.replace(tzinfo=None)) < timedelta(minutes=self.cooldown_period):
                return True
        
        return False
    
    async def _create_alert(
        self,
        ticker: str,
        score_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Create an alert.
        
        Args:
            ticker: Ticker symbol
            score_result: Score calculation result
            
        Returns:
            Alert data
        """
        total_score = score_result.get("total_score", 0)
        
        # Create alert message
        message = self._format_alert_message(ticker, score_result)
        
        # Store alert
        alert_id = await self.sql_client.insert_alert(
            ticker=ticker,
            score=total_score,
            alert_type="swing_play_candidate",
            message=message,
            metadata=score_result
        )
        
        alert = {
            "id": alert_id,
            "ticker": ticker,
            "score": total_score,
            "alert_type": "swing_play_candidate",
            "message": message,
            "metadata": score_result,
            "created_at": datetime.now().isoformat()
        }
        
        logger.info(f"Alert created for {ticker} (score: {total_score:.2f})")
        
        return alert
    
    def _format_alert_message(
        self,
        ticker: str,
        score_result: Dict[str, Any]
    ) -> str:
        """Format alert message.
        
        Args:
            ticker: Ticker symbol
            score_result: Score calculation result
            
        Returns:
            Formatted message
        """
        total_score = score_result.get("total_score", 0)
        catalyst = score_result.get("catalyst", {})
        volume = score_result.get("volume_technical", {})
        fundamental = score_result.get("fundamental", {})
        
        strongest_catalyst = catalyst.get("strongest_catalyst", "N/A")
        catalyst_score = catalyst.get("score", 0)
        volume_score = volume.get("score", 0)
        
        pump = score_result.get("pump_potential", {})
        pump_line = ""
        if pump.get("has_pump_potential"):
            pump_line = f"🔥 Pump potential: {pump.get('score', 0):.0f}/100\n"
        message = f"""🚀 Swing Play Alert: {ticker}
Score: {total_score:.1f}/100

Strongest Catalyst: {strongest_catalyst} ({catalyst_score:.1f})
Volume/Technical: {volume_score:.1f}/100
Fundamental: {fundamental.get('score', 0):.1f}/100
{pump_line}
"""
        
        if score_result.get("bonuses", {}).get("reasons"):
            message += f"Bonuses: {', '.join(score_result['bonuses']['reasons'])}\n"
        
        if score_result.get("penalties", {}).get("reasons"):
            message += f"Penalties: {', '.join(score_result['penalties']['reasons'])}\n"
        
        return message.strip()
    
    def _track_alert(self, ticker: str):
        """Track alert for deduplication.
        
        Args:
            ticker: Ticker symbol
        """
        alert_key = f"{ticker}:{datetime.now().strftime('%Y-%m-%d-%H')}"
        self.recent_alerts.add(alert_key)
        
        # Clean old entries periodically
        if len(self.recent_alerts) > 1000:
            # Remove entries older than deduplication window
            cutoff = (datetime.now() - timedelta(minutes=self.deduplication_window)).strftime('%Y-%m-%d-%H')
            self.recent_alerts = {k for k in self.recent_alerts if k > cutoff}
    
    async def get_recent_alerts(
        self,
        limit: int = 50,
        since: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """Get recent alerts.
        
        Args:
            limit: Maximum number of alerts
            since: Start time (optional)
            
        Returns:
            List of alerts
        """
        return await self.sql_client.get_recent_alerts(limit=limit, since=since)

