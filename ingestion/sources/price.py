import os
import logging
from datetime import date, datetime, timezone

import requests
import yfinance as yf
from psycopg2.extras import execute_values

from config import get_all_symbols
from db import get_connection

logger = logging.getLogger(__name__)

INSERT_SQL = """
    INSERT INTO price_data (time, symbol, open, high, low, close, volume, source, interval)
    VALUES %s
    ON CONFLICT (time, symbol, source, interval) DO NOTHING
"""


def _save(rows: list, source: str):
    if not rows:
        return
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                execute_values(cur, INSERT_SQL, rows)
        logger.info(f"[price/{source}] saved {len(rows)} rows")
    finally:
        conn.close()


def fetch_yfinance(symbols: list[str], bar_interval: str = "5m"):
    rows = []
    for symbol in symbols:
        try:
            df = yf.Ticker(symbol).history(period="1d", interval=bar_interval)
            if df.empty:
                logger.warning(f"[yfinance] no data for {symbol}")
                continue
            for ts, row in df.iterrows():
                rows.append((
                    ts.to_pydatetime(),
                    symbol,
                    float(row["Open"]),
                    float(row["High"]),
                    float(row["Low"]),
                    float(row["Close"]),
                    int(row["Volume"]),
                    "yfinance",
                    bar_interval,
                ))
        except Exception as e:
            logger.error(f"[yfinance] {symbol}: {e}")
    _save(rows, "yfinance")


def fetch_polygon(symbols: list[str], bar_interval: str = "5"):
    """
    Free-tier Polygon only supports the previous-close endpoint.
    bar_interval is unused here but kept so the config interface stays consistent.
    """
    api_key = os.getenv("POLYGON_API_KEY")
    if not api_key:
        logger.warning("[polygon] POLYGON_API_KEY not set — skipping")
        return

    rows = []

    for symbol in symbols:
        if symbol.endswith("-USD"):
            polygon_symbol = f"X:{symbol.replace('-USD', '')}USD"
        else:
            polygon_symbol = symbol

        try:
            url = f"https://api.polygon.io/v2/aggs/ticker/{polygon_symbol}/prev"
            resp = requests.get(url, params={"apiKey": api_key}, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            if not data.get("results"):
                logger.warning(f"[polygon] no data for {symbol}")
                continue

            bar = data["results"][0]
            ts = datetime.fromtimestamp(bar["t"] / 1000, tz=timezone.utc)
            rows.append((ts, symbol, bar["o"], bar["h"], bar["l"], bar["c"], int(bar["v"]), "polygon", "1d"))
        except Exception as e:
            logger.error(f"[polygon] {symbol}: {e}")

    _save(rows, "polygon")


def run(config: dict):
    stocks, crypto = get_all_symbols()
    all_symbols = stocks + crypto
    provider = config.get("provider", "yfinance")
    bar_interval = config.get("bar_interval", "5m" if provider == "yfinance" else "5")

    if provider == "yfinance":
        fetch_yfinance(all_symbols, bar_interval)
    elif provider == "polygon":
        fetch_polygon(all_symbols, bar_interval)
    else:
        logger.error(f"[price] unknown provider: {provider}")
