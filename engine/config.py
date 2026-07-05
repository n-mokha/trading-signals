import yaml
import os
from pathlib import Path

CONFIG_DIR = Path(os.getenv("CONFIG_DIR", "/app/config"))


def load_watchlist() -> dict:
    with open(CONFIG_DIR / "watchlist.yaml") as f:
        return yaml.safe_load(f)


def load_signals() -> dict:
    with open(CONFIG_DIR / "signals.yaml") as f:
        return yaml.safe_load(f)


def get_all_symbols() -> tuple[list[str], list[str]]:
    wl = load_watchlist()["watchlist"]
    stocks = [s["symbol"] for s in wl.get("stocks", [])]
    crypto = [s["symbol"] for s in wl.get("crypto", [])]
    return stocks, crypto
