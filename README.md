# flow-lens

Options flow signal engine — unusual volume, OI confirmation, directional bias, and dominant strike detection.

Scans the full market daily for option contracts with anomalous volume relative to open interest,
cross-references with an OI change screener to confirm new positions are being held overnight,
aggregates per ticker to detect institutional directional bias, and surfaces the specific
strike + expiry the smart money chose.

Ported and significantly improved from the original C# `ShareRatings` codebase.

---

## What it does

For each trading session, `flow-lens` runs a two-screener pipeline:

1. **Fetches** unusual volume contracts from Barchart (stocks + ETFs)
2. **Fetches** OI change leaders — contracts where open interest grew the most
3. **Filters** aggressively to cut 0DTE noise and retail chatter
4. **Aggregates** per ticker: call/put volume, premium, parity, aggressor side
5. **Confirms** with OI — volume + growing OI in the same direction = new money, not intraday noise
6. **Tracks** multi-day persistence — same bias 3+ days is the strongest signal
7. **Outputs** a clean terminal summary + colour-coded Excel workbook

### Terminal output (default)

```
  flow-lens · 2026-05-29 · 5 stock  1 ETF signals

  STRONG ✓  volume + OI confirmed, 3+ days
  ╭──────────┬────────┬──────────┬──────────┬────────┬─────────┬───────╮
  │ Ticker   │ Type   │   Strike │ Expiry   │ Bias   │ Delta   │   DTE │
  ├──────────┼────────┼──────────┼──────────┼────────┼─────────┼───────┤
  │ MRVL     │ CALL   │      200 │ 26JUN26  │ Long   │ Δ+0.59  │   29d │
  │ PLTR     │ CALL   │      138 │ 05JUN26  │ Long   │ Δ+0.71  │    8d │
  │ BMY      │ PUT    │       62 │ 02JUL26  │ Short  │ Δ-0.73  │   35d │
  ╰──────────┴────────┴──────────┴──────────┴────────┴─────────┴───────╯

  STRONG    volume signal, 3+ days
  ╭──────┬──────┬───────┬─────────┬───────┬────────┬─────╮
  │ MU   │ PUT  │   765 │ 05JUN26 │ Short │ Δ-0.10 │ 8d⚠ │
  ╰──────┴──────┴───────┴─────────┴───────┴────────┴─────╯

  ⚠ far OTM (|Δ| < 0.20) — likely hedge or event play, lower conviction
```

---

## Signal tiers

| Tier | Criteria | Interpretation |
|---|---|---|
| **STRONG ✓** | 3+ days + $1M+ premium + OI confirmed | Highest conviction — new money, held overnight, persistent direction |
| **STRONG** | 3+ days + $1M+ premium | Strong volume signal, OI confirmation pending |
| **WATCH** | 2+ days | Building streak, not yet strong — worth monitoring |

### Reading signals

- **Delta** tells you conviction: Δ±0.70+ = deep ITM, institutional directional bet. Δ±0.10 = far OTM, likely a hedge or event play (flagged ⚠)
- **DTE** tells you timeframe: 7–14d = binary event or short-term move expected. 30–90d = swing thesis. 90d+ = macro positioning
- **OI confirmed (✓)** means the volume wasn't just intraday — contracts were opened and held overnight. This is the single strongest confirmation available from public data

---

## Why the filters are stronger than the original C# code

The original used `volume > 500` and `OI > 100` — fine in 2018. In 2026:

| Problem | Fix |
|---|---|
| 0DTE options always look "unusual" (near-zero OI by definition) | `min_dte = 7` — exclude same-week expiries |
| Retail now accounts for >50% of short-dated volume | `min_vol_oi_ratio = 5.0` — require 5× anomaly |
| Volume screener alone can't distinguish opening from closing trades | Second OI change screener confirms new positions |
| $0.02 × 10,000 contracts = $20K notional — not meaningful | `min_premium_usd = 250,000` |
| Far-OTM contracts are often hedges, not directional bets | Delta flagged ⚠ when \|Δ\| < 0.20 |

---

## Installation

```bash
git clone https://github.com/pranjay/flow-lens.git
cd flow-lens
pip install -r requirements.txt
```

**Barchart auth** (same as `earnings_history`):
Log into barchart.com in Firefox or Safari — cookies load automatically.
Or set env vars:
```bash
export BARCHART_COOKIE="your_cookie_string"
export BARCHART_XSRF_TOKEN="your_token"
```

---

## Usage

```bash
python main.py opt-vol                      # run today's report
python main.py opt-vol --full               # brief output + full signal detail
python main.py opt-vol --date 2026-05-27    # run for a specific date
python main.py opt-vol --debug              # verbose logging
```

Output: `output/YYYY-MM-DD_OptionVolumeLeaders.xlsx`

To reset streaks (rare):
```bash
rm output/persistence_ledger.json output/oi_ledger.json
```

---

## Output workbook (4 sheets)

### Sheets 1 & 3: Raw contracts (Stocks / ETFs)

One row per filtered contract, sorted by volume descending.

