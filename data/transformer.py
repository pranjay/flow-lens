"""
data/transformer.py — raw API dict → typed OptionContract + quality filters
"""
from __future__ import annotations
import logging
from datetime import date, datetime, timezone
from typing import Optional
from config import OptionsFilterConfig
from models.options import OptionContract

log = logging.getLogger(__name__)


class OptionsTransformer:

    def __init__(self, cfg: OptionsFilterConfig):
        self.cfg = cfg

    def transform_all(self, raw_rows: list[dict]) -> list[OptionContract]:
        contracts, skipped = [], 0
        for row in raw_rows:
            c = self._parse_row(row)
            if c is None:
                skipped += 1
                continue
            if self._passes_filters(c):
                contracts.append(c)
            else:
                skipped += 1
        log.info("Parsed %d rows → kept %d, filtered %d", len(raw_rows), len(contracts), skipped)
        return contracts

    def _parse_row(self, row: dict) -> Optional[OptionContract]:
        raw = row.get("raw", row)
        try:
            expiration = self._parse_date(
                raw.get("expirationDate") or row.get("expirationDate", "")
            )
            dte = (expiration - date.today()).days
            return OptionContract(
                symbol           = str(row.get("symbol", "")),
                ticker           = str(raw.get("baseSymbol", "")),
                option_type      = self._normalise_type(raw.get("symbolType", "")),
                strike           = self._f(raw.get("strikePrice", 0)),
                expiration       = expiration,
                dte              = dte,
                bid              = self._f(raw.get("bidPrice", 0)),
                ask              = self._f(raw.get("askPrice", 0)),
                last             = self._f(raw.get("lastPrice", 0)),
                underlying_price = self._f(raw.get("baseLastPrice", 0)),
                volatility       = self._f(raw.get("volatility", 0)) / 100,
                delta            = self._f(raw.get("delta", 0)),
                moneyness        = str(raw.get("moneyness", "") or ""),
                volume           = self._i(raw.get("volume", 0)),
                open_interest    = self._i(raw.get("openInterest", 0)),
                trade_time       = self._parse_ts(raw.get("tradeTime", 0)),
            )
        except Exception as exc:
            log.debug("Skipping malformed row %s: %s", row.get("symbol"), exc)
            return None

    def _passes_filters(self, c: OptionContract) -> bool:
        cfg = self.cfg
        if not (cfg.min_dte <= c.dte <= cfg.max_dte):
            return False
        if c.vol_oi_ratio < cfg.min_vol_oi_ratio:
            return False
        if c.premium_usd < cfg.min_premium_usd:
            return False
        return True

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
    def _parse_ts(val) -> datetime:
        try:
            return datetime.fromtimestamp(int(val), tz=timezone.utc)
        except (ValueError, TypeError, OSError):
            return datetime.now(tz=timezone.utc)

    @staticmethod
    def _normalise_type(val: str) -> str:
        v = str(val).strip().lower()
        if v in ("call", "c"):
            return "Call"
        if v in ("put", "p"):
            return "Put"
        return val.title()
