import os
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Edge-triggered: only fires when a symbol's state changes (survives within one process lifetime)
_last_state: dict[str, str] = {}


def _classify(score: float, bullish_t: float, bearish_t: float) -> str:
    if score >= bullish_t:
        return "BULLISH"
    if score <= bearish_t:
        return "BEARISH"
    return "NEUTRAL"


def _send_email(subject: str, body: str, alerts_cfg: dict):
    smtp_host = os.getenv("ALERT_SMTP_HOST", alerts_cfg.get("smtp_host", "smtp.gmail.com"))
    smtp_port = int(os.getenv("ALERT_SMTP_PORT", alerts_cfg.get("smtp_port", 587)))
    smtp_user = os.getenv("ALERT_SMTP_USER", "")
    smtp_pass = os.getenv("ALERT_SMTP_PASSWORD", "")
    to_addr   = os.getenv("ALERT_EMAIL_TO", "")

    if not smtp_user or not smtp_pass or not to_addr:
        logger.warning("[alerter] SMTP credentials not set — alert skipped (set ALERT_SMTP_USER, ALERT_SMTP_PASSWORD, ALERT_EMAIL_TO)")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = smtp_user
    msg["To"]      = to_addr
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.ehlo()
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, to_addr, msg.as_string())
        logger.info(f"[alerter] email sent — {subject}")
    except Exception as e:
        logger.error(f"[alerter] email failed: {e}")


def run(conn, alerts_cfg: dict):
    if not alerts_cfg.get("enabled", False):
        return

    bullish_t = float(alerts_cfg.get("bullish_threshold", 70))
    bearish_t = float(alerts_cfg.get("bearish_threshold", 30))

    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT ON (symbol) symbol, composite_score, time
            FROM signals
            ORDER BY symbol, time DESC
        """)
        rows = cur.fetchall()

    triggered = []
    for symbol, score, ts in rows:
        if score is None:
            continue
        new_state = _classify(score, bullish_t, bearish_t)
        old_state = _last_state.get(symbol)

        if old_state is None:
            # First run after start — record state without alerting to avoid restart spam
            _last_state[symbol] = new_state
            continue

        if new_state != old_state:
            _last_state[symbol] = new_state
            if new_state != "NEUTRAL":
                triggered.append((symbol, score, new_state, old_state))

    if not triggered:
        return

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"Trading Signal Alerts — {now_str}", ""]
    for symbol, score, new_state, old_state in triggered:
        icon = "BULLISH  >>>" if new_state == "BULLISH" else "BEARISH  <<<"
        lines.append(f"  {icon}  {symbol}: {old_state} -> {new_state}  (score: {score:.1f}/100)")
    lines += [
        "",
        f"Thresholds:  bullish > {bullish_t}  |  bearish < {bearish_t}",
        "View full scores in Grafana: http://localhost:3000",
    ]

    subject = (
        "[TradingSignals] "
        + ", ".join(f"{sym} {st}" for sym, _, st, _ in triggered)
    )
    _send_email(subject, "\n".join(lines), alerts_cfg)
