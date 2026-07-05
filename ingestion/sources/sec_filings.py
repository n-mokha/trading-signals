import logging
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import requests

from config import get_all_symbols, load_sources
from db import get_connection

logger = logging.getLogger(__name__)
EDGAR_BASE = "https://data.sec.gov"
HEADERS = {"User-Agent": "TradingSignals/1.0 contact@tradingsignals.local"}
RATE_SLEEP = 0.15  # 10 req/sec max → sleep 150ms between calls


def _get_cik_map() -> dict[str, str]:
    resp = requests.get(
        "https://www.sec.gov/files/company_tickers.json",
        headers=HEADERS,
        timeout=15,
    )
    resp.raise_for_status()
    return {
        entry["ticker"].upper(): str(entry["cik_str"]).zfill(10)
        for entry in resp.json().values()
    }


def _fetch_recent_filings(cik: str, filing_types: list[str], limit: int) -> list[dict]:
    time.sleep(RATE_SLEEP)
    resp = requests.get(
        f"{EDGAR_BASE}/submissions/CIK{cik}.json",
        headers=HEADERS,
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    recent       = data.get("filings", {}).get("recent", {})
    forms        = recent.get("form", [])
    dates        = recent.get("filingDate", [])
    accessions   = recent.get("accessionNumber", [])
    primary_docs = recent.get("primaryDocument", [])

    results = []
    for i, form in enumerate(forms):
        if form not in filing_types:
            continue
        acc       = accessions[i]
        acc_clean = acc.replace("-", "")
        cik_int   = int(cik)
        filed_at  = datetime.strptime(dates[i], "%Y-%m-%d").replace(tzinfo=timezone.utc)

        entry = {
            "filed_at":         filed_at,
            "filing_type":      form,
            "accession_number": acc,
            "url":              f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_clean}/",
            "description":      f"SEC {form} filing",
            "transaction_type": None,
            "insider_txns":     [],
        }

        if form == "4" and i < len(primary_docs) and primary_docs[i]:
            direction, insider_txns = _fetch_and_parse_form4(
                cik_int, acc_clean, primary_docs[i], filed_at, acc
            )
            entry["transaction_type"] = direction
            entry["insider_txns"]     = insider_txns

        results.append(entry)
        if len(results) >= limit:
            break

    return results


def _fetch_and_parse_form4(
    cik_int: int, acc_clean: str, primary_doc: str, filed_at, accession_number: str
) -> tuple[str | None, list[dict]]:
    # primaryDocument may include an XSLT stylesheet subdirectory prefix
    # (e.g. "xslF345X06/wk-form4_xxx.xml"). Strip any directory prefix so we
    # fetch the raw XML, not the HTML-rendered view.
    raw_doc = primary_doc.split("/")[-1]
    url = (
        f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_clean}/{raw_doc}"
    )
    try:
        time.sleep(RATE_SLEEP)
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        xml_text = resp.text
    except Exception as e:
        logger.debug(f"[sec] could not fetch Form 4 XML ({url}): {e}")
        return None, []

    direction    = _parse_form4_direction(xml_text)
    insider_txns = _parse_form4_transactions(xml_text, filed_at, accession_number)
    return direction, insider_txns


