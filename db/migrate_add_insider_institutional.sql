-- Migration: add insider_transactions and institutional_ownership tables
-- Run once against the live database:
--   docker compose exec timescaledb psql -U postgres -d tradingsignals -f /docker-entrypoint-initdb.d/migrate_add_insider_institutional.sql
-- (or paste directly into psql)

CREATE TABLE IF NOT EXISTS insider_transactions (
    id                  SERIAL          PRIMARY KEY,
    transaction_date    DATE,
    filed_at            TIMESTAMPTZ     NOT NULL,
    symbol              TEXT            NOT NULL,
    reporter_name       TEXT,
    is_director         BOOLEAN         DEFAULT false,
    is_officer          BOOLEAN         DEFAULT false,
    transaction_code    TEXT            NOT NULL,
    shares              DOUBLE PRECISION,
    price_per_share     DOUBLE PRECISION,
    accession_number    TEXT            NOT NULL,
    UNIQUE (accession_number, transaction_code, shares, transaction_date)
);

CREATE INDEX IF NOT EXISTS insider_txn_symbol_idx  ON insider_transactions (symbol, filed_at DESC);
CREATE INDEX IF NOT EXISTS insider_txn_code_idx    ON insider_transactions (transaction_code, filed_at DESC);

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
