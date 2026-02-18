"""FastAPI webhook server for alerts."""
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import json
import asyncio
import os
from pathlib import Path
from utils.logger import get_logger, setup_logging
from utils.helpers import get_settings, normalize_ticker
from alerts.alert_manager import AlertManager
from scoring.swing_score_calculator import SwingScoreCalculator
from storage.timeseries_client import TimeseriesClient
from tests.backtesting import Backtester

# Setup logging
setup_logging()

logger = get_logger(__name__)

app = FastAPI(title="Stock Trading Assistant API", version="1.0.0")

# CORS middleware for web app
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify allowed origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files for dashboard
dashboard_path = Path(__file__).parent / "dashboard"
if dashboard_path.exists():
    app.mount("/alerts/dashboard", StaticFiles(directory=str(dashboard_path), html=True), name="dashboard")

# Global instances
alert_manager = AlertManager()
score_calculator = SwingScoreCalculator()
ts_client = TimeseriesClient()

# WebSocket connections for real-time dashboard
active_connections: List[WebSocket] = []

@app.middleware("http")
async def log_requests(request, call_next):
    """Log every API request so you can confirm the server is receiving them."""
    logger.info("API request: %s %s", request.method, request.url.path + ("?" + request.url.query if request.url.query else ""))
    response = await call_next(request)
    return response

@app.on_event("startup")
async def startup_event():
    """Initialize connections on startup."""
    await alert_manager.connect()
    await score_calculator.connect()
    await ts_client.connect()
    logger.info("Webhook server started — dashboard & API at http://localhost:8000 (Check ticker requests will log here)")

@app.on_event("shutdown")
async def shutdown_event():
    """Close connections on shutdown."""
    await alert_manager.disconnect()
    await score_calculator.disconnect()
    await ts_client.disconnect()
    logger.info("Webhook server stopped")

@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": "Stock Trading Assistant API",
        "version": "1.0.0",
        "status": "running"
    }

@app.get("/api/v1/alerts")
async def get_alerts(limit: int = 50, hours: int = 24):
    """Get recent alerts.
    
    Args:
        limit: Maximum number of alerts
        hours: Hours to look back
        
    Returns:
        List of alerts
    """
    since = datetime.now() - timedelta(hours=hours)
    alerts = await alert_manager.get_recent_alerts(limit=limit, since=since)
    return {"alerts": alerts, "count": len(alerts)}

@app.post("/api/v1/alerts/check")
async def check_ticker(ticker: str, current_volume: Optional[int] = None):
    """Check if a ticker qualifies for an alert. Always returns full score breakdown.
    
    Args:
        ticker: Ticker symbol
        current_volume: Current volume (optional)
        
    Returns:
        success, qualifies, score (full result), alert (if created)
    """
    try:
        ticker = normalize_ticker(ticker)
        logger.info("Check ticker: %s (calculating score...)", ticker)
        score_result = await score_calculator.calculate_score(ticker, current_volume)
        qualifies = score_result.get("qualifies", False)

        if qualifies:
            alert = await alert_manager.create_alert_from_score(ticker, score_result)
            if alert:
                await broadcast_alert(alert)
                logger.info("Check ticker: %s qualified (score %.1f)", ticker, score_result.get("total_score", 0))
                return {"success": True, "qualifies": True, "score": score_result, "alert": alert}
        logger.info("Check ticker: %s did not qualify (score %.1f)", ticker, score_result.get("total_score", 0))
        return {
            "success": True,
            "qualifies": False,
            "score": score_result,
            "message": "Did not qualify.",
        }
    except Exception as e:
        logger.error("Error checking ticker %s: %s", ticker, e)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/score")
async def score_ticker(ticker: str, current_volume: Optional[int] = None):
    """Calculate swing play score for a ticker.
    
    Args:
        ticker: Ticker symbol
        current_volume: Current volume (optional)
        
    Returns:
        Score result
    """
    try:
        ticker = normalize_ticker(ticker)
        score_result = await score_calculator.calculate_score(ticker, current_volume)
        return {"success": True, "score": score_result}
    
    except Exception as e:
        logger.error(f"Error scoring ticker {ticker}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/alerts/push")
async def push_alert(alert: Dict[str, Any]):
    """Push an alert to the dashboard (used by main.py when it creates an alert).
    
    Args:
        alert: Alert payload (ticker, score, message, metadata, created_at, etc.)
        
    Returns:
        Success and broadcast count
    """
    await broadcast_alert(alert)
    return {"success": True, "broadcast_to": len(active_connections)}

@app.get("/api/v1/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "active_connections": len(active_connections)
    }

