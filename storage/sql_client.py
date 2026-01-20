"""SQL database client for PostgreSQL with TimescaleDB."""
import asyncpg
from typing import Optional, List, Dict, Any
from datetime import datetime
import json
from utils.logger import get_logger
from utils.helpers import get_env_var, get_settings

logger = get_logger(__name__)

class SQLClient:
    """PostgreSQL client with TimescaleDB support."""
    
    def __init__(self):
        self.pool: Optional[asyncpg.Pool] = None
        self.settings = get_settings()
        
    async def connect(self):
        """Create database connection pool."""
        db_config = {
            "host": get_env_var("POSTGRES_HOST", "localhost"),
            "port": int(get_env_var("POSTGRES_PORT", "5432")),
            "user": get_env_var("POSTGRES_USER", "stockuser"),
            "password": get_env_var("POSTGRES_PASSWORD", "stockpass"),
            "database": get_env_var("POSTGRES_DB", "stockassistant"),
        }
        
        pool_config = self.settings.get("database", {})
        
        self.pool = await asyncpg.create_pool(
            **db_config,
            min_size=pool_config.get("connection_pool_size", 10),
            max_size=pool_config.get("connection_pool_size", 10) + pool_config.get("max_overflow", 20),
            command_timeout=pool_config.get("query_timeout", 30),
        )
        
        await self._init_schema()
        logger.info("SQL client connected")
    
    async def disconnect(self):
        """Close database connection pool."""
        if self.pool:
            await self.pool.close()
            logger.info("SQL client disconnected")
    
    async def _init_schema(self):
        """Initialize database schema."""
        async with self.pool.acquire() as conn:
            # Enable TimescaleDB extension
            await conn.execute("CREATE EXTENSION IF NOT EXISTS timescaledb;")
            
            # Create hypertable for stock price data
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS stock_prices (
                    time TIMESTAMPTZ NOT NULL,
                    ticker VARCHAR(10) NOT NULL,
                    open NUMERIC(12, 4),
                    high NUMERIC(12, 4),
                    low NUMERIC(12, 4),
                    close NUMERIC(12, 4),
                    volume BIGINT,
                    vwap NUMERIC(12, 4),
                    PRIMARY KEY (time, ticker)
                );
            """)
            
            # Convert to hypertable if not already
            try:
                await conn.execute("""
                    SELECT create_hypertable('stock_prices', 'time', 
                        if_not_exists => TRUE);
                """)
            except Exception as e:
                logger.debug(f"Hypertable may already exist: {e}")
            
            # Create index on ticker
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_stock_prices_ticker 
                ON stock_prices (ticker, time DESC);
            """)
            
            # Create table for fundamentals
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS fundamentals (
                    ticker VARCHAR(10) NOT NULL,
                    date DATE NOT NULL,
                    market_cap BIGINT,
                    revenue NUMERIC(15, 2),
                    net_income NUMERIC(15, 2),
                    total_debt NUMERIC(15, 2),
                    total_equity NUMERIC(15, 2),
                    cash_and_equivalents NUMERIC(15, 2),
                    shares_outstanding BIGINT,
                    current_ratio NUMERIC(10, 4),
                    debt_to_equity NUMERIC(10, 4),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    PRIMARY KEY (ticker, date)
                );
            """)
            
            # Create table for alerts
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS alerts (
                    id SERIAL PRIMARY KEY,
                    ticker VARCHAR(10) NOT NULL,
                    score NUMERIC(5, 2),
                    alert_type VARCHAR(50),
                    message TEXT,
                    metadata JSONB,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    is_sent BOOLEAN DEFAULT FALSE,
                    INDEX idx_alerts_ticker_time (ticker, created_at DESC),
                    INDEX idx_alerts_created_at (created_at DESC)
                );
            """)
            
            # Create table for news
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS news (
                    id SERIAL PRIMARY KEY,
                    ticker VARCHAR(10),
                    title TEXT NOT NULL,
                    content TEXT,
                    source VARCHAR(255),
                    url TEXT,
                    published_at TIMESTAMPTZ,
                    sentiment_score NUMERIC(3, 2),
                    catalyst_type VARCHAR(50),
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(ticker, url, published_at)
                );
            """)
            
            # Create index on news ticker and published_at
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_news_ticker_time 
                ON news (ticker, published_at DESC);
            """)
            
            logger.info("Database schema initialized")
    
    async def insert_price_data(
        self,
        ticker: str,
        time: datetime,
        open: float,
        high: float,
        low: float,
        close: float,
        volume: int,
        vwap: Optional[float] = None
    ):
        """Insert stock price data."""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO stock_prices 
                (time, ticker, open, high, low, close, volume, vwap)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (time, ticker) DO UPDATE SET
                    open = EXCLUDED.open,
                    high = EXCLUDED.high,
                    low = EXCLUDED.low,
                    close = EXCLUDED.close,
                    volume = EXCLUDED.volume,
                    vwap = EXCLUDED.vwap;
            """, time, ticker.upper(), open, high, low, close, volume, vwap)
    
    async def get_price_history(
        self,
        ticker: str,
        start_time: datetime,
        end_time: datetime
    ) -> List[Dict[str, Any]]:
        """Get price history for a ticker."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT time, open, high, low, close, volume, vwap
                FROM stock_prices
                WHERE ticker = $1 AND time BETWEEN $2 AND $3
                ORDER BY time ASC;
            """, ticker.upper(), start_time, end_time)
            
            return [dict(row) for row in rows]
    
    async def insert_fundamentals(
        self,
        ticker: str,
        date: datetime,
        **kwargs
    ):
        """Insert fundamental data."""
        fields = [
            "market_cap", "revenue", "net_income", "total_debt",
            "total_equity", "cash_and_equivalents", "shares_outstanding",
            "current_ratio", "debt_to_equity"
        ]
        
        values = [ticker.upper(), date.date()]
        placeholders = ["$1", "$2"]
        update_clauses = []
        
        for i, field in enumerate(fields, start=3):
            if field in kwargs:
                values.append(kwargs[field])
                placeholders.append(f"${i}")
                update_clauses.append(f"{field} = EXCLUDED.{field}")
        
        if len(values) == 2:
            return  # No fundamental data to insert
        
        async with self.pool.acquire() as conn:
            await conn.execute(f"""
                INSERT INTO fundamentals 
                (ticker, date, {', '.join(f for f in fields if f in kwargs)})
                VALUES ({', '.join(placeholders)})
                ON CONFLICT (ticker, date) DO UPDATE SET
                    {', '.join(update_clauses)},
                    updated_at = NOW();
            """, *values)
    
    async def get_fundamentals(
        self,
        ticker: str,
        date: Optional[datetime] = None
    ) -> Optional[Dict[str, Any]]:
        """Get latest fundamental data for a ticker."""
        async with self.pool.acquire() as conn:
            if date:
                row = await conn.fetchrow("""
                    SELECT * FROM fundamentals
                    WHERE ticker = $1 AND date = $2;
                """, ticker.upper(), date.date())
            else:
                row = await conn.fetchrow("""
                    SELECT * FROM fundamentals
                    WHERE ticker = $1
                    ORDER BY date DESC
                    LIMIT 1;
                """, ticker.upper())
            
            return dict(row) if row else None
    
    async def insert_alert(
        self,
        ticker: str,
        score: float,
        alert_type: str,
        message: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> int:
        """Insert an alert."""
        async with self.pool.acquire() as conn:
            alert_id = await conn.fetchval("""
                INSERT INTO alerts (ticker, score, alert_type, message, metadata)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING id;
            """, ticker.upper(), score, alert_type, message, json.dumps(metadata or {}))
            
            return alert_id
    
    async def get_recent_alerts(
        self,
        limit: int = 100,
        since: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """Get recent alerts."""
        async with self.pool.acquire() as conn:
            if since:
                rows = await conn.fetch("""
                    SELECT * FROM alerts
                    WHERE created_at >= $1
                    ORDER BY created_at DESC
                    LIMIT $2;
                """, since, limit)
            else:
                rows = await conn.fetch("""
                    SELECT * FROM alerts
                    ORDER BY created_at DESC
                    LIMIT $1;
                """, limit)
            
            results = [dict(row) for row in rows]
            for result in results:
                if result.get("metadata"):
                    result["metadata"] = json.loads(result["metadata"])
            return results

