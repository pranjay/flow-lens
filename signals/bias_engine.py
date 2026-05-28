"""
signals/bias_engine.py

The core signal logic. Takes a list of filtered OptionContract objects
and produces TickerBias objects — one per underlying ticker.

This is the Python equivalent of the C# 'betting table' logic in Program.cs
but significantly extended:
  - Premium-weighted parity (not just raw volume count)
  - Dominant contract identification (the specific strike/expiry to watch)
  - Day-over-day delta injection (OI change, volume change)
  - Persistence tracking hook (populated by PersistenceTracker)
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Optional

from models.options import DominantContract, OptionContract, TickerBias

logger = logging.getLogger(__name__)


class BiasEngine:
    """
    Aggregates a flat list of OptionContract objects into per-ticker TickerBias signals.

    Usage:
        engine  = BiasEngine()
        biases  = engine.compute(contracts, previous_biases=yesterday_biases)
    """

    def compute(
        self,
        contracts: list[OptionContract],
        previous_biases: Optional[dict[str, TickerBias]] = None,
    ) -> list[TickerBias]:
        """
        Main entry point.

        Args:
            contracts       : filtered OptionContract list from the transformer
            previous_biases : yesterday's TickerBias dict keyed by ticker
                              (None if no history available)

        Returns:
            List of TickerBias, sorted by total_premium descending
            (highest-conviction bets first).
        """
        # Step 1 — group contracts by ticker
        grouped: dict[str, list[OptionContract]] = defaultdict(list)
        for c in contracts:
            grouped[c.ticker].append(c)

        # Step 2 — aggregate each group into a TickerBias
        biases: list[TickerBias] = []
        for ticker, ticker_contracts in grouped.items():
            bias = self._aggregate(ticker, ticker_contracts)
            self._inject_deltas(bias, ticker_contracts, previous_biases)
            biases.append(bias)

        # Step 3 — sort by total premium (conviction size)
        biases.sort(key=lambda b: b.total_premium, reverse=True)

        logger.info("BiasEngine produced %d ticker signals", len(biases))
        return biases

    # -----------------------------------------------------------------------
    # Private — aggregation
    # -----------------------------------------------------------------------

    def _aggregate(
        self, ticker: str, contracts: list[OptionContract]
    ) -> TickerBias:
        bias = TickerBias(ticker=ticker)

        for c in contracts:
            bias.total_contracts += 1
            bias.total_volume    += c.volume
            bias.total_premium   += c.premium_usd

            if c.is_call:
                bias.call_volume    += c.volume
                bias.call_premium   += c.premium_usd
                bias.call_contracts += 1
            else:
                bias.put_volume    += c.volume
                bias.put_premium   += c.premium_usd
                bias.put_contracts += 1

        bias.dominant_contract = self._find_dominant(contracts)
        return bias

    def _find_dominant(
        self, contracts: list[OptionContract]
    ) -> Optional[DominantContract]:
        """
        Picks the single contract with the highest premium spend.
        This is the specific strike/expiry the market chose — the
        actionable output the original C# code never surfaced.
        """
        if not contracts:
            return None

        top = max(contracts, key=lambda c: c.premium_usd)

        return DominantContract(
            ticker           = top.ticker,
            option_type      = top.option_type,
            strike           = top.strike,
            expiration       = top.expiration,
            dte              = top.dte,
            expiration_label = top.expiration_label,
            premium_usd      = top.premium_usd,
            vol_oi_ratio     = top.vol_oi_ratio,
            volume           = top.volume,
            open_interest    = top.open_interest,
            volatility       = top.volatility,
            symbol           = top.symbol,
        )

    # -----------------------------------------------------------------------
    # Private — day-over-day delta
    # -----------------------------------------------------------------------

    def _inject_deltas(
        self,
        bias: TickerBias,
        contracts: list[OptionContract],
        previous_biases: Optional[dict[str, TickerBias]],
    ) -> None:
        """
        Mirrors the C# 'Open Interest Change' and 'Volume Change' columns.
        Populates them from the previous day's TickerBias if available.
        """
        if previous_biases is None:
            return
        prev = previous_biases.get(bias.ticker)
        if prev is None:
            return

        bias.oi_change     = sum(c.open_interest for c in contracts) - sum(
            c.open_interest for c in contracts  # replaced by prev data below
        )
        # Simpler: compare today's total volume to yesterday's
        bias.volume_change = bias.total_volume - prev.total_volume

        # OI change: today's total OI across all contracts vs yesterday's
        today_oi    = sum(c.open_interest for c in contracts)
        yesterday_oi = prev.total_contracts  # proxy if raw not stored
        bias.oi_change = today_oi - (prev.call_contracts + prev.put_contracts)
