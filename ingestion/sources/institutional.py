import logging
from datetime import datetime, timezone

import yfinance as yf
from psycopg2.extras import execute_values

from config import get_all_symbols
from db import get_connection

logger = logging.getLogger(__name__)

INSERT_OWNERSHIP_SQL = """
    INSERT INTO institutional_ownership
        (fetched_at, symbol, holder, shares, value, pct_held, pct_change, date_reported)
    VALUES %s
    ON CONFLICT (symbol, holder, date_reported) DO UPDATE SET
        shares     = EXCLUDED.shares,
        value      = EXCLUDED.value,
        pct_held   = EXCLUDED.pct_held,
        pct_change = EXCLUDED.pct_change,
        fetched_at = EXCLUDED.fetched_at
"""

INSERT_FUNDAMENTALS_SQL = """
    INSERT INTO fundamentals (time, symbol, metric, value, period, source)
    VALUES %s
    ON CONFLICT (time, symbol, metric, period, source) DO NOTHING
"""

# major_holders row index → fundamentals metric name
_SUMMARY_MAP = {
    "insidersPercentHeld":        "insiders_pct_held",
    "institutionsPercentHeld":    "institutions_pct_held",
    "institutionsFloatPercentHeld": "institutions_float_pct_held",
    "institutionsCount":          "institutions_count",
}


def run(config: dict):
    stocks, _ = get_all_symbols()
    now = datetime.now(timezone.utc)

    conn = get_connection()
    try:
        for symbol in stocks:
            try:
                ticker = yf.Ticker(symbol)
                ownership_rows = []
                fund_rows      = []

                # Top institutional holders from 13-F filings
                inst_df = ticker.institutional_holders
                if inst_df is not None and not inst_df.empty:
                    for _, row in inst_df.iterrows():
                        holder = row.get("Holder")
                        if not holder:
                            continue

                        date_rep = row.get("Date Reported")
                        if hasattr(date_rep, "date"):
                            date_rep = date_rep.date()
                        elif date_rep is None:
                            date_rep = now.date()

                        shares     = row.get("Shares")
                        value      = row.get("Value")
                        pct_held   = row.get("pctHeld")
                        pct_change = row.get("pctChange")

                        ownership_rows.append((
                            now,
                            symbol,
                            str(holder),
                            int(shares)     if shares is not None     else None,
                            float(value)    if value is not None       else None,
                            float(pct_held) if pct_held is not None    else None,
                            float(pct_change) if pct_change is not None else None,
                            date_rep,
                        ))

                # Summary ownership stats → fundamentals table
                try:
                    mh = ticker.major_holders
                    if mh is not None and not mh.empty:
                        for idx_name, metric in _SUMMARY_MAP.items():
                            if idx_name in mh.index:
                                try:
                                    val = float(mh.loc[idx_name].values[0])
                                    fund_rows.append((now, symbol, metric, val, "latest", "yfinance"))
                                except (ValueError, TypeError):
                                    pass
                except Exception as e:
                    logger.debug(f"[institutional] major_holders unavailable for {symbol}: {e}")

                with conn:
                    with conn.cursor() as cur:
                        if ownership_rows:
                            execute_values(cur, INSERT_OWNERSHIP_SQL, ownership_rows)
                        if fund_rows:
                            execute_values(cur, INSERT_FUNDAMENTALS_SQL, fund_rows)

                logger.info(
                    f"[institutional] {symbol}: {len(ownership_rows)} holders, "
                    f"{len(fund_rows)} summary metrics"
                )

            except Exception as e:
                logger.error(f"[institutional] {symbol}: {e}")
    finally:
        conn.close()
