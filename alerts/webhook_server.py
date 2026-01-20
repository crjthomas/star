"""FastAPI webhook server for alerts."""
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import json
import asyncio
from utils.logger import get_logger, setup_logging
from utils.helpers import get_settings, normalize_ticker
from alerts.alert_manager import AlertManager
from scoring.swing_score_calculator import SwingScoreCalculator

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

# Global instances
alert_manager = AlertManager()
score_calculator = SwingScoreCalculator()

# WebSocket connections for real-time dashboard
active_connections: List[WebSocket] = []

@app.on_event("startup")
async def startup_event():
    """Initialize connections on startup."""
    await alert_manager.connect()
    await score_calculator.connect()
    logger.info("Webhook server started")

@app.on_event("shutdown")
async def shutdown_event():
    """Close connections on shutdown."""
    await alert_manager.disconnect()
    await score_calculator.disconnect()
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
    """Check if a ticker qualifies for an alert.
    
    Args:
        ticker: Ticker symbol
        current_volume: Current volume (optional)
        
    Returns:
        Alert result
    """
    try:
        ticker = normalize_ticker(ticker)
        alert = await alert_manager.check_and_create_alert(ticker, current_volume)
        
        if alert:
            # Broadcast to WebSocket connections
            await broadcast_alert(alert)
            return {"success": True, "alert": alert}
        else:
            return {"success": False, "message": "Ticker does not qualify for alert"}
    
    except Exception as e:
        logger.error(f"Error checking ticker {ticker}: {e}")
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

@app.get("/api/v1/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "active_connections": len(active_connections)
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

