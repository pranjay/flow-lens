"""
config.py — Central configuration

All tuneable parameters in one place.
"""
from dataclasses import dataclass, field
from pathlib import Path

OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)


@dataclass
class OptionsFilterConfig:
    # ── API-side filters (sent in the request URL) ─────────────────────────
    # These match the confirmed live browser request exactly.

    min_volume: int         = 5000          # was 500 in C#; real endpoint uses 5000
    min_open_interest: int  = 100
    min_stock_price: float  = 2.00          # NEW: baseLastPrice filter
    exchanges: tuple        = ("AMEX", "NYSE", "NASDAQ", "INDEX-CBOE")  # CBOE added
    page_size: int          = 100           # API returns 100/page; we paginate

    # ── Post-fetch quality filters (applied locally after parsing) ──────────
    # These are our signal-quality improvements on top of the API filters.

    min_vol_oi_ratio: float = 5.0           # cut 0DTE noise; original C# used ~1x
    min_dte: int            = 7             # exclude 0-6 DTE entirely
    max_dte: int            = 365           # exclude deep LEAPS from volume screen
    min_premium_usd: float  = 250_000       # notional bet size floor

    # ── Report settings ────────────────────────────────────────────────────
    include_etfs: bool   = True
    include_stocks: bool = True
    top_n_tickers: int   = 50
