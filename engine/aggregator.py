import logging
from datetime import datetime, timezone

from config import get_all_symbols
from db import get_connection
from scorer import (
    score_price, score_fundamental,
    score_insider, score_sentiment, get_macro_modifier,
)

logger = logging.getLogger(__name__)

_DEFAULT_WEIGHTS = {
    'price': 0.40, 'fundamental': 0.30, 'insider': 0.10, 'sentiment': 0.20,
}

INSERT_SQL = """
    INSERT INTO signals
        (time, symbol, price_score, fundamental_score, insider_score,
         congressional_score, sentiment_score, macro_modifier, composite_score, signal_version)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (time, symbol, signal_version) DO UPDATE SET
        price_score         = EXCLUDED.price_score,
        fundamental_score   = EXCLUDED.fundamental_score,
        insider_score       = EXCLUDED.insider_score,
        congressional_score = EXCLUDED.congressional_score,
        sentiment_score     = EXCLUDED.sentiment_score,
        macro_modifier      = EXCLUDED.macro_modifier,
        composite_score     = EXCLUDED.composite_score
"""


def _composite_to_100(raw: float, modifier: float) -> float:
    """
    1. Map raw weighted avg [-1, 1] → [0, 100].
    2. Scale toward neutral (50) based on macro modifier.
       High VIX (modifier < 1.0) reduces conviction without flipping direction.
    """
    score_100 = (raw + 1) / 2 * 100
    return round(50 + (score_100 - 50) * modifier, 2)


def run_for_symbol(symbol: str, scoring_cfg: dict, conn):
    lookback  = scoring_cfg.get('lookback', {})
    weights   = scoring_cfg.get('weights', _DEFAULT_WEIGHTS)
    macro_cfg = scoring_cfg.get('macro', {})
    version   = scoring_cfg.get('signal_version', '1.0')

    raw_scores = {
        'price':       score_price(symbol, conn),
        'fundamental': score_fundamental(symbol, conn),
        'insider':     score_insider(symbol, conn, lookback.get('insider_days', 90)),
        'sentiment':   score_sentiment(symbol, conn, lookback.get('sentiment_hours', 24),
                                       scoring_cfg.get('sentiment', {}).get('weights')),
    }

    active = {k: s for k, s in raw_scores.items() if s is not None}
    if not active:
        logger.warning(f"[aggregator] {symbol}: no signal data — skipping")
        return

    # Renormalize weights to only active signals
    total_w = sum(weights.get(k, _DEFAULT_WEIGHTS[k]) for k in active)
    composite_raw = sum(s * weights.get(k, _DEFAULT_WEIGHTS[k]) for k, s in active.items()) / total_w

    modifier = get_macro_modifier(
        conn,
        vix_low=macro_cfg.get('vix_thresholds', {}).get('low', 15.0),
        vix_high=macro_cfg.get('vix_thresholds', {}).get('high', 30.0),
        max_dampening=macro_cfg.get('max_dampening', 0.25),
    )

    composite = _composite_to_100(composite_raw, modifier)

    # Bucket time to nearest 15-min interval for clean deduplication
    now = datetime.now(timezone.utc)
    bucket = now.replace(minute=(now.minute // 15) * 15, second=0, microsecond=0)

    with conn:
        with conn.cursor() as cur:
            cur.execute(INSERT_SQL, (
                bucket, symbol,
                raw_scores['price'],
                raw_scores['fundamental'],
                raw_scores['insider'],
                None,   # congressional_score — column kept in schema, no longer populated
                raw_scores['sentiment'],
                modifier,
                composite,
                version,
            ))

    logger.info(
        f"[aggregator] {symbol}: composite={composite:.1f}/100 "
        f"| price={raw_scores['price']} fund={raw_scores['fundamental']} "
        f"insider={raw_scores['insider']} macro_mod={modifier:.2f} "
        f"(active signals: {list(active.keys())})"
    )


def run_all(scoring_cfg: dict):
    stocks, crypto = get_all_symbols()
    conn = get_connection()
    try:
        for symbol in stocks + crypto:
            try:
                run_for_symbol(symbol, scoring_cfg, conn)
            except Exception as e:
                logger.error(f"[aggregator] {symbol}: {e}")
    finally:
        conn.close()
