"""
signals/persistence.py

Tracks directional bias persistence across trading days.

Ledger schema per ticker:
{
  "MU": {
    "bias":             "Short",
    "consecutive_days": 3,
    "last_seen":        "2026-05-28",   ← date of last pipeline run
    "total_premium":    39_615_705.0
  }
}

Day-count rules:
  - First appearance           → 1
  - Same bias, new day         → consecutive_days + 1
  - Same bias, same day        → unchanged  (re-run guard)
  - Different bias, any day    → 1
  - Absent today               → streak frozen (not reset until next appearance)
"""
from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

from models.options import TickerBias

logger = logging.getLogger(__name__)
LEDGER_FILENAME = "persistence_ledger.json"


class PersistenceTracker:

    def __init__(self, output_dir: Path):
        self.ledger_path = output_dir / LEDGER_FILENAME
        self._ledger: dict[str, dict] = self._load()

    def annotate(self, biases: list[TickerBias]) -> list[TickerBias]:
        today = date.today().isoformat()

        for bias in biases:
            prev = self._ledger.get(bias.ticker)

            if prev is None:
                # First time we've seen this ticker
                bias.consecutive_days = 1

            elif prev["bias"] != bias.bias:
                # Direction reversed — reset regardless of date
                bias.consecutive_days = 1

            elif prev["last_seen"] == today:
                # ── RE-RUN GUARD ──────────────────────────────────────────
                # Same direction, same calendar day — ledger already updated
                # this run. Stamp the existing count, do NOT increment.
                bias.consecutive_days = prev["consecutive_days"]

            else:
                # Same direction, new day — extend the streak
                bias.consecutive_days = prev["consecutive_days"] + 1

            self._ledger[bias.ticker] = {
                "bias":             bias.bias,
                "consecutive_days": bias.consecutive_days,
                "last_seen":        today,
                "total_premium":    bias.total_premium,
            }

        self._save()
        return biases

    def get_streak(self, ticker: str) -> int:
        entry = self._ledger.get(ticker)
        return entry["consecutive_days"] if entry else 0

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
        logger.debug("Persistence ledger saved → %s", self.ledger_path)
