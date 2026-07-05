-- Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- -----------------------------------------------------------------------
-- Price data (OHLCV) — hypertable partitioned by time
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS price_data (
    time            TIMESTAMPTZ     NOT NULL,
    symbol          TEXT            NOT NULL,
    open            DOUBLE PRECISION,
    high            DOUBLE PRECISION,
    low             DOUBLE PRECISION,
    close           DOUBLE PRECISION,
    volume          BIGINT,
    source          TEXT            NOT NULL,   -- 'yfinance' | 'polygon'
    interval        TEXT            NOT NULL    -- '5m' | '1h' | '1d'
);

SELECT create_hypertable('price_data', 'time', if_not_exists => TRUE);
CREATE UNIQUE INDEX IF NOT EXISTS price_data_uq ON price_data (time, symbol, source, interval);
CREATE INDEX IF NOT EXISTS price_data_symbol_idx ON price_data (symbol, time DESC);

-- -----------------------------------------------------------------------
-- Fundamentals (key metrics, analyst ratings) — hypertable
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fundamentals (
    time            TIMESTAMPTZ     NOT NULL,
    symbol          TEXT            NOT NULL,
    metric          TEXT            NOT NULL,
    value           DOUBLE PRECISION,
    period          TEXT,                       -- 'ttm' | 'annual' | 'quarterly'
    source          TEXT
);

SELECT create_hypertable('fundamentals', 'time', if_not_exists => TRUE);
CREATE UNIQUE INDEX IF NOT EXISTS fundamentals_uq ON fundamentals (time, symbol, metric, period, source);
CREATE INDEX IF NOT EXISTS fundamentals_symbol_idx ON fundamentals (symbol, metric, time DESC);

-- -----------------------------------------------------------------------
-- SEC filings (raw filing index — Form 4, 8-K, 10-K, etc.)
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sec_filings (
    id              SERIAL          PRIMARY KEY,
    filed_at        TIMESTAMPTZ     NOT NULL,
    symbol          TEXT,
    cik             TEXT,
    filing_type     TEXT            NOT NULL,
    accession_number TEXT           UNIQUE,
    url             TEXT,
    description     TEXT,
    transaction_type TEXT                        -- 'buy' | 'sell' | NULL (Form 4 net direction)
);

CREATE INDEX IF NOT EXISTS sec_filings_symbol_idx ON sec_filings (symbol, filed_at DESC);
CREATE INDEX IF NOT EXISTS sec_filings_type_idx   ON sec_filings (filing_type, filed_at DESC);

-- -----------------------------------------------------------------------
-- Congressional trades — hypertable
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS congressional_trades (
    id              SERIAL,
    disclosed_at    TIMESTAMPTZ     NOT NULL,
    transaction_date DATE,
    politician      TEXT            NOT NULL,
    party           TEXT,
    chamber         TEXT,                       -- 'senate' | 'house'
    symbol          TEXT            NOT NULL,
    asset_type      TEXT,
    transaction_type TEXT,                      -- 'buy' | 'sell'
    amount_range    TEXT,                       -- raw string e.g. '$1,001 - $15,000'
    amount_min      DOUBLE PRECISION,
    amount_max      DOUBLE PRECISION,
    source          TEXT
);

