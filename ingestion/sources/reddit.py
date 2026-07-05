import os
import re
import logging
from collections import defaultdict
from datetime import datetime, timezone

import praw
from psycopg2.extras import execute_values

from config import get_all_symbols
from db import get_connection

logger = logging.getLogger(__name__)

INSERT_SQL = """
    INSERT INTO reddit_sentiment
        (time, symbol, subreddit, post_count, comment_count, mention_count,
         avg_sentiment, bullish_count, bearish_count)
    VALUES %s
    ON CONFLICT (time, symbol, subreddit) DO NOTHING
"""

_BULLISH = re.compile(
    r'\b(bull|bullish|moon|mooning|buy|buying|long|calls?|squeeze|breakout|pump|rally|rocket|upside|upgrade)\b',
    re.IGNORECASE,
)
_BEARISH = re.compile(
    r'\b(bear|bearish|puts?|short|sell|selling|crash|dump|fall|drop|downside|downgrade|bankruptcy)\b',
    re.IGNORECASE,
)


def _sentiment(text: str) -> float:
    b = len(_BULLISH.findall(text))
    r = len(_BEARISH.findall(text))
    total = b + r
    return (b - r) / total if total > 0 else 0.0


def run(config: dict):
    client_id     = os.getenv("REDDIT_CLIENT_ID")
    client_secret = os.getenv("REDDIT_CLIENT_SECRET")
    if not client_id or not client_secret:
        logger.warning("[reddit] REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET not set — skipping")
        return

    stocks, _ = get_all_symbols()
    subreddits = config.get("subreddits", ["wallstreetbets", "investing", "stocks"])
    post_limit = config.get("post_limit", 100)

    pattern = re.compile(r'\b(' + '|'.join(re.escape(s) for s in stocks) + r')\b', re.IGNORECASE)
    reddit = praw.Reddit(
        client_id=client_id,
        client_secret=client_secret,
        user_agent="TradingSignals/1.0 (read-only)",
    )

    # stats[symbol][subreddit] → dict of counts
    stats: dict[str, dict[str, dict]] = defaultdict(lambda: defaultdict(lambda: {
        "posts": 0, "mentions": 0, "sentiment_sum": 0.0, "bullish": 0, "bearish": 0
    }))

    for sub_name in subreddits:
        try:
            subreddit = reddit.subreddit(sub_name)
            for post in subreddit.hot(limit=post_limit):
                text = f"{post.title} {post.selftext}"
                matches = {m.upper() for m in pattern.findall(text)}
                score = _sentiment(text)

                for symbol in matches:
                    s = stats[symbol][sub_name]
                    s["posts"] += 1
                    s["mentions"] += len(re.findall(rf'\b{re.escape(symbol)}\b', text, re.IGNORECASE))
                    s["sentiment_sum"] += score
                    if score > 0.1:
                        s["bullish"] += 1
                    elif score < -0.1:
                        s["bearish"] += 1

            logger.info(f"[reddit] scanned r/{sub_name} ({post_limit} posts)")
        except Exception as e:
            logger.error(f"[reddit] r/{sub_name}: {e}")

    now = datetime.now(timezone.utc)
    rows = []
    for symbol, subs in stats.items():
        for sub_name, s in subs.items():
            avg = s["sentiment_sum"] / s["posts"] if s["posts"] > 0 else 0.0
            rows.append((
                now, symbol, sub_name,
                s["posts"], 0, s["mentions"],
                avg, s["bullish"], s["bearish"],
            ))

    if not rows:
        logger.info("[reddit] no symbol mentions found")
        return

    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                execute_values(cur, INSERT_SQL, rows)
        logger.info(f"[reddit] saved {len(rows)} sentiment rows")
    finally:
        conn.close()
