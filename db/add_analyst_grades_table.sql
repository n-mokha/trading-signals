-- Migration: add analyst_grades table for individual firm upgrade/downgrade events.
-- Run this if your DB was initialized before this table was added.
-- New deployments get it automatically via init.sql.

CREATE TABLE IF NOT EXISTS analyst_grades (
    id              SERIAL          PRIMARY KEY,
    grade_date      TIMESTAMPTZ     NOT NULL,
    symbol          TEXT            NOT NULL,
    firm            TEXT,
    from_grade      TEXT,
    to_grade        TEXT            NOT NULL,
    action          TEXT,
    source          TEXT            DEFAULT 'yfinance'
);

CREATE UNIQUE INDEX IF NOT EXISTS analyst_grades_uq ON analyst_grades (grade_date, symbol, firm, to_grade);
CREATE INDEX IF NOT EXISTS analyst_grades_symbol_idx ON analyst_grades (symbol, grade_date DESC);
