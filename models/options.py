"""
models/options.py
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional


# Aggressor classification thresholds
# last >= ask * AGGRESSOR_THRESHOLD  → buyer initiated (paid up)
# last <= bid * (2 - AGGRESSOR_THRESHOLD) → seller initiated (hit bid)
_AGGRESSOR_THRESHOLD = 0.95


@dataclass
class OptionContract:
    symbol:           str
    ticker:           str
    option_type:      str
    strike:           float
    expiration:       date
    dte:              int
    bid:              float
    ask:              float
    last:             float    # last traded price — for aggressor inference
    underlying_price: float
    volatility:       float
    delta:            float
    moneyness:        str
    volume:           int
    open_interest:    int
    trade_time:       datetime

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
        return self.expiration.strftime("%d%b%y").upper()

    @property
    def aggressor(self) -> str:
        """
        Infer who initiated the trade from last vs bid/ask.

        'Buyer'  — last traded near or above ask → someone paid up, urgency to get in
        'Seller' — last traded near or below bid → someone hit the bid, urgency to exit
        'Mixed'  — last is mid-range, ambiguous (spread trade, negotiated block)
        'Unknown'— last price unavailable or spread is zero

        Interpretation:
          Call + Buyer  → bullish bet opening
          Put  + Buyer  → bearish bet opening  (or protective put)
          Call + Seller → closing long call or writing covered call (NOT bullish)
          Put  + Seller → closing long put or writing put (NOT bearish)
        """
        if self.last <= 0 or self.ask <= 0:
            return "Unknown"
        spread = self.ask - self.bid
        if spread <= 0:
            return "Unknown"
        # Position of last within the bid-ask spread (0.0 = bid, 1.0 = ask)
        position = (self.last - self.bid) / spread
        if position >= _AGGRESSOR_THRESHOLD:
            return "Buyer"
        if position <= (1 - _AGGRESSOR_THRESHOLD):
            return "Seller"
        return "Mixed"

    @property
    def is_opening_bet(self) -> bool:
        """
        True when signal suggests new directional money entering:
          - Call + Buyer  (long bet opening)
          - Put  + Buyer  (short bet opening)
        False for sellers (closing or writing) and ambiguous cases.
        """
        return self.aggressor == "Buyer"


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
    aggressor:        str     # NEW: Buyer / Seller / Mixed / Unknown
    symbol:           str

    def __str__(self) -> str:
        return (
            f"{self.ticker} {self.strike}{self.option_type[0].upper()} "
            f"{self.expiration_label} | Premium: ${self.premium_usd:,.0f} | "
            f"Vol/OI: {self.vol_oi_ratio:.1f}x | DTE: {self.dte} | "
            f"Δ{self.delta:.2f} | {self.moneyness} | {self.aggressor}"
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

    # OI change — today's total OI vs yesterday's (populated by pipeline)
    oi_change:        int = 0
    volume_change:    int = 0
    consecutive_days: int = 1

    # Aggressor breakdown — buyer-initiated vs seller-initiated premium
    buyer_premium:  float = 0.0   # NEW: premium where aggressor == Buyer
    seller_premium: float = 0.0   # NEW: premium where aggressor == Seller

    dominant_contract: Optional[DominantContract] = None

    # ── Pure directional flags ─────────────────────────────────────────────

    @property
    def is_pure_calls(self) -> bool:
        return self.call_volume > 0 and self.put_volume == 0

    @property
    def is_pure_puts(self) -> bool:
        return self.put_volume > 0 and self.call_volume == 0

    # ── Parity ────────────────────────────────────────────────────────────

    @property
    def parity(self) -> Optional[float]:
        if self.call_volume == 0 or self.put_volume == 0:
            return None
        return round(self.call_volume / self.put_volume, 2)

    @property
    def premium_parity(self) -> Optional[float]:
        if self.call_premium == 0 or self.put_premium == 0:
            return None
        return round(self.call_premium / self.put_premium, 2)

    @property
    def parity_label(self) -> str:
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

    # ── Aggressor ratio ───────────────────────────────────────────────────

    @property
    def buyer_ratio(self) -> Optional[float]:
        """
        Fraction of total premium that was buyer-initiated.
        > 0.7 = strongly opening / directional
        < 0.3 = mostly closing / writing
        None  = no aggressor data available
        """
        total = self.buyer_premium + self.seller_premium
        if total == 0:
            return None
        return round(self.buyer_premium / total, 2)

    @property
    def aggressor_label(self) -> str:
        r = self.buyer_ratio
        if r is None:
            return "Unknown"
        if r >= 0.7:
            return "Opening"    # majority buyer-initiated → new positions
        if r <= 0.3:
            return "Closing"    # majority seller-initiated → existing positions
        return "Mixed"

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
        aggressor = f" | {self.aggressor_label}" if self.buyer_ratio is not None else ""
        return (
            f"{self.ticker} | {self.bias} ({self.parity_label}) | "
            f"Premium: ${self.total_premium:,.0f} | "
            f"Strength: {self.signal_strength} | "
            f"Days: {self.consecutive_days}{aggressor}{dom}"
        )
