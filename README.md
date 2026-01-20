# Stock Trading Assistant - Real-time Swing Play Detection

A real-time stock trading assistant that detects high-volume movements, analyzes news catalysts (biotech phase 3 data, partnerships, buyouts, short squeezes), filters based on financial stability and dilution risks, and identifies multi-day swing play candidates using a hybrid LangChain + MCP architecture.

## Features

- **Real-time Market Data**: WebSocket integration with Polygon.io for live price and volume data
- **Volume Spike Detection**: Identifies stocks with >2.5x average volume and sustained momentum
- **News Catalyst Analysis**: LLM-powered classification of news types (phase 3, partnerships, buyouts, funding, short squeezes)
- **Technical Indicators**: RSI, MACD, moving averages, price breakouts
- **Risk Filtering**: Financial stability checks, dilution risk analysis, reverse split detection
- **Swing Play Scoring**: Weighted scoring model combining all signals (volume, catalyst, short squeeze, fundamentals)
- **Real-time Alerts**: WebSocket-based alerts with deduplication and rate limiting
- **Responsive Dashboard**: Modern web dashboard for viewing swing play candidates
- **Backtesting**: Historical validation of scoring model performance

## Architecture

The system uses a **hybrid LangChain + MCP (Model Context Protocol)** architecture:

- **MCP**: Standardizes tool interfaces for data sources (stock data, news, fundamentals)
- **LangChain**: Orchestrates complex multi-step reasoning and agent workflows
- **Real-time Processing**: Async/await for high-performance I/O operations

## Technology Stack

- **Language**: Python 3.11+
- **Agent Framework**: LangChain + LangGraph
- **Tool Protocol**: MCP (Model Context Protocol)
- **Real-time Data**: Polygon.io WebSocket API
- **News Sources**: NewsAPI, Benzinga API, OpenAI for sentiment
- **Storage**: 
  - TimescaleDB (time-series data)
  - PostgreSQL (fundamentals, alerts)
  - ChromaDB (news embeddings)
- **Alerting**: FastAPI + WebSocket for real-time dashboard
- **LLM**: OpenAI GPT-4 for news analysis

## Quick Start

### Prerequisites

- Python 3.11+
- Docker and Docker Compose
- API Keys:
  - Polygon.io API key
  - OpenAI API key
  - NewsAPI key (optional)
  - Benzinga API key (optional)

### Installation

1. **Clone the repository**
```bash
git clone <repository-url>
cd star
```

2. **Set up environment variables**
```bash
cp .env.example .env
# Edit .env with your API keys
```

3. **Start infrastructure services**
```bash
docker-compose up -d
```

4. **Install Python dependencies**
```bash
pip install -r requirements.txt
```

5. **Initialize database schema**
```python
# Run once to initialize schema
python -c "from storage.sql_client import SQLClient; import asyncio; asyncio.run(SQLClient().connect())"
```

6. **Start the webhook server (for alerts API and dashboard)**
```bash
python -m alerts.webhook_server
# Or with uvicorn directly:
uvicorn alerts.webhook_server:app --host 0.0.0.0 --port 8000
```

7. **Start the main trading assistant**
```bash
python main.py
```

8. **Access the dashboard**
Open http://localhost:8000/alerts/dashboard/index.html in your browser

## Configuration

Configuration files are in `config/`:

- **`settings.yaml`**: API configuration, thresholds, signal detection parameters
- **`scoring_weights.yaml`**: Scoring model weights and thresholds

Key settings:
- `volume_spike_multiplier`: Threshold for volume spike detection (default: 2.5x)
- `min_total_score`: Minimum score for alert (default: 75/100)
- `deduplication_window_minutes`: Alert deduplication window (default: 60 min)

## Usage

### Monitor Specific Tickers

Edit `main.py` to specify tickers:

```python
tickers = ["AAPL", "MSFT", "TSLA"]
await assistant.start(tickers)
```

### Check a Ticker Manually

```python
from scoring.swing_score_calculator import SwingScoreCalculator
import asyncio

async def check_ticker():
    calculator = SwingScoreCalculator()
    await calculator.connect()
    
    result = await calculator.calculate_score("AAPL")
    print(result)
    
    await calculator.disconnect()

asyncio.run(check_ticker())
```