@app.get("/api/v1/ticker/{ticker}/price-history")
async def get_price_history(ticker: str, days: int = 30):
    """Get price history for a ticker.
    
    Args:
        ticker: Ticker symbol
        days: Number of days of history
        
    Returns:
        Price history data
    """
    try:
        ticker = normalize_ticker(ticker)
        end_time = datetime.now()
        start_time = end_time - timedelta(days=days)
        
        prices = await ts_client.get_price_history(ticker, start_time, end_time)
        return {
            "success": True,
            "ticker": ticker,
            "data": prices,
            "count": len(prices)
        }
    except Exception as e:
        logger.error(f"Error getting price history for {ticker}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/ticker/{ticker}/performance")
async def get_ticker_performance(ticker: str, days: int = 90):
    """Get backtesting performance for a ticker.
    
    Args:
        ticker: Ticker symbol
        days: Number of days to look back
        
    Returns:
        Performance metrics
    """
    try:
        ticker = normalize_ticker(ticker)
        backtester = Backtester()
        await backtester.connect()
        
        start_date = datetime.now() - timedelta(days=days)
        end_date = datetime.now()
        
        result = await backtester.backtest_ticker(
            ticker,
            start_date,
            end_date,
            lookback_days=5
        )
        
        await backtester.disconnect()
        
        return {
            "success": True,
            "ticker": ticker,
            "performance": result
        }
    except Exception as e:
        logger.error(f"Error getting performance for {ticker}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/watchlist")
async def get_watchlist():
    """Get user watchlist from session/cookies.
    In production, this would use user authentication."""
    # For now, return empty watchlist - client-side localStorage will handle this
    return {"success": True, "watchlist": []}

@app.post("/api/v1/watchlist/{ticker}")
async def add_to_watchlist(ticker: str):
    """Add ticker to watchlist."""
    try:
        ticker = normalize_ticker(ticker)
        # In production, save to database with user ID
        return {"success": True, "message": f"{ticker} added to watchlist", "ticker": ticker}
    except Exception as e:
        logger.error(f"Error adding {ticker} to watchlist: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/v1/watchlist/{ticker}")
async def remove_from_watchlist(ticker: str):
    """Remove ticker from watchlist."""
    try:
        ticker = normalize_ticker(ticker)
        # In production, remove from database with user ID
        return {"success": True, "message": f"{ticker} removed from watchlist", "ticker": ticker}
    except Exception as e:
        logger.error(f"Error removing {ticker} from watchlist: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/preferences")
async def get_preferences():
    """Get user preferences. Client-side localStorage handles this."""
    return {
        "success": True,
        "preferences": {
            "minScore": 75,
            "enableNotifications": False,
            "defaultSort": "newest"
        }
    }

@app.websocket("/ws/alerts")
async def websocket_alerts(websocket: WebSocket):
    """WebSocket endpoint for real-time alerts.
    
    Args:
        websocket: WebSocket connection
    """
    await websocket.accept()
    active_connections.append(websocket)
    logger.info(f"WebSocket connection established ({len(active_connections)} active)")
    
    try:
        # Send recent alerts on connection
        recent_alerts = await alert_manager.get_recent_alerts(limit=10)
        await websocket.send_json({
            "type": "init",
            "alerts": recent_alerts
        })
        
        # Keep connection alive and listen for messages
        while True:
            try:
                data = await websocket.receive_text()
                # Echo or process message
                await websocket.send_json({
                    "type": "ack",
                    "message": "Message received"
                })
            except WebSocketDisconnect:
                break
            except Exception as e:
                logger.error(f"WebSocket error: {e}")
                break
    
    except Exception as e:
        logger.error(f"WebSocket connection error: {e}")
    finally:
        active_connections.remove(websocket)
        logger.info(f"WebSocket connection closed ({len(active_connections)} active)")

async def broadcast_alert(alert: Dict[str, Any]):
    """Broadcast alert to all WebSocket connections.
    
    Args:
        alert: Alert data
    """
    if not active_connections:
        return
    
    message = {
        "type": "alert",
        "data": alert,
        "timestamp": datetime.now().isoformat()
    }
    
    disconnected = []
    for connection in active_connections:
        try:
            await connection.send_json(message)
        except Exception as e:
            logger.error(f"Error broadcasting to WebSocket: {e}")
            disconnected.append(connection)
    
    # Remove disconnected connections
    for conn in disconnected:
        if conn in active_connections:
            active_connections.remove(conn)

if __name__ == "__main__":
    import uvicorn
    settings = get_settings()
    port = 8000  # Default port
    uvicorn.run(app, host="0.0.0.0", port=port)

