"""
signals/oi_joiner.py

Joins OI change data onto TickerBias objects.

For each TickerBias, looks up the ticker in the OI confirmation data and:
  1. Sums OI growth by direction (call vs put)
  2. Checks whether OI direction matches the volume signal bias
  3. Identifies the top OI contract (highest oi_change for the matching direction)
  4. Sets oi_confirmed = True when both conditions met:
       - OI growth in the signal direction exceeds min_oi_confirmed_contracts
       - That direction accounts for >= oi_confirmation_ratio of total OI growth

This is the key quality gate: volume + OI growing in same direction
= new money being deployed, not just intraday noise.
"""
from __future__ import annotations

import logging
from collections import defaultdict

from config import OptionsFilterConfig
from models.options import OIConfirmation, TickerBias

log = logging.getLogger(__name__)


class OIJoiner:

    def __init__(self, cfg: OptionsFilterConfig):
        self.cfg = cfg

    def join(
        self,
        biases:       list[TickerBias],
        oi_contracts: list[OIConfirmation],
    ) -> list[TickerBias]:
        """
        Annotates each TickerBias with OI confirmation data.
        Modifies biases in-place and returns the list.
        """
        # Group OI contracts by ticker
        by_ticker: dict[str, list[OIConfirmation]] = defaultdict(list)
        for c in oi_contracts:
            by_ticker[c.ticker].append(c)

        confirmed = 0
        for bias in biases:
            contracts = by_ticker.get(bias.ticker, [])
            if not contracts:
                continue
            self._annotate(bias, contracts)
            if bias.oi_confirmed:
                confirmed += 1

        log.info(
            "OI join: %d/%d tickers OI-confirmed",
            confirmed, len(biases)
        )
        return biases

    def _annotate(
        self,
        bias:      TickerBias,
        contracts: list[OIConfirmation],
    ) -> None:
        cfg = self.cfg

        # Sum OI growth by direction
        call_growth = sum(c.oi_change for c in contracts if c.is_call)
        put_growth  = sum(c.oi_change for c in contracts if c.is_put)
        total_growth = call_growth + put_growth

        bias.oi_call_growth = call_growth
        bias.oi_put_growth  = put_growth

        if total_growth == 0:
            return

        # Which direction does the OI growth favour?
        if bias.bias == "Long":
            signal_growth     = call_growth
            top_type_filter   = lambda c: c.is_call
        elif bias.bias == "Short":
            signal_growth     = put_growth
            top_type_filter   = lambda c: c.is_put
        else:
            # Neutral bias — check whichever side dominates OI
            signal_growth   = max(call_growth, put_growth)
            top_type_filter = (lambda c: c.is_call) if call_growth >= put_growth \
                              else (lambda c: c.is_put)

        direction_ratio = signal_growth / total_growth

        # Confirm when enough OI grew in the matching direction
        bias.oi_confirmed = (
            signal_growth     >= cfg.min_oi_confirmed_contracts
            and direction_ratio >= cfg.oi_confirmation_ratio
        )

        # Find the top contract in the matching direction
        matching = [c for c in contracts if top_type_filter(c)]
        if matching:
            bias.oi_top_contract = max(matching, key=lambda c: c.oi_change)

        log.debug(
            "%s | bias=%s | call_oi=+%d put_oi=+%d | ratio=%.2f | confirmed=%s",
            bias.ticker, bias.bias, call_growth, put_growth,
            direction_ratio, bias.oi_confirmed,
        )
