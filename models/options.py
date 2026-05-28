"""
models/options.py

Data containers for options flow signals.

Field changes vs original C# Raw model:
  Added:   moneyness, delta  (new fields in confirmed API response)
  Removed: midpoint          (not in confirmed API response)
  Renamed: lastPrice → last  (lastPrice is filter-only in confirmed API; askPrice is pricing)
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional


@dataclass
class OptionContract:
    # Identifiers
    symbol:      str    # e.g. "AAPL|250620|C|200"
    ticker:      str    # e.g. "AAPL"
    option_type: str    # "Call" or "Put"
    strike:      float
    expiration:  date
    dte:         int

    # Pricing
    bid:              float
    ask:              float
    underlying_price: float   # baseLastPrice — stock price

    # Greeks / vol
    volatility: float   # implied vol as decimal (0.35 = 35%)
    delta:      float   # NEW: option delta
    moneyness:  str     # NEW: "ITM" / "ATM" / "OTM"

    # Activity
    volume:        int
    open_interest: int
    trade_time:    datetime

    # Derived — calculated on construction
    vol_oi_ratio: float = field(init=False)
    premium_usd:  float = field(init=False)   # volume × mid × 100

    def __post_init__(self):
        self.vol_oi_ratio = (
            round(self.volume / self.open_interest, 2)
            if self.open_interest > 0 else 0.0
        )
        mid = (self.bid + self.ask) / 2
        self.premium_usd = round(self.volume * mid * 100, 2)

    @property
    def is_call(self) -> bool:
        return self.option_type.upper() == "CALL"

    @property
    def is_put(self) -> bool:
        return self.option_type.upper() == "PUT"

    @property
    def expiration_label(self) -> str:
        """e.g. '20JUN25'"""
        return self.expiration.strftime("%d%b%y").upper()


@dataclass
class DominantContract:
    """The single highest-premium contract for a ticker — the actionable output."""
    ticker:           str
    option_type:      str
    strike:           float
    expiration:       date
    dte:              int
    expiration_label: str
    premium_usd:      float
    vol_oi_ratio:     float
    volume:           int
    open_interest:    int
    volatility:       float
    delta:            float
    moneyness:        str
    symbol:           str

    def __str__(self) -> str:
        return (
            f"{self.ticker} {self.strike}{self.option_type[0].upper()} "
            f"{self.expiration_label} | Premium: ${self.premium_usd:,.0f} | "
            f"Vol/OI: {self.vol_oi_ratio:.1f}x | DTE: {self.dte} | "
            f"Δ{self.delta:.2f} | {self.moneyness}"
        )


@dataclass
class TickerBias:
    """Aggregated signal for one underlying ticker."""
    ticker: str

    call_volume:   int   = 0
    put_volume:    int   = 0
    total_volume:  int   = 0
    call_premium:  float = 0.0
    put_premium:   float = 0.0
    total_premium: float = 0.0
    call_contracts:  int = 0
    put_contracts:   int = 0
    total_contracts: int = 0

    oi_change:     int   = 0
    volume_change: int   = 0
    consecutive_days: int = 1

    dominant_contract: Optional[DominantContract] = None

    @property
    def parity(self) -> float:
        if self.put_volume == 0:
            return float("inf") if self.call_volume > 0 else 0.0
        return round(self.call_volume / self.put_volume, 2)

    @property
    def premium_parity(self) -> float:
        if self.put_premium == 0:
            return float("inf") if self.call_premium > 0 else 0.0
        return round(self.call_premium / self.put_premium, 2)

    @property
    def bias(self) -> str:
        if self.parity >= 1.5:
            return "Long"
        if self.parity <= 0.67:
            return "Short"
        return "Neutral"

    @property
    def signal_strength(self) -> str:
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
