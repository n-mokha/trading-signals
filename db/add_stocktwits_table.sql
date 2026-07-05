-- Run this against an existing DB to add StockTwits sentiment support.
-- Safe to run multiple times (all statements are idempotent).

CREATE TABLE IF NOT EXISTS stocktwits_sentiment (
    time            TIMESTAMPTZ      NOT NULL,
    symbol          TEXT             NOT NULL,
    message_count   INTEGER,
    bullish_count   INTEGER,
    bearish_count   INTEGER,
    avg_sentiment   DOUBLE PRECISION          -- (bullish - bearish) / total_messages, range [-1, 1]
);

SELECT create_hypertable('stocktwits_sentiment', 'time', if_not_exists => TRUE);
CREATE UNIQUE INDEX IF NOT EXISTS stocktwits_sentiment_uq  ON stocktwits_sentiment (time, symbol);
CREATE INDEX        IF NOT EXISTS stocktwits_symbol_idx    ON stocktwits_sentiment (symbol, time DESC);
