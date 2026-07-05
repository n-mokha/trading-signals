# Trading Signals Tracker

A personal 3-tier trading signals system. Ingests data from multiple sources, aggregates into configurable signals, and delivers alerts + visualization.

---

## Architecture

```
Tier 1  →  Data Sources + Ingestion      (Docker: ingestion + TimescaleDB)
Tier 2  →  Aggregation + Signal Engine   (Docker: engine — runs every 15 min)
Tier 3  →  Alerting + Visualization      (Email, Grafana — coming next)
```

---

## Tier 1 — Active Data Sources

| Source | What it provides | Frequency | Key required |
|---|---|---|---|
| yfinance | OHLCV price data | every 5 min | No |
| Polygon.io | OHLCV price data (more reliable) | every 5 min | Yes — `.env` |
| Financial Modeling Prep (FMP) | Key metrics, analyst ratings | hourly | Yes — `.env` |
| SEC EDGAR | Form 4 insider trades, 8-K filings | hourly | No (free) |
| FRED | Macro: CPI, Fed rate, VIX, unemployment | daily | Yes — `.env` |
| Reddit | WSB/investing sentiment | — | **Disabled** |

---

## Watchlist

Edit `config/watchlist.yaml` to add/remove symbols. No rebuild needed — just restart.

Current: **NVDA, AMD, AAPL, GOOGL, MSFT, IONQ, RGTI, ACHR, AUR, JOBY, QBTS, RKLB** (stocks) · **BTC-USD, ETH-USD** (crypto)

---

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running
- API keys (see below)

---

## First-Time Setup

### 1. Clone / navigate to the project

```bash
cd ~/Desktop/tradingsignals
```

### 2. Set up your API keys

```bash
cp .env.example .env
# Open .env and fill in your keys
```

Keys you need:

| Key | Where to get it |
|---|---|
| `POLYGON_API_KEY` | polygon.io → Dashboard → API Keys |
| `FMP_API_KEY` | financialmodelingprep.com → Dashboard |
| `FRED_API_KEY` | fred.stlouisfed.org/docs/api/api_key.html (free) |
| `DB_PASSWORD` | Set to anything strong — used internally only |

### 3. Build and start

```bash
docker compose up --build
```

First run takes ~2 minutes to pull images and build. All sources run immediately on startup, then on their configured intervals.

---

## Day-to-Day Usage

### Start everything

```bash
docker compose up
```

### Start in background (detached)

```bash
docker compose up -d
```

### View live logs

```bash
docker compose logs -f ingestion   # data ingestion
docker compose logs -f engine      # signal scoring (runs every 15 min)
```

### Stop everything

```bash
docker compose down
```

### Stop and wipe the database (full reset)

```bash
docker compose down -v
```

---

## Email Alerts

Alerts fire when a symbol's composite score crosses a threshold **and changes state** (edge-triggered — no repeat spam on every run).

### Enable

1. Fill in `.env`:
   ```
   ALERT_SMTP_USER=your_gmail@gmail.com
   ALERT_SMTP_PASSWORD=your_app_password   # Gmail: myaccount.google.com/apppasswords
   ALERT_EMAIL_TO=recipient@email.com
   ```
2. In `config/signals.yaml`, set `alerts.enabled: true` and adjust thresholds if needed.
3. `docker compose restart engine`

Default thresholds: **bullish > 70**, **bearish < 30**.

---

## Grafana Dashboards

Open **http://localhost:3000** (default login: admin / admin).

| Dashboard | What it shows |
|---|---|
| Analyst Recommendations | Wall Street ratings, price targets, upgrades/downgrades |
| Composite Signal Scores | Engine output — live scores per symbol, history, breakdown |
| Macro Overview | VIX, Fed rate, CPI, 10Y yield, unemployment, WTI oil |
| Insider Activity | Form 4 insider buy/sell transactions |
| Institutional Ownership | 13-F quarterly holder breakdown |

---

## Changing Config (no rebuild needed)

| What | File | How to apply |
|---|---|---|
| Add/remove symbols | `config/watchlist.yaml` | `docker compose restart ingestion engine` |
| Enable/disable a source | `config/sources.yaml` → `enabled:` | `docker compose restart ingestion` |
| Change poll frequency | `config/sources.yaml` → `interval_seconds:` | `docker compose restart ingestion` |
| Add an API key | `.env` | `docker compose restart ingestion` |
| Change signal weights | `config/signals.yaml` → `weights:` | `docker compose restart engine` |
| Change scoring lookbacks | `config/signals.yaml` → `lookback:` | `docker compose restart engine` |
| Change VIX dampening | `config/signals.yaml` → `macro:` | `docker compose restart engine` |

---

## Query the Database Directly

```bash
# Open a psql shell into TimescaleDB
docker compose exec timescaledb psql -U postgres -d tradingsignals
```

**Tier 1 — Raw data**
```sql
SELECT time, symbol, close FROM price_data ORDER BY time DESC LIMIT 20;
SELECT * FROM macro_indicators ORDER BY time DESC LIMIT 20;
SELECT * FROM sec_filings ORDER BY filed_at DESC LIMIT 10;
SELECT * FROM fundamentals WHERE symbol = 'NVDA' ORDER BY time DESC LIMIT 20;
```

**Tier 2 — Signals**
```sql
-- Latest composite score per symbol
SELECT DISTINCT ON (symbol) symbol, time, composite_score, macro_modifier
FROM signals
ORDER BY symbol, time DESC;

-- Top signals right now (score > 60 = bullish, < 40 = bearish)
SELECT symbol, composite_score, price_score, fundamental_score,
       insider_score, sentiment_score
FROM signals
WHERE time > NOW() - INTERVAL '1 hour'
ORDER BY composite_score DESC;

-- Score history for a symbol (last 24 hours)
SELECT time, composite_score, macro_modifier
FROM signals
WHERE symbol = 'NVDA' AND time > NOW() - INTERVAL '24 hours'
ORDER BY time DESC;
```

---

## Project Roadmap

- [x] **Tier 1** — Data ingestion (5 sources, Dockerized, configurable)
- [x] **Tier 2** — Signal aggregation engine (composite score, configurable weights, VIX dampening)
- [x] **Tier 3** — Email alerting (threshold-triggered, edge-detected) + Grafana dashboards (Analyst Recommendations, Composite Signal Scores, Macro Overview, Insider Activity, Institutional Ownership)
