"""
data/transformer.py

Converts raw Barchart API response dicts into typed OptionContract objects.

This is where:
  - field name normalisation happens (camelCase → snake_case)
  - type coercions happen (string prices → float, unix ts → datetime)
  - DTE is calculated (API returns it but we recalculate to be sure)
  - Local quality filters are applied (Vol/OI ratio, DTE window, premium size)

Keeping this separate from the client means we can swap data sources
(Barchart → another provider) without touching any signal logic.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Optional

from config import OptionsFilterConfig
from models.options import OptionContract

logger = logging.getLogger(__name__)


class OptionsTransformer:
    """
    Stateless transformer: raw API dict → OptionContract (or None if filtered out).
    """

    def __init__(self, cfg: OptionsFilterConfig):
        self.cfg = cfg

    def transform_all(self, raw_rows: list[dict]) -> list[OptionContract]:
        """
        Parse and filter a full API response.
        Returns only contracts that pass all quality filters.
        """
        contracts = []
        skipped   = 0

        for row in raw_rows:
            contract = self._parse_row(row)
            if contract is None:
                skipped += 1
                continue
            if self._passes_filters(contract):
                contracts.append(contract)
            else:
                skipped += 1

        logger.info(
            "Parsed %d contracts, filtered out %d, kept %d",
            len(raw_rows), skipped, len(contracts),
        )
        return contracts

    # -----------------------------------------------------------------------
    # Parsing
    # -----------------------------------------------------------------------

    def _parse_row(self, row: dict) -> Optional[OptionContract]:
        """
        Parse one API row. Returns None if any required field is missing/invalid.
        The API returns both a 'raw' sub-object (numeric) and top-level
        formatted strings — we prefer 'raw' for numeric fields.
        """
        raw = row.get("raw", row)   # use raw sub-object if present

        try:
            expiration = self._parse_date(
                raw.get("expirationDate") or row.get("expirationDate", "")
            )
            today = date.today()
            dte   = (expiration - today).days

            contract = OptionContract(
                symbol           = str(row.get("symbol", "")),
                ticker           = str(raw.get("baseSymbol", row.get("baseSymbol", ""))),
                option_type      = self._normalise_type(
                                       raw.get("symbolType", row.get("symbolType", ""))
                                   ),
                strike           = self._to_float(raw.get("strikePrice", 0)),
                expiration       = expiration,
                dte              = dte,
                bid              = self._to_float(raw.get("bidPrice", 0)),
                ask              = self._to_float(raw.get("askPrice", 0)),
                last             = self._to_float(raw.get("lastPrice", 0)),
                midpoint         = self._to_float(raw.get("midpoint", 0)),
                underlying_price = self._to_float(raw.get("baseLastPrice", 0)),
                volume           = self._to_int(raw.get("volume", 0)),
                open_interest    = self._to_int(raw.get("openInterest", 0)),
                volatility       = self._to_float(raw.get("volatility", 0)) / 100,
                trade_time       = self._parse_timestamp(raw.get("tradeTime", 0)),
            )
            return contract

        except Exception as exc:
            logger.debug("Skipping malformed row %s: %s", row.get("symbol"), exc)
            return None

    # -----------------------------------------------------------------------
    # Post-fetch quality filters  (applied locally, not at API level)
    # -----------------------------------------------------------------------

    def _passes_filters(self, c: OptionContract) -> bool:
        cfg = self.cfg

        # 1. DTE window — exclude very short-dated (0DTE noise) and deep LEAPS
        if not (cfg.min_dte <= c.dte <= cfg.max_dte):
            return False

        # 2. Vol/OI ratio — the core "unusual" threshold
        #    Original C# used ~1x implicitly; we require 5x to cut noise
        if c.vol_oi_ratio < cfg.min_vol_oi_ratio:
            return False

        # 3. Minimum option price — filters out sub-penny garbage
        if c.last < cfg.min_last_price:
            return False

        # 4. Minimum premium — ensures we're seeing meaningful bets
        if c.premium_usd < cfg.min_premium_usd:
            return False

        return True

    # -----------------------------------------------------------------------
    # Type coercion helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _to_float(val) -> float:
        try:
            return float(str(val).replace(",", "").strip())
        except (ValueError, TypeError):
            return 0.0

    @staticmethod
    def _to_int(val) -> int:
        try:
            return int(str(val).replace(",", "").strip())
        except (ValueError, TypeError):
            return 0

    @staticmethod
    def _parse_date(val: str) -> date:
        """Accepts '2025-06-20', '20250620', or similar."""
        val = str(val).strip().replace("-", "")
        return datetime.strptime(val, "%Y%m%d").date()

    @staticmethod
    def _parse_timestamp(val) -> datetime:
        """Barchart tradeTime is a unix timestamp (int)."""
        try:
            return datetime.fromtimestamp(int(val), tz=timezone.utc)
        except (ValueError, TypeError, OSError):
            return datetime.now(tz=timezone.utc)

    @staticmethod
    def _normalise_type(val: str) -> str:
        val = str(val).strip().lower()
        if val in ("call", "c"):
            return "Call"
        if val in ("put", "p"):
            return "Put"
        return val.title()