def _parse_form4_direction(xml_text: str) -> str | None:
    """
    Returns net open-market direction: 'buy', 'sell', or None.
    P=purchase adds shares; S/D=sale/disposal subtracts. F/A ignored.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None

    net_shares = 0.0
    for txn in root.findall(".//nonDerivativeTransaction"):
        code_el   = txn.find(".//transactionCode")
        shares_el = txn.find(".//transactionShares/value")
        if code_el is None or shares_el is None:
            continue
        code = (code_el.text or "").strip()
        try:
            shares = float(shares_el.text)
        except (ValueError, TypeError):
            continue
        if code == "P":
            net_shares += shares
        elif code in ("S", "D"):
            net_shares -= shares

    if net_shares > 0:
        return "buy"
    if net_shares < 0:
        return "sell"
    return None


def _parse_form4_transactions(
    xml_text: str, filed_at, accession_number: str
) -> list[dict]:
    """
    Extracts all nonDerivativeTransaction rows with full detail for the
    insider_transactions table. Includes all codes (P, S, D, F, A, etc.).
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    reporter_name_el = root.find(".//rptOwnerName")
    is_director_el   = root.find(".//isDirector")
    is_officer_el    = root.find(".//isOfficer")

    reporter_name = reporter_name_el.text.strip() if reporter_name_el is not None and reporter_name_el.text else None
    is_director   = (is_director_el.text or "0").strip() == "1" if is_director_el is not None else False
    is_officer    = (is_officer_el.text or "0").strip() == "1" if is_officer_el is not None else False

    txns = []
    for txn in root.findall(".//nonDerivativeTransaction"):
        code_el   = txn.find(".//transactionCode")
        shares_el = txn.find(".//transactionShares/value")
        price_el  = txn.find(".//transactionPricePerShare/value")
        date_el   = txn.find(".//transactionDate/value")

        if code_el is None or shares_el is None:
            continue

        code = (code_el.text or "").strip()
        try:
            shares = float(shares_el.text)
        except (ValueError, TypeError):
            continue

        price = None
        if price_el is not None and price_el.text:
            try:
                price = float(price_el.text)
            except (ValueError, TypeError):
                pass

        txn_date = None
        if date_el is not None and date_el.text:
            try:
                txn_date = datetime.strptime(date_el.text.strip(), "%Y-%m-%d").date()
            except ValueError:
                pass

        txns.append({
            "transaction_date": txn_date,
            "filed_at":         filed_at,
            "reporter_name":    reporter_name,
            "is_director":      is_director,
            "is_officer":       is_officer,
            "transaction_code": code,
            "shares":           shares,
            "price_per_share":  price,
            "accession_number": accession_number,
        })

    return txns


def run(config: dict):
    stocks, _ = get_all_symbols()
    filing_types = config.get("filing_types", ["4", "8-K"])
    limit        = config.get("lookback_filings", 50)

    try:
        cik_map = _get_cik_map()
    except Exception as e:
        logger.error(f"[sec] failed to load CIK map: {e}")
        return

    conn = get_connection()
    try:
        for symbol in stocks:
            cik = cik_map.get(symbol.upper())
            if not cik:
                logger.warning(f"[sec] CIK not found for {symbol}")
                continue
            try:
                filings = _fetch_recent_filings(cik, filing_types, limit)
                insider_rows = []
                for f in filings:
                    for it in f.get("insider_txns", []):
                        insider_rows.append((
                            it["transaction_date"],
                            it["filed_at"],
                            symbol,
                            it["reporter_name"],
                            it["is_director"],
                            it["is_officer"],
                            it["transaction_code"],
                            it["shares"],
                            it["price_per_share"],
                            it["accession_number"],
                        ))

                with conn:
                    with conn.cursor() as cur:
                        for f in filings:
                            cur.execute(
                                """
                                INSERT INTO sec_filings
                                    (filed_at, symbol, cik, filing_type, accession_number,
                                     url, description, transaction_type)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                                ON CONFLICT (accession_number) DO UPDATE SET
                                    transaction_type = EXCLUDED.transaction_type
                                """,
                                (
                                    f["filed_at"], symbol, cik,
                                    f["filing_type"], f["accession_number"],
                                    f["url"], f["description"], f["transaction_type"],
                                ),
                            )
                        for row in insider_rows:
                            cur.execute(
                                """
                                INSERT INTO insider_transactions
                                    (transaction_date, filed_at, symbol, reporter_name,
                                     is_director, is_officer, transaction_code,
                                     shares, price_per_share, accession_number)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                                ON CONFLICT (accession_number, transaction_code, shares, transaction_date)
                                DO NOTHING
                                """,
                                row,
                            )

                logger.info(
                    f"[sec] {symbol}: {len(filings)} filings, "
                    f"{len(insider_rows)} insider transaction rows"
                )
            except Exception as e:
                logger.error(f"[sec] {symbol}: {e}")
    finally:
        conn.close()
