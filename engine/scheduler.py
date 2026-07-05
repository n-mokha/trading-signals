import logging
from datetime import datetime, timezone

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

from config import load_signals
from aggregator import run_all
import alerter
from db import get_connection

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)


def main():
    cfg = load_signals()
    scoring_cfg = cfg.get('scoring', {})
    alerts_cfg  = cfg.get('alerts', {})
    interval = cfg.get('engine', {}).get('run_interval_seconds', 900)

    def run_cycle():
        run_all(scoring_cfg)
        if alerts_cfg.get('enabled', False):
            conn = get_connection()
            try:
                alerter.run(conn, alerts_cfg)
            except Exception as e:
                logger.error(f"[alerter] {e}")
            finally:
                conn.close()

    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_job(
        run_cycle,
        trigger=IntervalTrigger(seconds=interval),
        id="aggregator",
        name="aggregator",
        next_run_time=datetime.now(timezone.utc),
    )
    logger.info(f"[scheduler] aggregator scheduled every {interval}s")
    logger.info("[scheduler] starting — press Ctrl+C to stop")
    scheduler.start()


if __name__ == "__main__":
    main()
