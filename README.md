# flow-lens

Options flow signal engine — unusual volume, directional bias, and dominant strike detection.

Scans the full market daily for option contracts with anomalous volume relative to open interest,
aggregates them per underlying ticker to detect institutional directional bias, and surfaces
the single highest-premium contract (the specific strike + expiry the smart money chose).

Ported and significantly improved from the original C# `ShareRatings` codebase.

---

## What it does

For each trading session, `flow-lens`:

1. **Fetches** all options contracts with unusual volume from Barchart (stocks + ETFs separately)
2. **Filters** aggressively to cut 0DTE noise and retail chatter
3. **Aggregates** per ticker: total call/put volume, premium, call/put parity ratio
4. **Identifies** the dominant contract — the specific strike/expiry carrying the most premium
5. **Tracks** multi-day persistence — tickers with the same directional bias 2+ days running carry far more conviction
6. **Outputs** a colour-coded Excel workbook with four sheets

### Example signal output

```
NVDA | Long | Parity: 5.6 | Premium: $51M | Strength: Strong | Days: 3
  Top: NVDA 160.0C 20JUN25 | Premium: $39.6M | Vol/OI: 10.7x | DTE: 24
```

---

## Why the filters are stronger than the original

The original C# code used `volume > 500` and `OI > 100` as the only filters —
equivalent to Barchart's own Vol/OI ratio threshold of ~1x. That was fine in 2018.
In 2026 it captures too much noise:

| Problem | Fix |
|---|---|
| 0DTE options have near-zero OI by definition — always look "unusual" | `min_dte = 7` excludes same-week expiries |
| Retail now accounts for >50% of short-dated volume | `min_vol_oi_ratio = 5.0` — only 5× spikes |
| $0.02 contract with 10,000 vol looks loud but is $20K notional | `min_premium_usd = 250_000` |

---

## Installation

```bash
git clone https://github.com/pranjay/flow-lens.git
cd flow-lens
pip install -r requirements.txt
```

**Barchart auth** (same as `earnings_history`):
Log into barchart.com in Firefox or Safari. Cookies are loaded automatically —
no configuration needed. Or set env vars:
```bash
export BARCHART_COOKIE="your_cookie_string"
export BARCHART_XSRF_TOKEN="your_token"
```

---

## Usage

```bash
python main.py opt-vol           # run the report
python main.py opt-vol --debug   # verbose logging
```

Output: `output/YYYY-MM-DD_OptionVolumeLeaders.xlsx`

---

## Output workbook (4 sheets)

### Sheet 1 & 3: Raw contracts (Stocks / ETFs)

One row per filtered option contract, sorted by volume descending.

| Column | Description |
|---|---|
| Ticker | Underlying stock |
| Type | Call / Put |
| Strike | Strike price |
| Expiration | Formatted date (e.g. `20JUN25`) |
| DTE | Days to expiration |
| Bid / Ask / Last | Option pricing |
| Volume | Contracts traded today |
| Open Interest | Existing open contracts |
| Vol/OI Ratio | The anomaly score — higher = more unusual |
| Premium ($) | `volume × last × 100` — notional bet size |
| Volatility | Implied volatility |
| Underlying $ | Stock's current price |

### Sheet 2 & 4: Bets summary (Stocks Bets / ETFs Bets) ← main signal sheet

One row per underlying ticker, colour-coded by bias.

| Column | Description |
|---|---|
| Ticker | Underlying stock |
| Bias | `Long` / `Short` / `Neutral` |
| Signal Strength | `Strong` / `Moderate` / `Weak` |
| Consecutive Days | How many sessions this bias has persisted |
| Parity (Vol) | Call volume / Put volume ratio |
| Parity (Premium) | Call premium / Put premium — premium-weighted conviction |
| Total Premium ($) | Total notional across all contracts |
| Top Strike / Type / Expiry / DTE | The dominant contract — highest premium contract |
| Top Premium ($) | Premium size of the dominant contract |
| Top Vol/OI | Anomaly score of the dominant contract |

**Colour coding:**
- 🟡 Gold = Strong signal (3+ consecutive days + $1M+ premium)
- 🟢 Green = Long bias
- 🔴 Red = Short bias

---

## Architecture

```
flow-lens/
├── main.py                     CLI entrypoint
├── config.py                   All tuneable thresholds
├── models/
│   └── options.py              OptionContract, TickerBias, DominantContract dataclasses
├── data/
│   ├── barchart_client.py      HTTP client (same auth as earnings_history)
│   └── transformer.py          Raw API dict → typed OptionContract + quality filters
├── signals/
│   ├── bias_engine.py          Aggregate contracts → per-ticker TickerBias
│   ├── persistence.py          Multi-day streak tracker (JSON ledger)
│   └── pipeline.py             Orchestrates all 5 stages
├── reports/
│   └── excel_reporter.py       4-sheet colour-coded Excel workbook
└── tests/
    ├── test_pipeline.py        20 unit tests (transformer, engine, persistence, signals)
    └── sample_response.json    Offline sample data for testing
```

### Pipeline stages

```
Fetch → Parse+Filter → Aggregate → Persistence → Excel
```

1. **Fetch** — `BarchartClient` pulls raw JSON (stocks + ETFs)
2. **Parse+Filter** — `OptionsTransformer` converts to typed objects, applies quality filters
3. **Aggregate** — `BiasEngine` computes per-ticker bias, parity, dominant contract
4. **Persistence** — `PersistenceTracker` stamps consecutive day count (JSON ledger)
5. **Report** — `ExcelReporter` writes the 4-sheet workbook

---

## Configuration

All thresholds live in `config.py`:

```python
@dataclass
class OptionsFilterConfig:
    min_volume:        int   = 500        # API-side filter
    min_open_interest: int   = 100        # API-side filter
    min_vol_oi_ratio:  float = 5.0        # post-fetch: exclude weak signals
    min_dte:           int   = 7          # post-fetch: exclude 0DTE noise
    max_dte:           int   = 365        # post-fetch: exclude deep LEAPS
    min_premium_usd:   float = 250_000    # post-fetch: meaningful bets only
    min_last_price:    float = 0.10       # post-fetch: no sub-penny contracts
```

---

## Running tests

```bash
python -m pytest tests/ -v   # 20 tests, no network required
```

---

## Relationship to `earnings_history`

`flow-lens` uses the same Barchart auth chain as `earnings_history/barchart.py`
and is designed to sit alongside it. They share no code but the cookie loading
logic is intentionally identical so both tools work from the same browser session.

---

## Disclaimer

For research and educational purposes only. Nothing here constitutes financial advice.
Options trading involves substantial risk of loss.
