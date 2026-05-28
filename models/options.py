"""
models/options.py

Dataclasses that represent:
  - OptionContract  : one row from the Barchart API (one strike/expiry)
  - TickerBias      : the aggregated signal per underlying ticker
  - DominantContract: the single highest-premium contract for a ticker (the actual "bet")

These are pure data containers — no business logic.
They map 1-to-1 with the C# Raw / Datum / BarchartApiResponse models
but are richer (DTE, premium, vol_oi_ratio calculated on construction).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional


# ---------------------------------------------------------------------------
# Raw contract (one row from the API)
# ---------------------------------------------------------------------------

@dataclass
class OptionContract:
    # Identifiers
    symbol: str          # full option symbol  e.g. "AAPL|250620|C|200"
    ticker: str          # underlying          e.g. "AAPL"
    option_type: str     # "Call" or "Put"
    strike: float
    expiration: date
    dte: int             # days to expiration (calculated)

    # Pricing
    bid: float
    ask: float
    last: float
    midpoint: float
    underlying_price: float   # stock's last price — NOT the option price

    # Activity
    volume: int
    open_interest: int
    volatility: float         # implied vol as a decimal  (0.35 = 35%)
    trade_time: datetime

    # Derived metrics — calculated at parse time, not from the API
    vol_oi_ratio: float = field(init=False)
    premium_usd: float  = field(init=False)   # volume × last × 100

    def __post_init__(self):
        self.vol_oi_ratio = (
            round(self.volume / self.open_interest, 2)
            if self.open_interest > 0 else 0.0
        )
        self.premium_usd = round(self.volume * self.last * 100, 2)

    @property
    def is_call(self) -> bool:
        return self.option_type.upper() == "CALL"

    @property
    def is_put(self) -> bool:
        return self.option_type.upper() == "PUT"

    @property
    def expiration_label(self) -> str:
        """e.g. '20JUN25' — matches the C# ExpirationLong format"""
        return self.expiration.strftime("%d%b%y").upper()


# ---------------------------------------------------------------------------
# Dominant contract — the single best representative for a ticker's bias
# ---------------------------------------------------------------------------

@dataclass
class DominantContract:
    """
    The highest-premium contract for a ticker.
    This is the actionable output: 'smart money chose THIS strike/expiry.'
    """
    ticker: str
    option_type: str
    strike: float
    expiration: date
    dte: int
    expiration_label: str
    premium_usd: float
    vol_oi_ratio: float
    volume: int
    open_interest: int
    volatility: float
    symbol: str

    def __str__(self) -> str:
        return (
            f"{self.ticker} {self.strike}{self.option_type[0].upper()} "
            f"{self.expiration_label} | Premium: ${self.premium_usd:,.0f} | "
            f"Vol/OI: {self.vol_oi_ratio:.1f}x | DTE: {self.dte}"
        )


# ---------------------------------------------------------------------------
# Ticker-level aggregated bias (the "Bets" table)
# ---------------------------------------------------------------------------

@dataclass
class TickerBias:
    """
    Aggregated signal for one underlying ticker across all its active contracts.
    Replaces + extends the C# 'betTable' logic.
    """
    ticker: str

    # Volume aggregates
    call_volume: int = 0
    put_volume: int  = 0
    total_volume: int = 0

    # Premium aggregates (weighted signal strength)
    call_premium: float = 0.0
    put_premium: float  = 0.0
    total_premium: float = 0.0

    # Contract counts
    call_contracts: int = 0   # number of distinct call rows
    put_contracts: int  = 0
    total_contracts: int = 0  # "Bets" in the original

    # OI change (day-over-day, populated if yesterday's data is available)
    oi_change: int = 0
    volume_change: int = 0

    # Multi-day persistence (populated by PersistenceTracker)
    consecutive_days: int = 1

    # The single most telling contract
    dominant_contract: Optional[DominantContract] = None

    # -----------------------------------------------------------------------
    # Derived properties
    # -----------------------------------------------------------------------

    @property
    def parity(self) -> float:
        """Call/put volume ratio. >1 = bullish lean, <1 = bearish lean."""
        if self.put_volume == 0:
            return float("inf") if self.call_volume > 0 else 0.0
        return round(self.call_volume / self.put_volume, 2)

    @property
    def premium_parity(self) -> float:
        """Call/put ratio weighted by premium — more meaningful than raw volume."""
        if self.put_premium == 0:
            return float("inf") if self.call_premium > 0 else 0.0
        return round(self.call_premium / self.put_premium, 2)

    @property
    def bias(self) -> str:
        """'Long', 'Short', or 'Neutral'"""
        if self.parity >= 1.5:
            return "Long"
        if self.parity <= 0.67:
            return "Short"
        return "Neutral"

    @property
    def signal_strength(self) -> str:
        """
        Qualitative label combining premium, persistence, and parity.
        Replaces the implicit 'sort by Bets descending' in the original.
        """
        if self.consecutive_days >= 3 and self.total_premium >= 1_000_000:
            return "Strong"
        if self.consecutive_days >= 2 or self.total_premium >= 500_000:
            return "Moderate"
        return "Weak"

    def __str__(self) -> str:
        dom = f" | Top: {self.dominant_contract}" if self.dominant_contract else ""
        return (
            f"{self.ticker} | {self.bias} | Parity: {self.parity} | "
            f"Premium: ${self.total_premium:,.0f} | "
            f"Strength: {self.signal_strength} | "
            f"Days: {self.consecutive_days}{dom}"
        )
