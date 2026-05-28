"""
signals/bias_engine.py

Aggregates filtered OptionContract objects into per-ticker TickerBias signals.

New in this version:
  - buyer_premium / seller_premium populated from contract.aggressor
  - OI change calculated from previous day's ledger (passed in as prev_oi)
  - DominantContract includes aggressor field
"""
from __future__ import annotations
import logging
from collections import defaultdict
from typing import Optional
from models.options import DominantContract, OptionContract, TickerBias

log = logging.getLogger(__name__)


class BiasEngine:

    def compute(
        self,
        contracts:    list[OptionContract],
        prev_oi:      Optional[dict[str, int]] = None,   # ticker → yesterday's total OI
        prev_biases:  Optional[dict[str, TickerBias]] = None,
    ) -> list[TickerBias]:
        grouped: dict[str, list[OptionContract]] = defaultdict(list)
        for c in contracts:
            grouped[c.ticker].append(c)

        biases = []
        for ticker, group in grouped.items():
            bias = self._aggregate(ticker, group)
            self._inject_oi_change(bias, group, prev_oi)
            self._inject_volume_change(bias, prev_biases)
            biases.append(bias)

        biases.sort(key=lambda b: b.total_premium, reverse=True)
        log.info("BiasEngine: %d ticker signals", len(biases))
        return biases

    def _aggregate(self, ticker: str, contracts: list[OptionContract]) -> TickerBias:
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

            # Aggressor breakdown
            if c.aggressor == "Buyer":
                bias.buyer_premium  += c.premium_usd
            elif c.aggressor == "Seller":
                bias.seller_premium += c.premium_usd

        bias.dominant_contract = self._find_dominant(contracts)
        return bias

    def _find_dominant(self, contracts: list[OptionContract]) -> Optional[DominantContract]:
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
            delta            = top.delta,
            moneyness        = top.moneyness,
            aggressor        = top.aggressor,
            symbol           = top.symbol,
        )

    def _inject_oi_change(
        self,
        bias:     TickerBias,
        contracts: list[OptionContract],
        prev_oi:  Optional[dict[str, int]],
    ) -> None:
        """
        OI change = today's sum of open interest across qualifying contracts
                    minus yesterday's sum for the same ticker.

        Positive = new money entering (contracts being opened)
        Negative = positions being closed
        """
        if prev_oi is None:
            return
        today_oi       = sum(c.open_interest for c in contracts)
        yesterday_oi   = prev_oi.get(bias.ticker, 0)
        bias.oi_change = today_oi - yesterday_oi

    def _inject_volume_change(
        self,
        bias:        TickerBias,
        prev_biases: Optional[dict[str, TickerBias]],
    ) -> None:
        if prev_biases is None:
            return
        prev = prev_biases.get(bias.ticker)
        if prev:
            bias.volume_change = bias.total_volume - prev.total_volume
