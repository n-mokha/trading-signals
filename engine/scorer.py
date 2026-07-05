import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)


def _clamp(value: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def score_price(symbol: str, conn) -> float | None:
    """
    MA50/MA200 golden-cross + 52-week price position.
    Computed directly from price_data table (yfinance/Polygon OHLCV — free, always available).
    No FMP dependency. Returns [-1, 1] or None if fewer than 50 daily closes exist.
    """
    with conn.cursor() as cur:
        cur.execute("""
            WITH daily AS (
                SELECT
                    time_bucket('1 day', time) AS day,
                    LAST(close, time)           AS close
                FROM price_data
                WHERE symbol = %s
                  AND time > NOW() - INTERVAL '252 days'
                  AND close IS NOT NULL
                GROUP BY 1
            ),
            ranked AS (
                SELECT close, ROW_NUMBER() OVER (ORDER BY day DESC) AS rn
                FROM daily
            )
            SELECT
                AVG(close) FILTER (WHERE rn <= 50)  AS ma50,
                AVG(close) FILTER (WHERE rn <= 200) AS ma200,
                MAX(close)                           AS high_52w,
                MIN(close)                           AS low_52w,
                MAX(close) FILTER (WHERE rn = 1)    AS price
            FROM ranked
        """, (symbol,))
        row = cur.fetchone()

    if not row or row[0] is None or row[1] is None or float(row[1]) == 0:
        return None

    ma50, ma200, high, low, price = (float(v) if v is not None else None for v in row)

    # How far MA50 is above/below MA200 (×10 so ±10% spread → ±1.0)
    ma_signal = _clamp((ma50 - ma200) / ma200 * 10)

    if high and low and price and high > low:
        pos_signal = ((price - low) / (high - low) - 0.5) * 2
        return _clamp(0.6 * ma_signal + 0.4 * pos_signal)

    return ma_signal


def score_fundamental(symbol: str, conn) -> float | None:
    """
    DCF undervaluation: dcf_diff = intrinsic_value - price.
    Positive → undervalued → bullish. Normalised as % of price (×5 so 20% gap → 1.0).
    Price falls back to price_data table when FMP quote is unavailable (e.g. 402 on free tier).
    Returns [-1, 1] or None if DCF data is unavailable.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=2)
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT ON (metric) metric, value
            FROM fundamentals
            WHERE symbol = %s
              AND metric IN ('dcf_diff', 'price')
              AND time > %s
            ORDER BY metric, time DESC
        """, (symbol, cutoff))
        metrics = {row[0]: row[1] for row in cur.fetchall()}

    dcf_diff = metrics.get('dcf_diff')
    price    = metrics.get('price')

    if price is None:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT close FROM price_data
                WHERE symbol = %s AND close IS NOT NULL
                ORDER BY time DESC LIMIT 1
            """, (symbol,))
            r = cur.fetchone()
        if r:
            price = float(r[0])

    if dcf_diff is None or not price:
        return None

    return _clamp(dcf_diff / price * 5)



def score_insider(symbol: str, conn, lookback_days: int = 90) -> float | None:
    """
    Dollar-value-weighted open-market insider buy vs sell from Form 4 (insider_transactions table).
    P=purchase → bullish; S/D=sale/disposal → bearish. F/A (RSU/award) excluded.
    Returns [-1, 1] or None if no open-market transactions in the lookback window.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    with conn.cursor() as cur:
        cur.execute("""
            SELECT transaction_code,
                   SUM(shares * COALESCE(price_per_share, 0)) AS dollar_value
            FROM insider_transactions
            WHERE symbol = %s
              AND filed_at > %s
              AND transaction_code IN ('P', 'S', 'D')
            GROUP BY transaction_code
        """, (symbol, cutoff))
        rows = cur.fetchall()

    if not rows:
        return None

    values   = {code: float(v) for code, v in rows}
    buy_val  = values.get('P', 0.0)
    sell_val = values.get('S', 0.0) + values.get('D', 0.0)
    total    = buy_val + sell_val

    if not total:
        return None

    return _clamp((buy_val - sell_val) / total)


_DEFAULT_SENTIMENT_WEIGHTS = {'reddit': 0.4, 'stocktwits': 0.6}


def score_sentiment(symbol: str, conn, lookback_hours: int = 24, sentiment_weights: dict | None = None) -> float | None:
    """
    Weighted combination of Reddit and StockTwits sentiment → [-1, 1].
    StockTwits uses explicit Bullish/Bearish user tags (higher quality signal).
    Reddit uses keyword-based heuristic scoring.
    Returns None only if both sources have no data in the lookback window.
    """
    weights = sentiment_weights or _DEFAULT_SENTIMENT_WEIGHTS
    cutoff  = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    scores: dict[str, float] = {}

    # Reddit (keyword heuristic, mention-count weighted)
    if weights.get('reddit', 0) > 0:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT avg_sentiment, COALESCE(mention_count, 1)
                FROM reddit_sentiment
                WHERE symbol = %s AND time > %s
            """, (symbol, cutoff))
            rows = cur.fetchall()
        if rows:
            total_w = sum(float(w) for _, w in rows)
            if total_w > 0:
                scores['reddit'] = _clamp(sum(float(s) * float(w) for s, w in rows) / total_w)

    # StockTwits (explicit user-tagged Bullish / Bearish)
    if weights.get('stocktwits', 0) > 0:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT avg_sentiment, message_count
                FROM stocktwits_sentiment
                WHERE symbol = %s AND time > %s
                ORDER BY time DESC
                LIMIT 1
            """, (symbol, cutoff))
            row = cur.fetchone()
        if row and row[1]:
            scores['stocktwits'] = _clamp(float(row[0]))

    if not scores:
        return None

    total_w = sum(weights.get(k, 0) for k in scores)
    if not total_w:
        return None

    return _clamp(sum(s * weights.get(k, 0) for k, s in scores.items()) / total_w)


def get_macro_modifier(conn, vix_low: float = 15.0, vix_high: float = 30.0, max_dampening: float = 0.25) -> float:
    """
    VIX-based risk-off modifier in [1 - max_dampening, 1.0].
    Applied by scaling the composite score toward neutral (50) — high VIX reduces
    conviction in all signals without flipping their direction.
    Returns 1.0 (no dampening) if VIX data is unavailable.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT value FROM macro_indicators
            WHERE series_id = 'VIXCLS'
            ORDER BY time DESC LIMIT 1
        """)
        row = cur.fetchone()

    if not row:
        return 1.0

    vix = float(row[0])
    if vix <= vix_low:
        return 1.0
    if vix >= vix_high:
        return 1.0 - max_dampening
    return 1.0 - (vix - vix_low) / (vix_high - vix_low) * max_dampening
