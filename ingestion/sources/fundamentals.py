import os
import logging
from datetime import datetime, timezone, timedelta

import requests
import yfinance as yf
from psycopg2.extras import execute_values

from config import get_all_symbols
from db import get_connection

logger = logging.getLogger(__name__)
FMP_BASE = "https://financialmodelingprep.com/stable"

INSERT_FUNDAMENTALS_SQL = """
    INSERT INTO fundamentals (time, symbol, metric, value, period, source)
    VALUES %s
    ON CONFLICT (time, symbol, metric, period, source) DO NOTHING
"""

INSERT_GRADES_SQL = """
    INSERT INTO analyst_grades (grade_date, symbol, firm, from_grade, to_grade, action, source)
    VALUES %s
    ON CONFLICT (grade_date, symbol, firm, to_grade) DO NOTHING
"""


def _fmp_get(path: str, api_key: str, params: dict = None) -> list | dict:
    p = {"apikey": api_key, **(params or {})}
    resp = requests.get(f"{FMP_BASE}{path}", params=p, timeout=15)
    resp.raise_for_status()
    return resp.json()


def fetch_quote(symbol: str, api_key: str) -> list:
    """Real-time quote — price, MAs, 52-week range."""
    data = _fmp_get("/quote", api_key, {"symbol": symbol})
    if not data:
        return []
    q = data[0]
    now = datetime.now(timezone.utc)
    fields = {
        "price":          q.get("price"),
        "change_pct":     q.get("changePercentage"),
        "market_cap":     q.get("marketCap"),
        "52w_high":       q.get("yearHigh"),
        "52w_low":        q.get("yearLow"),
        "volume":         q.get("volume"),
        "price_avg_50":   q.get("priceAvg50"),
        "price_avg_200":  q.get("priceAvg200"),
        "open":           q.get("open"),
        "previous_close": q.get("previousClose"),
    }
    return [
        (now, symbol, k, float(v), "latest", "fmp")
        for k, v in fields.items()
        if v is not None
    ]


def fetch_profile(symbol: str, api_key: str) -> list:
    """Company profile — beta, DCF intrinsic value."""
    data = _fmp_get("/profile", api_key, {"symbol": symbol})
    if not data:
        return []
    p = data[0]
    now = datetime.now(timezone.utc)
    fields = {
        "beta":      p.get("beta"),
        "dcf_value": p.get("dcf"),
        "dcf_diff":  p.get("dcfDiff"),
    }
    return [
        (now, symbol, k, float(v), "latest", "fmp")
        for k, v in fields.items()
        if v is not None
    ]


def fetch_analyst_ratings(symbol: str, api_key: str) -> list:
    """
    Aggregate analyst counts (Strong Buy / Buy / Hold / Sell / Strong Sell)
    via yfinance recommendations_summary, plus consensus price targets from FMP.
    Returns rows for the fundamentals table.
    """
    now = datetime.now(timezone.utc)
    rows = []

    # Recommendation counts — yfinance aggregates current analyst stance
    try:
        ticker = yf.Ticker(symbol)
        summary = ticker.recommendations_summary
        if summary is not None and not summary.empty:
            current = summary[summary["period"] == "0m"]
            if current.empty:
                current = summary.iloc[[0]]
            r = current.iloc[0]
            counts = {
                "analyst_strong_buy":  float(r.get("strongBuy",  0)),
                "analyst_buy":         float(r.get("buy",        0)),
                "analyst_hold":        float(r.get("hold",       0)),
                "analyst_sell":        float(r.get("sell",       0)),
                "analyst_strong_sell": float(r.get("strongSell", 0)),
            }
            rows += [(now, symbol, k, v, "latest", "yfinance") for k, v in counts.items()]
    except Exception as e:
        logger.warning(f"[fundamentals] analyst counts unavailable for {symbol}: {e}")

    # Consensus price targets from FMP
    try:
        data = _fmp_get("/price-target-consensus", api_key, {"symbol": symbol})
        if data:
            t = data if isinstance(data, dict) else data[0]
            fields = {
                "price_target_high":      t.get("targetHigh"),
                "price_target_low":       t.get("targetLow"),
                "price_target_consensus": t.get("targetConsensus"),
                "price_target_median":    t.get("targetMedian"),
            }
            rows += [
                (now, symbol, k, float(v), "latest", "fmp")
                for k, v in fields.items()
                if v is not None
            ]
    except Exception as e:
        logger.warning(f"[fundamentals] price targets unavailable for {symbol}: {e}")

    return rows


def fetch_analyst_grades(symbol: str) -> list:
    """
    Individual analyst firm grade events (upgrades / downgrades / initiations).
    Pulls the last 180 days from yfinance upgrades_downgrades.
    Returns rows for the analyst_grades table.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=180)
    rows = []
    try:
        df = yf.Ticker(symbol).upgrades_downgrades
        if df is None or df.empty:
            return []
        for grade_date, row in df.iterrows():
            ts = grade_date.to_pydatetime()
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts < cutoff:
                continue
            rows.append((
                ts,
                symbol,
                row.get("Firm"),
                row.get("FromGrade") or None,
                row.get("ToGrade"),
                row.get("Action"),
                "yfinance",
            ))
    except Exception as e:
        logger.warning(f"[fundamentals] analyst grades unavailable for {symbol}: {e}")
    return rows


def run(config: dict):
    api_key = os.getenv("FMP_API_KEY")
    if not api_key:
        logger.warning("[fundamentals] FMP_API_KEY not set — skipping")
        return

    stocks, _ = get_all_symbols()  # FMP covers stocks only; skip crypto
    fetch_ratings = config.get("fetch_analyst_ratings", False)
    fundamental_rows = []
    grade_rows = []

    for symbol in stocks:
        # FMP quote/profile may 402 for small caps — catch per call so yfinance still runs
        for fetcher in (fetch_quote, fetch_profile):
            try:
                fundamental_rows.extend(fetcher(symbol, api_key))
            except Exception as e:
                logger.warning(f"[fundamentals] {fetcher.__name__} skipped for {symbol}: {e}")

        if fetch_ratings:
            try:
                fundamental_rows.extend(fetch_analyst_ratings(symbol, api_key))
                grade_rows.extend(fetch_analyst_grades(symbol))
            except Exception as e:
                logger.error(f"[fundamentals] ratings/grades {symbol}: {e}")

        logger.info(f"[fundamentals] fetched {symbol}")

    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                if fundamental_rows:
                    execute_values(cur, INSERT_FUNDAMENTALS_SQL, fundamental_rows)
                if grade_rows:
                    execute_values(cur, INSERT_GRADES_SQL, grade_rows)
        logger.info(
            f"[fundamentals] saved {len(fundamental_rows)} fundamental rows, "
            f"{len(grade_rows)} grade events"
        )
    finally:
        conn.close()
