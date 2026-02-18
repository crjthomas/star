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

3. **Start infrastructure services (required before schema init)**

   PostgreSQL (TimescaleDB), Redis, and ChromaDB run in Docker. **You must start these before initializing the schema or running the app.**

```bash
docker-compose up -d
```

   Wait until Postgres is ready (usually 10–20 seconds), then check:

```bash
docker-compose ps
# postgres should show "Up (healthy)"
# Or: nc -z localhost 5432 && echo "Postgres is reachable"
```

4. **Install Python dependencies**
```bash
pip install -r requirements.txt
```

5. **Initialize database schema** (only after step 3 is running)

   If you see `[Errno 61] Connect call failed ... 5432`, Postgres is not running — go back to step 3.

```bash
python -c "from storage.sql_client import SQLClient; import asyncio; asyncio.run(SQLClient().connect())"
```

6. **Start the alert system (recommended: one command)**

   **Hands-free, robust alerting** — one process runs both the dashboard server and the market scanner. No manual ticker search; the scanner watches all stocks and pushes qualifying alerts to the dashboard automatically.

```bash
python run_alert_system.py
```

   This starts the webhook server (dashboard + API) and the market scanner (Polygon all-stocks feed). Open **http://localhost:8000/alerts/dashboard/index.html** and leave the terminal running. Alerts appear when any stock qualifies (score > 75, volume, catalyst, etc.). Press Ctrl+C to stop both.

   **Alternative (two terminals):** run the webhook server in one terminal (`python -m alerts.webhook_server`) and the scanner in another (`python main.py`). Same behavior; the launcher is for convenience.

7. **Open the dashboard**  
   In your browser go to: **http://localhost:8000/alerts/dashboard/index.html**  
   (Use that URL from the running server—do not open the HTML file directly as `file://` or the API won’t work.)

   - You should see a **“Check ticker”** bar at the top (input + **Check ticker** button). If you don’t, do a **hard refresh**: Ctrl+Shift+R (Windows/Linux) or Cmd+Shift+R (Mac), or open in a private/incognito window.
   - With `run_alert_system.py` (or webhook + `main.py`) running, alerts appear in real time. You can also type a symbol (e.g. AAPL) and click **Check ticker** to test.

## Configuration

Configuration files are in `config/`:

- **`settings.yaml`**: API configuration, thresholds, signal detection parameters
- **`scoring_weights.yaml`**: Scoring model weights and thresholds

Key settings:
- `volume_spike_multiplier`: Threshold for volume spike detection (default: 2.5x)
- `min_total_score`: Minimum score for alert (default: 75/100)
- `deduplication_window_minutes`: Alert deduplication window (default: 60 min)

## How automatic alerts work

1. The **scanner** (main.py) connects to Polygon’s WebSocket and, by default, subscribes to **all stocks** (`monitor_all_stocks: true` in config).
2. For each aggregate message that passes the volume filter, it runs the swing-play score (volume spike, catalyst, fundamentals, etc.).
3. If the score is above the threshold (default 75/100) and other filters pass, it creates an alert and **POSTs it to the webhook server**.
4. The **webhook server** broadcasts that alert to every open dashboard tab. You don’t search for tickers—alerts are pushed to you.
5. Run **`python run_alert_system.py`** once; keep it running. The WebSocket listener reconnects automatically on disconnect so the scanner stays live.

### Monitor all stocks (any stock can trigger an alert)

By default the app is configured to **monitor the entire market**. In `config/settings.yaml` under `apis.polygon`:

- **`monitor_all_stocks: true`** – Subscribe to Polygon’s feed for all stocks (`A.*`). Any symbol with enough volume is evaluated; when one meets the swing-play criteria (score > 75, etc.), you get an alert.
- **`min_volume_to_consider: 50000`** – Only run full scoring when the message volume is above this (reduces noise and API load).
- **`per_ticker_cooldown_seconds: 120`** – Don’t re-run the full score for the same ticker more than once every 2 minutes.

So you get alerts when **any** stock that could run today or this week is identified, not just a fixed list. To go back to a fixed list, set `monitor_all_stocks: false` and configure tickers in `main.py` (see below).

### Monitor specific tickers only

Set `monitor_all_stocks: false` in `config/settings.yaml`, then edit `main.py` to set the tickers to monitor:

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

