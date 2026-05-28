"""
models/options.py
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional


@dataclass
class OptionContract:
    symbol:      str
    ticker:      str
    option_type: str
    strike:      float
    expiration:  date
    dte:         int
    bid:         float
    ask:         float
    underlying_price: float
    volatility:  float
    delta:       float
    moneyness:   str
    volume:      int
    open_interest: int
    trade_time:  datetime

    vol_oi_ratio: float = field(init=False)
    premium_usd:  float = field(init=False)

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
        return self.expiration.strftime("%d%b%y").upper()


@dataclass
class DominantContract:
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

    oi_change:        int = 0
    volume_change:    int = 0
    consecutive_days: int = 1

    dominant_contract: Optional[DominantContract] = None

    # ── Pure directional flags ─────────────────────────────────────────────

    @property
    def is_pure_calls(self) -> bool:
        """All qualifying contracts were calls — no puts passed the filters."""
        return self.call_volume > 0 and self.put_volume == 0

    @property
    def is_pure_puts(self) -> bool:
        """All qualifying contracts were puts — no calls passed the filters."""
        return self.put_volume > 0 and self.call_volume == 0

    # ── Parity ratios ──────────────────────────────────────────────────────

    @property
    def parity(self) -> Optional[float]:
        """
        Call/Put volume ratio. None when flow is purely one-sided —
        the ratio is undefined (and irrelevant) when the other side is zero.
        Use is_pure_calls / is_pure_puts to detect pure flow.
        """
        if self.call_volume == 0 or self.put_volume == 0:
            return None
        return round(self.call_volume / self.put_volume, 2)

    @property
    def premium_parity(self) -> Optional[float]:
        """Same as parity but weighted by premium spent."""
        if self.call_premium == 0 or self.put_premium == 0:
            return None
        return round(self.call_premium / self.put_premium, 2)

    # ── Direction ─────────────────────────────────────────────────────────

    @property
    def bias(self) -> str:
        if self.is_pure_calls:
            return "Long"
        if self.is_pure_puts:
            return "Short"
        p = self.parity
        if p is None:
            return "Neutral"
        if p >= 1.5:
            return "Long"
        if p <= 0.67:
            return "Short"
        return "Neutral"

    @property
    def parity_label(self) -> str:
        """Human-readable parity — shows 'Calls only' / 'Puts only' for pure flow."""
        if self.is_pure_calls:
            return "Calls only"
        if self.is_pure_puts:
            return "Puts only"
        p = self.parity
        return str(p) if p is not None else "—"

    @property
    def premium_parity_label(self) -> str:
        if self.is_pure_calls:
            return "Calls only"
        if self.is_pure_puts:
            return "Puts only"
        p = self.premium_parity
        return str(p) if p is not None else "—"

    # ── Signal quality ────────────────────────────────────────────────────

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
            f"{self.ticker} | {self.bias} ({self.parity_label}) | "
            f"Premium: ${self.total_premium:,.0f} | "
            f"Strength: {self.signal_strength} | "
            f"Days: {self.consecutive_days}{dom}"
        )
