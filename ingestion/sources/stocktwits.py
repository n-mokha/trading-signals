import logging
import time
from datetime import datetime, timezone

import requests
from psycopg2.extras import execute_values

from config import get_all_symbols
from db import get_connection

logger = logging.getLogger(__name__)

# StockTwits uses .X suffix for crypto
_SYMBOL_MAP = {
    "BTC-USD": "BTC.X",
    "ETH-USD": "ETH.X",
    "SOL-USD": "SOL.X",
    "DOGE-USD": "DOGE.X",
}

INSERT_SQL = """
    INSERT INTO stocktwits_sentiment
        (time, symbol, message_count, bullish_count, bearish_count, avg_sentiment)
    VALUES %s
    ON CONFLICT (time, symbol) DO NOTHING
"""


def _st_symbol(symbol: str) -> str:
    return _SYMBOL_MAP.get(symbol, symbol)


def _fetch(symbol: str, session: requests.Session) -> tuple | None:
    url = f"https://api.stocktwits.com/api/2/streams/symbol/{_st_symbol(symbol)}.json"
    try:
        resp = session.get(url, timeout=10)
        if resp.status_code == 429:
            logger.warning(f"[stocktwits] rate limited — backing off")
            time.sleep(60)
            return None
        if resp.status_code != 200:
            logger.warning(f"[stocktwits] {symbol}: HTTP {resp.status_code}")
            return None

        messages = resp.json().get("messages", [])
        if not messages:
            return None

        def _tag(msg: dict) -> str | None:
            return ((msg.get("entities") or {}).get("sentiment") or {}).get("basic")

        bullish = sum(1 for m in messages if _tag(m) == "Bullish")
        bearish = sum(1 for m in messages if _tag(m) == "Bearish")
        total = len(messages)
        avg = (bullish - bearish) / total  # range [-1, 1]
        return (symbol, total, bullish, bearish, avg)

    except Exception as e:
        logger.error(f"[stocktwits] {symbol}: {e}")
        return None


def run(config: dict):
    stocks, crypto = get_all_symbols()
    session = requests.Session()
    session.headers.update({"User-Agent": "TradingSignals/1.0 (personal research tool)"})

    now = datetime.now(timezone.utc)
    rows = []

    for symbol in stocks + crypto:
        result = _fetch(symbol, session)
        if result:
            sym, total, bullish, bearish, avg = result
            rows.append((now, sym, total, bullish, bearish, avg))
            logger.debug(f"[stocktwits] {sym}: {total} msgs bull={bullish} bear={bearish} avg={avg:.2f}")
        time.sleep(0.5)  # stay well within rate limits

    if not rows:
        logger.info("[stocktwits] no data collected this run")
        return

    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                execute_values(cur, INSERT_SQL, rows)
        logger.info(f"[stocktwits] saved {len(rows)} rows")
    finally:
        conn.close()