**Dashboard empty?**
1. Ensure **both** are running: `python -m alerts.webhook_server` (terminal 1) and `python main.py` (terminal 2).
2. Alerts only appear when a stock **qualifies** (score > 75, volume spike, etc.). During market hours, run both and wait for data, or use the **Check ticker** box on the dashboard (e.g. enter AAPL and click Check) to test: if that ticker qualifies, an alert appears; otherwise you’ll see “did not qualify”.
3. Open the dashboard at **http://localhost:8000/alerts/dashboard/index.html** (same host as the webhook server).

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

## Troubleshooting

### No logs when clicking “Check ticker”

**Cause:** The dashboard and all APIs (including Check ticker) are served by the **webhook server**, not by `main.py`. If you only run `python main.py`, nothing is listening on port 8000, so the request never reaches the app and you see no logs.

**Fix:**

1. Start the webhook server in a terminal:
   ```bash
   python -m alerts.webhook_server
   ```
   Or use the combined launcher: `python run_alert_system.py` (this starts both the webhook server and the scanner).
2. Watch **that** terminal. When you click Check ticker you should see:
   - `API request: POST /api/v1/alerts/check?ticker=SOUN`
   - `Check ticker: SOUN (calculating score...)`
   - then either `Check ticker: SOUN qualified` or `Check ticker: SOUN did not qualify`.
3. Open the dashboard at **http://localhost:8000/alerts/dashboard/index.html** (so the browser talks to the same server).

### `OSError: [Errno 61] Connect call failed ('127.0.0.1', 5432)` (or `::1`, 5432)

**Cause:** PostgreSQL is not running. The app and schema init connect to Postgres on `localhost:5432`.

**Fix:**

1. Start the stack and ensure Postgres is up:
   ```bash
   docker-compose up -d
   docker-compose ps   # postgres should be "Up (healthy)"
   ```
2. If Docker isn’t running, start Docker Desktop (or your Docker daemon) first.
3. If port 5432 is already in use (e.g. a local Postgres install), either stop that service or change the port in `docker-compose.yml` and set `POSTGRES_PORT` in `.env` to match.
4. Run schema init again:
   ```bash
   python -c "from storage.sql_client import SQLClient; import asyncio; asyncio.run(SQLClient().connect())"
   ```

### Connection works but schema init fails

- Ensure the TimescaleDB image is used: `timescale/timescaledb:latest-pg16` in `docker-compose.yml`.
- Check logs: `docker-compose logs postgres`.

### `ssl.SSLCertVerificationError: certificate verify failed` (macOS)

**Cause:** Python on macOS (e.g. from python.org) may not use the system CA bundle, so HTTPS/WSS connections fail.

**Fix:** The app uses `certifi` for the Polygon WebSocket. Install deps so certifi is available: `pip install -r requirements.txt`. If you still see the error elsewhere, run the macOS certificate installer: open **Applications → Python 3.12 → Install Certificates.command** (or equivalent for your Python version).

### `asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already`

**Cause:** The app opens many Postgres connection pools (one per component); total connections exceeded Postgres’ limit.

**Fix:**

1. **Config:** `config/settings.yaml` uses smaller pools (`connection_pool_size: 2`, `max_overflow: 5`) so total connections stay under the limit.
2. **Postgres:** `docker-compose.yml` sets `max_connections=200` for the Postgres container. Restart Postgres so it takes effect:
   ```bash
   docker-compose stop postgres && docker-compose up -d postgres
   ```
3. Restart the webhook server (and any other app processes) so they use the new pool sizes.

### `ValueError: Could not connect to tenant default_tenant` (ChromaDB)

**Cause:** ChromaDB server and Python client version mismatch (e.g. `chromadb/chroma:latest` uses a different API than client 0.4.x).

**Fix:**

1. Recreate the Chroma container with the pinned image (already set in `docker-compose.yml` to `chromadb/chroma:0.4.22`):
   ```bash
   docker-compose stop chromadb
   docker-compose rm -f chromadb
   docker-compose up -d chromadb
   ```
2. ChromaDB is on host port **8010** (webhook server uses 8000). The app uses `CHROMADB_PORT=8010` by default; override with `CHROMADB_PORT` in `.env` if needed.

### `ValueError: Could not connect to a Chroma server`

**Cause:** ChromaDB is not running or not reachable (wrong host/port).

**Options:**

1. **Start ChromaDB** (for news embeddings):
   ```bash
   docker-compose up -d chromadb
   ```
   Ensure `.env` has `CHROMADB_PORT=8010` (or leave unset to use the default).

2. **Run without ChromaDB:** The webhook server will start anyway and log a warning; only news-embedding features are disabled. No need to run the Chroma container if you don’t need those.

## License

[Add your license here]

## Contributing

[Add contribution guidelines here]

## Support

[Add support information here]

