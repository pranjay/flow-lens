"""
config.py — Central configuration
"""
from dataclasses import dataclass
from pathlib import Path

OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)


@dataclass
class OptionsFilterConfig:
    # ── Volume screener — API-side filters ────────────────────────────────
    min_volume:         int   = 5000       # confirmed from live browser request
    min_open_interest:  int   = 100
    min_stock_price:    float = 2.00
    exchanges:          tuple = ("AMEX", "NYSE", "NASDAQ", "INDEX-CBOE")
    page_size:          int   = 100

    # ── OI screener — API-side filters ────────────────────────────────────
    min_oi_volume:  int = 500              # lower floor — OI screen casts wider net
    min_oi_change:  int = 1000             # gt(openInterestChange,1000)

    # ── Post-fetch quality filters (both screeners) ───────────────────────
    min_vol_oi_ratio:  float = 5.0
    min_dte:           int   = 7
    max_dte:           int   = 365
    min_premium_usd:   float = 250_000

    # ── OI confirmation thresholds ─────────────────────────────────────────
    # A ticker is "OI confirmed" when its OI growth direction matches
    # the volume signal direction.
    min_oi_confirmed_contracts: int   = 1000   # minimum OI growth to count as confirmation
    oi_confirmation_ratio:      float = 0.65   # 65%+ of OI growth must match bias direction

    # ── Report settings ───────────────────────────────────────────────────
    include_etfs:   bool = True
    include_stocks: bool = True
    top_n_tickers:  int  = 50