### Use the API

```bash
# Get recent alerts
curl http://localhost:8000/api/v1/alerts

# Check a specific ticker
curl -X POST http://localhost:8000/api/v1/score?ticker=AAPL

# Create alert for ticker
curl -X POST http://localhost:8000/api/v1/alerts/check?ticker=AAPL
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

## Project Structure

```
team-ocl/
├── config/              # Configuration files
├── mcp_tools/           # MCP tool servers
├── agents/              # LangChain agents
├── ingestion/           # Data ingestion layer
├── processing/          # Signal processing
├── scoring/             # Risk and scoring engine
├── alerts/              # Alert system
│   └── dashboard/       # Web dashboard
├── storage/             # Database clients
├── utils/               # Utilities
├── tests/               # Tests and backtesting
├── main.py              # Main entry point
└── requirements.txt     # Python dependencies
```

## Scoring Model

The swing play score combines:

- **Volume/Technical Score (30%)**: Volume spike + technical breakout
- **Catalyst Score (35%)**: News quality + sentiment + catalyst type
- **Short Squeeze Potential (15%)**: Short interest ratio, days-to-cover
- **Fundamental Strength (20%)**: Financial stability, low dilution risk

Only stocks with score >75/100 AND passing all critical filters trigger alerts.

## User Interface Recommendations

### Recommended: Responsive Web App with PWA Features

**We recommend a responsive web application** as the primary user interface for the following reasons:

#### Advantages:
- ✅ **Cross-platform compatibility**: Works on desktop, tablet, and mobile devices
- ✅ **Easy maintenance**: Single codebase instead of separate iOS/Android apps
- ✅ **Quick updates**: No app store approval process required
- ✅ **Better for data visualization**: Charts, tables, and complex data are easier to display
- ✅ **Real-time capabilities**: WebSocket support for live alerts
- ✅ **Cost-effective**: Lower development and maintenance costs
- ✅ **Progressive Web App (PWA) support**: Can provide native-like features (push notifications, offline mode, installable)

#### When to Consider Native Mobile App:
- If you need advanced native device features (biometric auth, background location)
- If you require iOS App Store / Google Play distribution
- If users demand native performance for complex calculations

### Enhanced Dashboard Features

The current responsive web dashboard (`alerts/dashboard/index.html`) provides:
- ✅ Real-time alerts via WebSocket connection
- ✅ Detailed score breakdown (volume, catalyst, fundamental, short squeeze)
- ✅ Catalyst information and news analysis
- ✅ Risk factors display (dilution risk, financial stability)
- ✅ Mobile-friendly responsive design
- ✅ Dark mode optimized interface

### Future Enhancement Ideas:
- 📊 Interactive charts (price action, volume spikes)
- 🔔 Browser push notifications (PWA)
- 🔍 Search and filter alerts (by ticker, score, catalyst type)
- 📱 Install as PWA app (Add to Home Screen)
- 📈 Historical performance tracking
- ⚙️ User preferences and alert customization
- 📊 Watchlist management
- 📱 Offline mode with cached data

## Dashboard

### Accessing the Dashboard

1. **Start the webhook server** (if not already running):
   ```bash
   python -m alerts.webhook_server
   ```

2. **Open in browser**:
   ```
   http://localhost:8000/alerts/dashboard/index.html
   ```

3. **The dashboard will:**
   - Automatically connect via WebSocket
   - Display real-time alerts as they're generated
   - Show connection status indicator (green = connected, red = disconnected)
   - Auto-reconnect if connection is lost

### Using the Dashboard

- **View Alerts**: All qualifying swing play candidates appear as cards
- **Alert Details**: Each card shows:
  - Ticker symbol and total score
  - Catalyst type (phase 3, partnership, buyout, etc.)
  - Volume score, fundamental score
  - Dilution risk indicator
  - Timestamp
  
- **Real-time Updates**: New alerts appear automatically at the top with animation
- **Mobile View**: Responsive layout adapts to smaller screens

## Development

### Running Tests

```bash
pytest tests/
```

### Code Style

This project follows PEP 8 style guidelines.

## API Documentation

When the webhook server is running, API docs are available at:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## License

[Add your license here]

## Contributing

[Add contribution guidelines here]

## Support

[Add support information here]

