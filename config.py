"""
config.py — Central configuration (replaces App.config)

All tuneable parameters live here. When the Barchart repo is wired in,
add the API key / base URL here and update BarchartClient accordingly.
"""
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Barchart API  (stub — fill in from the other repo)
# ---------------------------------------------------------------------------

BARCHART_API_KEY: str = ""           # injected from env / other repo
BARCHART_BASE_URL: str = "https://core-api.barchart.com/v1"


# ---------------------------------------------------------------------------
# Options Volume Leaders — filter thresholds
# ---------------------------------------------------------------------------

@dataclass
class OptionsFilterConfig:
    # Raw fetch filters (sent to the API)
    min_volume: int        = 500
    min_open_interest: int = 100
    min_last_price: float  = 0.10
    exchanges: tuple       = ("AMEX", "NASDAQ", "NYSE")
    max_results: int       = 5000

    # Post-fetch quality filters (applied locally)
    min_vol_oi_ratio: float  = 5.0    # original was ~1x — raised to cut noise
    min_dte: int             = 7      # exclude 0-6 DTE (0DTE noise)
    max_dte: int             = 365    # exclude deep LEAPS from volume screen
    min_premium_usd: float   = 250_000  # vol × last × 100 — meaningful bets only

    # Bias / scoring
    min_parity_for_signal: float  = 2.0   # call/put ratio must be ≥ 2x (or ≤ 0.5x for puts)
    min_consecutive_days: int     = 1     # set to 2+ to require multi-day persistence


@dataclass
class ReportConfig:
    include_etfs: bool    = True
    include_stocks: bool  = True
    top_n_tickers: int    = 50        # tickers to surface in the Bets summary


# Singletons used throughout the app
OPTIONS_FILTER = OptionsFilterConfig()
REPORT_CFG     = ReportConfig()
