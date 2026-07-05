-- Migration: add transaction_type to sec_filings for Form 4 buy/sell direction.
-- Run this if you initialized the DB before this column was added.
-- New deployments get it automatically via init.sql.

ALTER TABLE sec_filings ADD COLUMN IF NOT EXISTS transaction_type TEXT;
