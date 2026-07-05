import os
import time
import logging
import psycopg2

logger = logging.getLogger(__name__)


def get_connection(retries: int = 5, delay: int = 3):
    """Return a psycopg2 connection, retrying if the DB isn't ready yet."""
    for attempt in range(1, retries + 1):
        try:
            return psycopg2.connect(
                host=os.getenv("DB_HOST", "timescaledb"),
                port=int(os.getenv("DB_PORT", "5432")),
                dbname=os.getenv("DB_NAME", "tradingsignals"),
                user=os.getenv("DB_USER", "postgres"),
                password=os.getenv("DB_PASSWORD"),
            )
        except psycopg2.OperationalError as e:
            if attempt == retries:
                raise
            logger.warning(f"DB not ready (attempt {attempt}/{retries}): {e} — retrying in {delay}s")
            time.sleep(delay)
