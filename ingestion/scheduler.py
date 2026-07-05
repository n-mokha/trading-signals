import logging
from datetime import datetime, timezone

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

from config import load_sources
from sources import fundamentals, institutional, macro, price, reddit, sec_filings, stocktwits

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Maps source name in sources.yaml → the module that handles it
SOURCE_MODULES = {
    "price_yfinance":    price,
    "price_polygon":     price,
    "fundamentals_fmp":  fundamentals,
    "sec_filings":       sec_filings,
    "stocktwits":        stocktwits,
    "reddit":            reddit,
    "macro_fred":        macro,
    "institutional":     institutional,
}


def _make_job(module, config: dict, name: str):
    def job():
        try:
            logger.info(f"[scheduler] running {name}")
            module.run(config)
        except Exception as e:
            logger.error(f"[scheduler] {name} failed: {e}")
    job.__name__ = name
    return job


def main():
    sources = load_sources().get("sources", {})
    scheduler = BlockingScheduler(timezone="UTC")

    for source_name, config in sources.items():
        if not config.get("enabled", False):
            logger.info(f"[scheduler] {source_name} is disabled — skipping")
            continue

        module = SOURCE_MODULES.get(source_name)
        if module is None:
            logger.warning(f"[scheduler] no module for source '{source_name}' — skipping")
            continue

        interval = config.get("interval_seconds", 3600)
        scheduler.add_job(
            _make_job(module, config, source_name),
            trigger=IntervalTrigger(seconds=interval),
            id=source_name,
            name=source_name,
            next_run_time=datetime.now(timezone.utc),  # run immediately on startup
        )
        logger.info(f"[scheduler] {source_name} scheduled every {interval}s")

    logger.info("[scheduler] starting — press Ctrl+C to stop")
    scheduler.start()


if __name__ == "__main__":
    main()