| Column | Description |
|---|---|
| Ticker | Underlying stock |
| Type | Call / Put |
| Strike | Strike price |
| Moneyness | ITM / ATM / OTM |
| Delta | Option delta — proxy for probability and conviction |
| Aggressor | Buyer / Seller / Mixed — inferred from last vs bid-ask |
| Expiration | e.g. `20JUN26` |
| DTE | Days to expiration |
| Volume | Contracts traded today |
| Open Interest | Existing open contracts |
| Vol/OI | Anomaly score |
| Premium ($) | `volume × mid × 100` — notional bet size |
| IV | Implied volatility |

### Sheets 2 & 4: Bets summary (Stocks Bets / ETFs Bets) ← main signal sheet

One row per underlying ticker.

| Column | Description |
|---|---|
| Bias | `Long` / `Short` / `Neutral` |
| Signal Strength | `Strong ✓` / `Strong` / `Moderate` / `Weak` |
| Consecutive Days | Sessions with same bias — core conviction metric |
| Parity (Vol) | Call/put volume ratio. `Calls only` or `Puts only` for pure flow |
| Parity (Premium) | Same, weighted by premium — more meaningful than raw volume |
| Buyer Premium ($) | Premium from buyer-initiated trades (aggressor = Buyer) |
| Seller Premium ($) | Premium from seller-initiated trades (closing/writing) |
| Flow Type | `Opening` / `Closing` / `Mixed` — is money entering or exiting? |
| OI Confirmed | ✓ when OI growth direction matches bias |
| OI Call/Put Growth | Net new contracts opened by direction from OI screener |
| OI Top Strike/Expiry | Highest OI-growth contract — the held position |
| Top Strike/Type/Expiry | Dominant volume contract — the biggest bet by premium |
| Top Delta / Aggressor | Conviction and initiation side of the dominant contract |

**Colour coding:**
- 🟡 Gold + Bold = `Strong ✓` (volume + OI confirmed, 3+ days)
- 🟡 Gold = `Strong` (volume, 3+ days)
- 🟢 Green = Long bias
- 🔴 Red = Short bias

---

## Architecture

```
flow-lens/
├── main.py                     CLI entrypoint (opt-vol, --full, --date, --debug)
├── config.py                   All tuneable thresholds
├── models/
│   └── options.py              OptionContract, OIConfirmation, TickerBias, DominantContract
├── data/
│   ├── barchart_client.py      Volume screener HTTP client
│   ├── oi_client.py            OI change screener HTTP client
│   ├── transformer.py          Volume API → OptionContract + quality filters
│   └── oi_transformer.py       OI API → OIConfirmation objects
├── signals/
│   ├── bias_engine.py          Aggregate contracts → TickerBias (aggressor, OI delta)
│   ├── oi_joiner.py            Join OI confirmation onto TickerBias
│   ├── persistence.py          Multi-day streak tracker (re-run safe)
│   └── pipeline.py             Orchestrates all 7 stages
├── reports/
│   ├── brief.py                Terminal summary (tabulate rounded_outline)
│   └── excel_reporter.py       4-sheet colour-coded Excel workbook
└── tests/
    ├── test_pipeline.py        23 unit tests
    └── sample_response.json    Offline sample data
```

### Pipeline stages

```
Fetch volume → Fetch OI → Parse+Filter → Compute signals → Join OI → Persistence → Report
```

1. **Fetch volume** — `BarchartClient` pulls unusual volume contracts (stocks + ETFs)
2. **Fetch OI** — `OIChangeClient` pulls OI change leaders (same session, different ordering)
3. **Parse+Filter** — transformers convert raw dicts, apply quality filters
4. **Compute signals** — `BiasEngine` aggregates per ticker: bias, parity, aggressor breakdown, dominant contract
5. **Join OI** — `OIJoiner` cross-references OI growth direction against volume bias; sets `oi_confirmed`
6. **Persistence** — `PersistenceTracker` stamps consecutive day count (re-run safe — won't double-count same day)
7. **Report** — `brief.py` prints terminal summary; `ExcelReporter` writes workbook

---

## Configuration

```python
@dataclass
class OptionsFilterConfig:
    # Volume screener — API-side
    min_volume:         int   = 5000       # confirmed from live Barchart request
    min_open_interest:  int   = 100
    min_stock_price:    float = 2.00
    exchanges:          tuple = ("AMEX", "NYSE", "NASDAQ", "INDEX-CBOE")
    page_size:          int   = 100        # paginated

    # OI screener — API-side
    min_oi_volume:  int = 500              # wider net than volume screener
    min_oi_change:  int = 1000             # OI must grow by 1000+ contracts

    # Post-fetch quality filters (both screeners)
    min_vol_oi_ratio:  float = 5.0         # 5× anomaly threshold
    min_dte:           int   = 7           # exclude 0DTE noise
    max_dte:           int   = 365
    min_premium_usd:   float = 250_000     # meaningful bets only

    # OI confirmation thresholds
    min_oi_confirmed_contracts: int   = 1000
    oi_confirmation_ratio:      float = 0.65   # 65%+ of OI growth must match bias
```

---

## Running tests

```bash
python -m pytest tests/ -v   # 23 tests, no network required
```

---

## Relationship to `earnings_history`

`flow-lens` uses the same Barchart auth chain as `earnings_history/barchart.py`.
Both tools work from the same browser session — log into barchart.com once, both work.

---

## Disclaimer

For research and educational purposes only. Nothing here constitutes financial advice.
Options trading involves substantial risk of loss.
