# Trading Signals — Dashboard Configuration

This is the source of truth for your Grafana dashboards.
Edit this file to change what you see, then run:

    docker compose restart grafana

Grafana picks up the change within a few seconds — no rebuild needed.

---

## Dashboard: Analyst Recommendations
uid: analyst-recommendations
refresh: 1h
default_time_range: last 7 days
tags: [analyst, stocks]
description: >
  Wall Street analyst recommendations and price targets for each stock.
  Data comes from Financial Modeling Prep (FMP), refreshed every hour.
  Stocks only — crypto has no analyst coverage.

---

### Panel 1 — Consensus Recommendation (per symbol)
type: stat
position: row 1, spans full width (split into one tile per symbol)
symbols: [NVDA, AMD]
value: dominant recommendation (buy / hold / sell)
logic: >
  If (strong_buy + buy) > (hold + sell + strong_sell) → BUY
  If hold > all others combined → HOLD
  Otherwise → SELL
text_size: large
colors:
  BUY:  green  (#1a9641)
  HOLD: yellow (#f4a736)
  SELL: red    (#d73027)

---

### Panel 2 — Recommendation Breakdown (bar chart)
type: bar-chart
position: row 2, full width
x_axis: symbol
series: [Strong Buy, Buy, Hold, Sell, Strong Sell]
stacking: true
orientation: vertical
colors:
  Strong Buy:   #1a9641
  Buy:          #a6d96a
  Hold:         #f4a736
  Sell:         #f46d43
  Strong Sell:  #d73027
legend: bottom
tooltip: show all series on hover

---

### Panel 3 — Price Targets (table)
type: table
position: row 3, full width
columns:
  - Symbol
  - Current Price    ($ formatted, 2 decimal places)
  - Consensus Target ($ formatted, 2 decimal places)
  - Target High      ($ formatted, 2 decimal places)
  - Target Low       ($ formatted, 2 decimal places)
  - Upside %         (% formatted, 1 decimal place)
sort: Upside % descending
upside_calc: ((consensus_target - current_price) / current_price) * 100
color_thresholds:
  Upside % > 20:  green
  Upside % 0–20:  yellow
  Upside % < 0:   red

---

### Panel 4 — Upgrades & Downgrades (event table)
type: table
position: row 4, full width
description: >
  Every individual analyst firm grade event stored in the DB.
  The time range picker controls how far back you see — default is last 7 days.
  New events appear within 1 hour of ingestion (hourly scheduler).
columns:
  - Date         (the date the analyst published the grade)
  - Symbol
  - Firm         (e.g. Goldman Sachs, Morgan Stanley)
  - From         (previous rating, or — if first coverage)
  - To Grade     (new rating)
  - Action       (color-coded)
action_colors:
  Upgrade:    green  (#1a9641)
  Downgrade:  red    (#d73027)
  Initiation: blue   (#4575b4)
  Maintained: gray   (#636363)
  Reiterated: gray   (#636363)
sort: Date descending
filterable: true (click column headers to filter by symbol or firm)
notes: >
  To see only upgrades, use the Grafana column filter on Action = "Upgrade".
  To change the lookback window, use the time range picker (top right).
  Stored in DB table: analyst_grades (180 days of history kept)

---

## Future Dashboards (add new sections below as needed)

## Dashboard: Composite Signal Scores
(coming — Tier 3)

## Dashboard: Congressional Trades
(coming — Tier 3)

## Dashboard: Insider Activity
(coming — Tier 3)

## Dashboard: Macro Overview
(coming — Tier 3)
