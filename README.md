# Dhan Algo Trading System

Production-grade algorithmic trading system for Indian markets using the [Dhan](https://dhan.co) broker API. Supports **live trading**, **paper trading**, and **backtesting** with a configurable EMA-based strategy.

---

## Architecture

```
src/
├── core/           Config, logging, constants
├── data/           Dhan API client, market data manager
├── indicators/     EMA, ATR, volume indicators
├── strategy/       Base strategy + EMA strategy implementation
├── execution/      Order manager, position manager
├── risk/           Risk management & kill switch
├── backtest/       Backtesting engine & reporting
├── live/           Live/paper trading engine
├── webhooks/       Dhan postback/webhook receiver
├── notifications/  Telegram alerts
└── utils/          Helpers
```

## Quick Start

### 1. Install Dependencies

```bash
python -m venv venv
source venv/bin/activate    # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure API Credentials

```bash
cp .env.example .env
```

Edit `.env` and add your Dhan credentials:

```
DHAN_CLIENT_ID=your_client_id
DHAN_ACCESS_TOKEN=your_access_token
TRADING_MODE=paper
```

Get your API key from [Dhan Developer Portal](https://api.dhan.co).

### 3. Review Configuration

All strategy parameters are in `config/default.yaml`. Key settings:

| Setting | Description | Default |
|---------|-------------|---------|
| `symbol` | Trading instrument | NIFTY |
| `timeframe` | Candle timeframe | 5m |
| `ema.primary_period` | Primary EMA trigger | 7 |
| `ema.short_period` | Short EMA (crossover) | 9 |
| `ema.long_period` | Long EMA (crossover) | 21 |
| `risk.lot_size` | Quantity per trade | 50 |
| `risk.max_trades_per_day` | Daily trade limit | 5 |
| `risk.max_loss_per_day` | Kill switch (INR) | 5000 |

---

## Running Backtests

### With Dhan API data:

```bash
python run_backtest.py --start 2025-01-01 --end 2025-06-30 --trades --export
```

### With sample/synthetic data (no API needed):

```bash
# Generate sample data
python tools/generate_sample_data.py --days 90 --output data/sample.csv

# Run backtest on it
python run_backtest.py --csv data/sample.csv --trades --export
```

### Backtest flags:

| Flag | Description |
|------|-------------|
| `--config` | Custom config file path |
| `--csv` | Use CSV file instead of API |
| `--start` | Override start date |
| `--end` | Override end date |
| `--trades` | Print trade log |
| `--export` | Export trades & equity to CSV |

### Sample output:

```
============================================================
  BACKTEST RESULTS
============================================================
   Total Trades  47
      Win / Loss  28 / 19
        Win Rate  +59.57%

       Gross PnL  +₹32,450.00
      Commission  -₹1,880.00
         Net PnL  +₹30,570.00
          Return  +6.11%

         Avg Win  +₹1,850.25
        Avg Loss  -₹1,023.50
     Largest Win  +₹4,200.00
    Largest Loss  -₹2,500.00
   Profit Factor  2.15
      Expectancy  +₹650.43

    Sharpe Ratio  1.82
    Max Drawdown  -₹8,200.00
        Max DD %  -1.60%
============================================================
```

---

## Live / Paper Trading

### Paper trading (default, no real money):

```bash
python run_live.py --mode paper
```

### Live trading (real orders):

```bash
# Ensure .env has valid credentials
python run_live.py --mode live
```

### Flags:

| Flag | Description |
|------|-------------|
| `--config` | Custom config file |
| `--mode` | `live` or `paper` |

---

## Strategy Logic

### Entry Conditions (LONG)

1. Price closes **above EMA 7**
2. (Optional) EMA short > EMA long (bullish trend confirmation)
3. Entry trigger:
   - **Breakout**: Current close > previous candle high
   - **Pullback**: Price touches EMA 7 and bounces
4. Sideways filter: ATR must exceed threshold
5. (Optional) Volume confirmation

### Entry Conditions (SHORT)

Mirror of long conditions with inverted logic.

### Exit Conditions

- **Stop Loss**: Fixed points/%, swing high/low, or EMA breach
- **Target**: Risk:reward ratio, fixed points/%
- **Trailing SL**: Activates at configurable profit %, trails by %
- **Time exit**: Close positions before market close
- **Opposite signal**: Exit when reverse signal appears

---

## Risk Management

- **Max trades/day**: Hard limit on daily entries
- **Kill switch**: Stops all trading if daily loss exceeds threshold
- **Single position**: Only one active trade at any time
- **Position sizing**: Based on risk per trade % and stop loss distance
- **Trading hours**: Configurable entry window (default: 09:20–15:15 IST)
- **Force exit**: All positions closed before 15:25 IST

---

## Telegram Alerts

Enable in `config/default.yaml`:

```yaml
telegram:
  enabled: true
```

Set bot credentials in `.env`:

```
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

Alerts include: entry, exit, errors, order status updates, and daily summary.

---

## Webhook / Postback Integration

The system includes a built-in HTTP server to receive **Dhan Postback** (webhook) notifications. When enabled, Dhan sends real-time order status updates (TRADED, REJECTED, CANCELLED, EXPIRED, etc.) directly to your server via HTTP POST.

### Setup

**1. Enable in config:**

```yaml
webhook:
  enabled: true
  host: "0.0.0.0"
  port: 8443
  auth_token: "your_secret"   # optional
```

**2. Set the Postback URL in Dhan API settings:**

Go to [Dhan Developer Portal](https://api.dhan.co) → your app → set Postback URL to:

```
http://<your-server-ip>:8443/
```

For local development, use [ngrok](https://ngrok.com) or similar:

```bash
ngrok http 8443
# Then set the ngrok URL as your Postback URL in Dhan
```

**3. Optional auth token in `.env`:**

```
WEBHOOK_AUTH_TOKEN=your_secret
```

If set, only requests with a matching `X-Webhook-Token` header will be accepted.

### What it does

| Order Status | Action |
|-------------|--------|
| **TRADED** | Reconciles fill price with position manager, logs execution |
| **REJECTED** | Logs error details, closes orphaned position record, alerts via Telegram |
| **CANCELLED** | Logs cancellation, cleans up pending order tracking |
| **EXPIRED** | Logs expiry, alerts via Telegram |
| **PENDING/TRANSIT** | Tracks order in pending set for monitoring |

### Health check

```bash
curl http://localhost:8443/health
# {"status": "healthy", "service": "dhan_algo_webhook"}
```

### Postback payload

The server expects the standard Dhan postback JSON format:

```json
{
    "dhanClientId": "1000000003",
    "orderId": "112111182198",
    "correlationId": "123abc678",
    "orderStatus": "TRADED",
    "transactionType": "BUY",
    "exchangeSegment": "NSE_EQ",
    "productType": "INTRADAY",
    "orderType": "MARKET",
    "securityId": "11536",
    "quantity": 50,
    "price": 22150.50,
    ...
}
```

All six statuses are handled: `TRANSIT`, `PENDING`, `REJECTED`, `CANCELLED`, `TRADED`, `EXPIRED`.

### Subscribing to order events programmatically

```python
from src.webhooks.handler import OrderStatus, WebhookHandler

handler = WebhookHandler()

# Subscribe to specific status
handler.subscribe(OrderStatus.TRADED, lambda update: print(f"Filled: {update.order_id}"))

# Catch-all
handler.subscribe_all(lambda update: print(f"{update.order_status}: {update.order_id}"))
```

---

## Running Tests

```bash
python -m pytest tests/ -v
```

---

## Configuration Reference

The full config file (`config/default.yaml`) is self-documented. Every parameter has a comment explaining its purpose. You can create multiple config files for different instruments:

```bash
python run_backtest.py --config config/banknifty.yaml
python run_live.py --config config/nifty_options.yaml
```

---

## Project Structure

```
dhan/
├── run_backtest.py         Backtest entry point
├── run_live.py             Live/paper trading entry point
├── config/
│   └── default.yaml        Master configuration
├── src/
│   ├── core/
│   │   ├── config.py       Dataclass-based config loader
│   │   ├── constants.py    Enums and mappings
│   │   └── logger.py       Color console + file logging
│   ├── data/
│   │   ├── dhan_client.py  Dhan API wrapper with rate limiting
│   │   └── market_data.py  Candle management & resampling
│   ├── indicators/
│   │   ├── ema.py          EMA calculations & crossover detection
│   │   ├── atr.py          ATR, swing points, sideways filter
│   │   └── volume.py       Volume analysis
│   ├── strategy/
│   │   ├── base.py         Abstract strategy interface
│   │   └── ema_strategy.py Full EMA strategy implementation
│   ├── execution/
│   │   ├── order_manager.py  Order placement (live + paper)
│   │   └── position_manager.py  Position tracking & trailing SL
│   ├── risk/
│   │   └── risk_manager.py Risk rules & kill switch
│   ├── backtest/
│   │   ├── engine.py       Event-driven backtesting engine
│   │   └── report.py       Analytics, reporting, CSV export
│   ├── live/
│   │   └── engine.py       Real-time trading loop + webhook integration
│   ├── webhooks/
│   │   ├── handler.py      Postback payload parser, dispatcher, dedup
│   │   └── server.py       HTTP server for Dhan postback receiver
│   └── notifications/
│       └── telegram.py     Telegram bot integration + order alerts
├── tools/
│   └── generate_sample_data.py  Synthetic data generator
├── tests/
│   ├── test_strategy.py    Strategy & indicator tests
│   └── test_webhook.py     Webhook handler & server tests
├── requirements.txt
├── .env.example
└── .gitignore
```

---

## Adding a New Strategy

1. Create a new file in `src/strategy/` inheriting from `BaseStrategy`
2. Implement: `name()`, `compute_indicators()`, `generate_signal()`, `compute_stop_loss()`, `compute_target()`
3. Import and use in `run_backtest.py` or `run_live.py`

---

## Important Notes

- This system avoids overtrading via max daily trades and single-position rules
- Duplicate orders are prevented by the position manager's state check
- API rate limits are handled with built-in throttling (350ms between calls)
- All signals are deterministic and reproducible for backtesting
- Candle close confirmation prevents fake breakout entries
- Webhook postbacks provide real-time order fill confirmation and rejection handling
- Duplicate postback updates are automatically suppressed by the webhook handler
