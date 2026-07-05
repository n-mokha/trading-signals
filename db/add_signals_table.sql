-- Run this against your DB if you initialized before Tier 2 was added.
-- New deployments get this automatically via init.sql.

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
CREATE INDEX IF NOT EXISTS signals_symbol_idx ON signals (symbol, time DESC);