SELECT create_hypertable('congressional_trades', 'disclosed_at', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS congressional_symbol_idx ON congressional_trades (symbol, disclosed_at DESC);
CREATE INDEX IF NOT EXISTS congressional_politician_idx ON congressional_trades (politician, disclosed_at DESC);

-- -----------------------------------------------------------------------
-- StockTwits sentiment — hypertable
-- -----------------------------------------------------------------------
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

-- -----------------------------------------------------------------------
-- Reddit sentiment — hypertable
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS reddit_sentiment (
    time            TIMESTAMPTZ     NOT NULL,
    symbol          TEXT            NOT NULL,
    subreddit       TEXT            NOT NULL,
    post_count      INTEGER,
    comment_count   INTEGER,
    mention_count   INTEGER,
    avg_sentiment   DOUBLE PRECISION,           -- -1.0 (bearish) to 1.0 (bullish)
    bullish_count   INTEGER,
    bearish_count   INTEGER
);

SELECT create_hypertable('reddit_sentiment', 'time', if_not_exists => TRUE);
CREATE UNIQUE INDEX IF NOT EXISTS reddit_sentiment_uq ON reddit_sentiment (time, symbol, subreddit);
CREATE INDEX IF NOT EXISTS reddit_sentiment_symbol_idx ON reddit_sentiment (symbol, time DESC);

-- -----------------------------------------------------------------------
-- Macro indicators (FRED series) — hypertable
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS macro_indicators (
    time            TIMESTAMPTZ     NOT NULL,
    series_id       TEXT            NOT NULL,
    indicator_name  TEXT,
    value           DOUBLE PRECISION,
    unit            TEXT,
    source          TEXT            DEFAULT 'FRED'
);

SELECT create_hypertable('macro_indicators', 'time', if_not_exists => TRUE);
CREATE UNIQUE INDEX IF NOT EXISTS macro_indicators_uq ON macro_indicators (time, series_id);
CREATE INDEX IF NOT EXISTS macro_indicators_series_idx ON macro_indicators (series_id, time DESC);

-- -----------------------------------------------------------------------
-- Aggregated signals (Tier 2 output) — hypertable
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS signals (
    time                TIMESTAMPTZ     NOT NULL,
    symbol              TEXT            NOT NULL,
    price_score         DOUBLE PRECISION,
    fundamental_score   DOUBLE PRECISION,
    insider_score       DOUBLE PRECISION,
    congressional_score DOUBLE PRECISION,
    sentiment_score     DOUBLE PRECISION,
    macro_modifier      DOUBLE PRECISION,
    composite_score     DOUBLE PRECISION,
    signal_version      TEXT            DEFAULT '1.0'
);

SELECT create_hypertable('signals', 'time', if_not_exists => TRUE);
CREATE UNIQUE INDEX IF NOT EXISTS signals_uq ON signals (time, symbol, signal_version);

-- -----------------------------------------------------------------------
-- Insider transactions (Form 4 — individual trade detail)
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS insider_transactions (
    id                  SERIAL          PRIMARY KEY,
    transaction_date    DATE,
    filed_at            TIMESTAMPTZ     NOT NULL,
    symbol              TEXT            NOT NULL,
    reporter_name       TEXT,
    is_director         BOOLEAN         DEFAULT false,
    is_officer          BOOLEAN         DEFAULT false,
    transaction_code    TEXT            NOT NULL,   -- P=purchase, S=sale, D=dispose, F=tax, A=award
    shares              DOUBLE PRECISION,
    price_per_share     DOUBLE PRECISION,
    accession_number    TEXT            NOT NULL,
    UNIQUE (accession_number, transaction_code, shares, transaction_date)
);

CREATE INDEX IF NOT EXISTS insider_txn_symbol_idx ON insider_transactions (symbol, filed_at DESC);
CREATE INDEX IF NOT EXISTS insider_txn_code_idx   ON insider_transactions (transaction_code, filed_at DESC);

-- -----------------------------------------------------------------------
-- Institutional ownership (13-F — quarterly holder breakdown)
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS institutional_ownership (
    id                  SERIAL          PRIMARY KEY,
    fetched_at          TIMESTAMPTZ     NOT NULL,
    symbol              TEXT            NOT NULL,
    holder              TEXT            NOT NULL,
    shares              BIGINT,
    value               DOUBLE PRECISION,
    pct_held            DOUBLE PRECISION,
    pct_change          DOUBLE PRECISION,
    date_reported       DATE,
    UNIQUE (symbol, holder, date_reported)
);

CREATE INDEX IF NOT EXISTS inst_own_symbol_idx ON institutional_ownership (symbol, fetched_at DESC);

-- -----------------------------------------------------------------------
-- Analyst grade events (individual firm upgrades / downgrades)
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS analyst_grades (
    id              SERIAL          PRIMARY KEY,
    grade_date      TIMESTAMPTZ     NOT NULL,
    symbol          TEXT            NOT NULL,
    firm            TEXT,
    from_grade      TEXT,
    to_grade        TEXT            NOT NULL,
    action          TEXT,           -- 'up' | 'down' | 'init' | 'main' | 'reit'
    price_target    DOUBLE PRECISION,               -- analyst's new price target (when available)
    source          TEXT            DEFAULT 'yfinance'
);

CREATE UNIQUE INDEX IF NOT EXISTS analyst_grades_uq ON analyst_grades (grade_date, symbol, firm, to_grade);
CREATE INDEX IF NOT EXISTS analyst_grades_symbol_idx ON analyst_grades (symbol, grade_date DESC);
CREATE INDEX IF NOT EXISTS signals_symbol_idx ON signals (symbol, time DESC);
