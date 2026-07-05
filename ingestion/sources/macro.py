import os
import logging
from datetime import datetime, timezone

import requests
from psycopg2.extras import execute_values

from db import get_connection

logger = logging.getLogger(__name__)
FRED_BASE = "https://api.stlouisfed.org/fred"

INSERT_SQL = """
    INSERT INTO macro_indicators (time, series_id, indicator_name, value, unit, source)
    VALUES %s
    ON CONFLICT (time, series_id) DO NOTHING
"""


def _fetch_series(series_id: str, name: str, api_key: str, limit: int = 5) -> list[tuple]:
    resp = requests.get(
        f"{FRED_BASE}/series/observations",
        params={
            "series_id":  series_id,
            "api_key":    api_key,
            "file_type":  "json",
            "limit":      limit,
            "sort_order": "desc",
        },
        timeout=15,
    )
    resp.raise_for_status()

    rows = []
    for obs in resp.json().get("observations", []):
        if obs["value"] == ".":  # FRED uses "." for missing values
            continue
        ts = datetime.strptime(obs["date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        rows.append((ts, series_id, name, float(obs["value"]), None, "FRED"))
    return rows


def run(config: dict):
    api_key = os.getenv("FRED_API_KEY")
    if not api_key:
        logger.warning("[macro] FRED_API_KEY not set — skipping")
        return

    series_map: dict[str, str] = config.get("series", {})
    rows = []

    for series_id, name in series_map.items():
        try:
            rows.extend(_fetch_series(series_id, name, api_key))
            logger.debug(f"[macro] fetched {series_id}")
        except Exception as e:
            logger.error(f"[macro] {series_id}: {e}")

    if not rows:
        return

    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                execute_values(cur, INSERT_SQL, rows)
        logger.info(f"[macro] saved {len(rows)} indicator rows")
    finally:
        conn.close()
