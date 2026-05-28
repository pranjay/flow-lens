"""
signals/persistence.py

Tracks whether a ticker's directional bias has persisted across multiple days.

This is the single most important improvement over the original C# code.
Repeated directional flow over multiple days carries dramatically more
conviction than a one-day spike, which could be hedging, rolling, or noise.

Architecture:
  - PersistenceTracker loads and saves a lightweight JSON ledger
  - On each run, it compares today's biases to the ledger
  - If direction matches yesterday, consecutive_days increments
  - If direction reverses, streak resets to 1
  - The ledger persists between runs in OUTPUT_DIR/persistence_ledger.json
"""
from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from typing import Optional

from models.options import TickerBias

logger = logging.getLogger(__name__)

LEDGER_FILENAME = "persistence_ledger.json"


class PersistenceTracker:
    """
    Maintains a rolling day-count for each ticker's directional bias.

    Ledger schema (one entry per ticker):
    {
      "AAPL": {
        "bias":             "Long",
        "consecutive_days": 3,
        "last_seen":        "2025-06-10",
        "total_premium":    1_250_000.0
      },
      ...
    }
    """

    def __init__(self, output_dir: Path):
        self.ledger_path = output_dir / LEDGER_FILENAME
        self._ledger: dict[str, dict] = self._load()

    # -----------------------------------------------------------------------
    # Public interface
    # -----------------------------------------------------------------------

    def annotate(self, biases: list[TickerBias]) -> list[TickerBias]:
        """
        Stamps each TickerBias with its consecutive_days count
        and updates the ledger for the next run.
        """
        today = date.today().isoformat()

        for bias in biases:
            prev = self._ledger.get(bias.ticker)

            if prev and prev.get("bias") == bias.bias:
                # Same direction — extend streak
                bias.consecutive_days = prev["consecutive_days"] + 1
            else:
                # New direction or first appearance — reset
                bias.consecutive_days = 1

            # Update ledger
            self._ledger[bias.ticker] = {
                "bias":             bias.bias,
                "consecutive_days": bias.consecutive_days,
                "last_seen":        today,
                "total_premium":    bias.total_premium,
            }

        # Prune tickers not seen today (stale entries)
        seen_tickers = {b.ticker for b in biases}
        stale = [t for t in self._ledger if t not in seen_tickers]
        for t in stale:
            # Keep entries from yesterday (they may return tomorrow)
            entry = self._ledger[t]
            if entry.get("last_seen") < today:
                # Reset streak — ticker absent today breaks the streak
                self._ledger[t]["consecutive_days"] = 0

        self._save()
        return biases

    def get_streak(self, ticker: str) -> int:
        entry = self._ledger.get(ticker)
        return entry["consecutive_days"] if entry else 0

    # -----------------------------------------------------------------------
    # Persistence
    # -----------------------------------------------------------------------

    def _load(self) -> dict:
        if self.ledger_path.exists():
            try:
                with open(self.ledger_path) as f:
                    return json.load(f)
            except json.JSONDecodeError:
                logger.warning("Corrupted ledger — starting fresh")
        return {}

    def _save(self) -> None:
        with open(self.ledger_path, "w") as f:
            json.dump(self._ledger, f, indent=2)
        logger.debug("Persistence ledger saved to %s", self.ledger_path)
