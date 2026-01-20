"""Helper utilities and common functions."""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import yaml
from pathlib import Path
from functools import lru_cache
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def load_config(config_path: str) -> Dict[str, Any]:
    """Load YAML configuration file.
    
    Args:
        config_path: Path to YAML config file
        
    Returns:
        Configuration dictionary
    """
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)

@lru_cache(maxsize=1)
def get_settings() -> Dict[str, Any]:
    """Get application settings from config file.
    
    Returns:
        Settings dictionary
    """
    config_dir = Path(__file__).parent.parent / "config"
    return load_config(config_dir / "settings.yaml")

@lru_cache(maxsize=1)
def get_scoring_weights() -> Dict[str, Any]:
    """Get scoring weights from config file.
    
    Returns:
        Scoring weights dictionary
    """
    config_dir = Path(__file__).parent.parent / "config"
    return load_config(config_dir / "scoring_weights.yaml")

def get_env_var(key: str, default: Optional[str] = None) -> str:
    """Get environment variable.
    
    Args:
        key: Environment variable key
        default: Default value if not found
        
    Returns:
        Environment variable value
        
    Raises:
        ValueError: If key not found and no default provided
    """
    value = os.getenv(key, default)
    if value is None:
        raise ValueError(f"Environment variable {key} not set and no default provided")
    return value

def normalize_ticker(ticker: str) -> str:
    """Normalize ticker symbol.
    
    Args:
        ticker: Ticker symbol
        
    Returns:
        Normalized ticker (uppercase, no extra spaces)
    """
    return ticker.strip().upper()

def calculate_percentage_change(old_value: float, new_value: float) -> float:
    """Calculate percentage change between two values.
    
    Args:
        old_value: Old value
        new_value: New value
        
    Returns:
        Percentage change
    """
    if old_value == 0:
        return 0.0
    return ((new_value - old_value) / old_value) * 100

def format_currency(value: float, currency: str = "USD") -> str:
    """Format value as currency.
    
    Args:
        value: Numeric value
        currency: Currency code
        
    Returns:
        Formatted currency string
    """
    if currency == "USD":
        return f"${value:,.2f}"
    return f"{value:,.2f} {currency}"

def get_trading_days_ago(days: int, date: Optional[datetime] = None) -> datetime:
    """Get datetime for N trading days ago.
    
    Note: This is a simplified version that subtracts calendar days.
    For production, consider using a proper trading calendar.
    
    Args:
        days: Number of trading days
        date: Reference date (defaults to now)
        
    Returns:
        Datetime N trading days ago
    """
    if date is None:
        date = datetime.now()
    
    # Approximate: assume ~5 trading days per week, so ~7 calendar days = 5 trading days
    calendar_days = int(days * 7 / 5)
    return date - timedelta(days=calendar_days)

def is_market_hours(dt: Optional[datetime] = None) -> bool:
    """Check if current time is within market hours (9:30 AM - 4:00 PM ET).
    
    Args:
        dt: Datetime to check (defaults to now)
        
    Returns:
        True if within market hours
    """
    from pytz import timezone
    
    if dt is None:
        dt = datetime.now(timezone('US/Eastern'))
    else:
        # Convert to ET if needed
        if dt.tzinfo is None:
            dt = timezone('US/Eastern').localize(dt)
        else:
            dt = dt.astimezone(timezone('US/Eastern'))
    
    # Market hours: 9:30 AM - 4:00 PM ET
    market_open = dt.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = dt.replace(hour=16, minute=0, second=0, microsecond=0)
    
    # Check if it's a weekday (Monday=0, Sunday=6)
    is_weekday = dt.weekday() < 5
    
    return is_weekday and market_open <= dt <= market_close

def safe_divide(numerator: float, denominator: float, default: float = 0.0) -> float:
    """Safely divide two numbers, returning default if denominator is zero.
    
    Args:
        numerator: Numerator
        denominator: Denominator
        default: Default value if denominator is zero
        
    Returns:
        Division result or default
    """
    if denominator == 0:
        return default
    return numerator / denominator

def chunk_list(lst: List[Any], chunk_size: int) -> List[List[Any]]:
    """Split a list into chunks of specified size.
    
    Args:
        lst: List to chunk
        chunk_size: Size of each chunk
        
    Returns:
        List of chunks
    """
    return [lst[i:i + chunk_size] for i in range(0, len(lst), chunk_size)]

