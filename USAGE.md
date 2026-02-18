# How to Use the Stock Trading Assistant

## Quick Start Guide

### 1. Setup and Installation

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Start infrastructure (PostgreSQL, TimescaleDB, ChromaDB)
docker-compose up -d

# 3. Initialize database schema
python -c "from storage.sql_client import SQLClient; import asyncio; asyncio.run(SQLClient().connect())"

# 4. Set up your API keys in .env file
# Required: POLYGON_API_KEY, OPENAI_API_KEY
# Optional: NEWSAPI_KEY, BENZINGA_API_KEY
```

### 2. Start the Services

#### Terminal 1: Start the Webhook Server (Dashboard & API)
```bash
python -m alerts.webhook_server
# Or: uvicorn alerts.webhook_server:app --host 0.0.0.0 --port 8000
```
This starts:
- **API Server** at `http://localhost:8000`
- **WebSocket** for real-time alerts at `ws://localhost:8000/ws/alerts`
- **Dashboard** at `http://localhost:8000/alerts/dashboard/index.html`
- **API Docs** at `http://localhost:8000/docs`

#### Terminal 2: Start the Main Trading Assistant
```bash
python main.py
```
This starts the real-time monitoring and alert generation system.

### 3. Access the Dashboard

Open your browser and navigate to:
```
http://localhost:8000/alerts/dashboard/index.html
```

## Using the Dashboard

### Features

1. **Real-time Alerts**: Alerts appear automatically via WebSocket connection
2. **Search**: Search by ticker symbol or catalyst type
3. **Filter**: Filter by score threshold or catalyst type
4. **Sort**: Sort by date, score, or ticker alphabetically
5. **Statistics**: View total alerts, filtered count, and average score

### Dashboard Controls

- **Search Box**: Type to search by ticker (e.g., "AAPL") or catalyst (e.g., "phase 3")
- **Sort Dropdown**: Choose how alerts are ordered:
  - Newest First (default)
  - Oldest First
  - Highest Score
  - Lowest Score
  - Ticker A-Z
- **Score Filter**: Show only alerts above a certain score (75+, 80+, 90+)
- **Catalyst Filter**: Filter by specific catalyst types (Phase 3, Partnership, Buyout, Short Squeeze)

### Alert Card Information

Each alert card displays:
- **Ticker Symbol**: Stock ticker (e.g., AAPL)
- **Total Score**: Overall swing play score out of 100
- **Alert Message**: Summary of why the alert was triggered
- **Catalyst**: Type of news catalyst detected
- **Volume Score**: Technical/volume analysis score
- **Fundamental Score**: Financial strength score
- **Dilution Risk**: Whether dilution risk was detected
- **Timestamp**: When the alert was created

### Connection Status

- **Green indicator**: Connected and receiving real-time alerts
- **Red indicator**: Disconnected (will auto-reconnect)

## Using the API

### Get Recent Alerts
```bash
curl http://localhost:8000/api/v1/alerts?limit=10&hours=24
```

### Check a Specific Ticker
```bash
curl -X POST "http://localhost:8000/api/v1/score?ticker=AAPL"
```

### Trigger Alert Check for a Ticker
```bash
curl -X POST "http://localhost:8000/api/v1/alerts/check?ticker=AAPL"
```

### Health Check
```bash
curl http://localhost:8000/api/v1/health
```

## Programmatic Usage

### Monitor Specific Tickers

Edit `main.py`:
```python
tickers = ["AAPL", "MSFT", "TSLA"]
await assistant.start(tickers)
```

### Manual Ticker Check

```python
from scoring.swing_score_calculator import SwingScoreCalculator
import asyncio

async def check_ticker():
    calculator = SwingScoreCalculator()
    await calculator.connect()
    
    result = await calculator.calculate_score("AAPL")
    print(f"Score: {result['total_score']}/100")
    print(f"Breakdown: {result['breakdown']}")
    
    await calculator.disconnect()

asyncio.run(check_ticker())
```

### Backtesting

```python
from tests.backtesting import Backtester
from datetime import datetime, timedelta
import asyncio

async def backtest():
    backtester = Backtester()
    await backtester.connect()
    
    start_date = datetime.now() - timedelta(days=90)
    end_date = datetime.now()
    
    result = await backtester.backtest_ticker(
        "AAPL",
        start_date,
        end_date,
        lookback_days=5
    )
    
    print(f"Win rate: {result['win_rate']:.2f}%")
    print(f"Avg return: {result['avg_return_pct']:.2f}%")
    
    await backtester.disconnect()

asyncio.run(backtest())
```

## Mobile Usage (Progressive Web App)

The dashboard can be installed as a PWA on mobile devices:

### iOS (Safari):
1. Open the dashboard in Safari
2. Tap the Share button
3. Select "Add to Home Screen"
4. The app will appear on your home screen like a native app

### Android (Chrome):
1. Open the dashboard in Chrome
2. Tap the menu (three dots)
3. Select "Add to Home Screen" or "Install App"
4. The app will be installed and accessible from your app drawer

## Tips

1. **Keep Both Services Running**: The webhook server (dashboard) and main assistant should both be running for full functionality
2. **Market Hours**: Best results during market hours when live data is available
3. **Filter High Scores**: Use the 80+ or 90+ filter to see only the highest quality swing play candidates
4. **Search by Catalyst**: If you're looking for specific catalyst types (e.g., "phase 3"), use the search box
5. **Desktop vs Mobile**: The dashboard works on both, but desktop provides better overview of multiple alerts

## Troubleshooting

### Dashboard Not Connecting
- Check that the webhook server is running: `http://localhost:8000/api/v1/health`
- Check browser console for WebSocket errors
- Verify CORS settings if accessing from a different domain

### No Alerts Showing
- Ensure `main.py` is running and monitoring tickers
- Check that tickers meet the minimum score threshold (default: 75/100)
- Verify API keys are correctly configured
- Check logs for errors in the main assistant process

### API Not Responding
- Verify the webhook server is running
- Check the API documentation at `http://localhost:8000/docs`
- Review server logs for error messages

## Next Steps

- Customize scoring weights in `config/scoring_weights.yaml`
- Adjust thresholds in `config/settings.yaml`
- Set up additional tickers to monitor in `main.py`
- Configure alert notification preferences (if implemented)

