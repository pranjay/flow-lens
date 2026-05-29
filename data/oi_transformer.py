"""
data/oi_transformer.py

Parses raw OI change API rows into OIConfirmation objects.
Simpler than OptionsTransformer — fewer fields, no aggressor inference.
"""
from __future__ import annotations
import logging
from datetime import date, datetime, timezone
from typing import Optional
from models.options import OIConfirmation

log = logging.getLogger(__name__)


class OITransformer:

    def transform_all(self, raw_rows: list[dict]) -> list[OIConfirmation]:
        results, skipped = [], 0
        for row in raw_rows:
            c = self._parse(row)
            if c is None:
                skipped += 1
            else:
                results.append(c)
        log.info("OI: parsed %d rows → kept %d, skipped %d",
                 len(raw_rows), len(results), skipped)
        return results

    def _parse(self, row: dict) -> Optional[OIConfirmation]:
        raw = row.get("raw", row)
        try:
            expiration = self._parse_date(
                raw.get("expirationDate") or row.get("expirationDate", "")
            )
            dte = (expiration - date.today()).days
            return OIConfirmation(
                ticker           = str(raw.get("baseSymbol", "")),
                option_type      = self._norm_type(raw.get("symbolType", "")),
                strike           = self._f(raw.get("strikePrice", 0)),
                expiration       = expiration,
                expiration_label = expiration.strftime("%d%b%y").upper(),
                dte              = dte,
                oi_change        = self._i(raw.get("openInterestChange", 0)),
                open_interest    = self._i(raw.get("openInterest", 0)),
                volume           = self._i(raw.get("volume", 0)),
                volatility       = self._f(raw.get("volatility", 0)) / 100,
                delta            = self._f(raw.get("delta", 0)),
                moneyness        = str(raw.get("moneyness", "") or ""),
            )
        except Exception as exc:
            log.debug("Skipping OI row %s: %s", row.get("symbol"), exc)
            return None

    @staticmethod
    def _f(val) -> float:
        try:
            return float(str(val).replace(",", "").strip())
        except (ValueError, TypeError):
            return 0.0

    @staticmethod
    def _i(val) -> int:
        try:
            return int(str(val).replace(",", "").strip())
        except (ValueError, TypeError):
            return 0

    @staticmethod
    def _parse_date(val: str) -> date:
        val = str(val).strip().replace("-", "")
        return datetime.strptime(val, "%Y%m%d").date()

    @staticmethod
    def _norm_type(val: str) -> str:
        v = str(val).strip().lower()
        if v in ("call", "c"): return "Call"
        if v in ("put",  "p"): return "Put"
        return val.title()
