"""
data/oi_client.py

Fetches the OI Change screener from Barchart.

Endpoint (confirmed from browser DevTools):
  https://www.barchart.com/proxies/core-api/v1/options/get
  orderBy=openInterestChange

This is a separate fetch from the volume screener — same endpoint,
different ordering and filters. Returns contracts where OI grew the most,
meaning new positions were actually opened and held overnight.

Key differences vs volume screener:
  - orderBy: openInterestChange (not volume)
  - volume floor: 500 (not 5000 — OI screen casts a wider net)
  - new filter: gt(openInterestChange,1000)
  - tradeTime: DATE to DATE+4 (covers weekends — OI settles T+1)
  - new field: openInterestChange
  - no lastPrice field (aggressor inference not applicable here)
"""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

from data.barchart_client import load_barchart_cookies
from config import OptionsFilterConfig

log = logging.getLogger(__name__)

ENDPOINT = "https://www.barchart.com/proxies/core-api/v1/options/get"

OI_FIELDS = ",".join([
    "symbol",
    "baseSymbol",
    "baseLastPrice",
    "expirationDate",
    "daysToExpiration",
    "baseSymbolType",
    "symbolType",
    "strikePrice",
    "moneyness",
    "bidPrice",
    "askPrice",
    "volume",
    "openInterest",
    "openInterestChange",       # the key field — how much OI grew today
    "volumeOpenInterestRatio",
    "volatility",
    "delta",
    "tradeTime",
    "symbolCode",
    "hasOptions",
])


class OIChangeClient:
    """
    Fetches contracts with the largest increase in open interest.

    Same auth as BarchartClient — shares load_barchart_cookies().
    """

    def __init__(
        self,
        cookie:     str | None = None,
        xsrf_token: str | None = None,
        delay:      float = 0.3,
    ):
        self.cookie, self.xsrf_token = load_barchart_cookies(cookie, xsrf_token)
        self.delay = delay

    def _headers(self) -> dict:
        return {
            "User-Agent":   "Mozilla/5.0",
            "Accept":       "application/json",
            "Cookie":       self.cookie,
            "x-xsrf-token": self.xsrf_token,
            "Referer":      "https://www.barchart.com/",
        }

    def get_oi_leaders(
        self,
        asset_type:  str,              # "stock" or "etf"
        cfg:         OptionsFilterConfig,
        trade_date:  date | None = None,
    ) -> list[dict]:
        """
        Fetch all pages of OI change leaders for a given date.
        tradeTime window is trade_date → trade_date+4 to catch T+1 OI settlement.
        """
        trade_date = trade_date or date.today()
        all_rows: list[dict] = []
        page = 1

        while True:
            qs   = self._build_qs(asset_type, cfg, trade_date, page)
            url  = f"{ENDPOINT}?{qs}"
            rows = self._fetch_page(url, asset_type, page)
            if not rows:
                break
            all_rows.extend(rows)
            if len(rows) < cfg.page_size:
                break
            page += 1
            time.sleep(self.delay)

        log.info("OI leaders [%s] %s: %d rows", asset_type, trade_date, len(all_rows))
        return all_rows

    def _build_qs(
        self,
        asset_type: str,
        cfg:        OptionsFilterConfig,
        trade_date: date,
        page:       int,
    ) -> str:
        # OI settles T+1 — use a 4-day window to catch weekend rollovers
        end_date   = trade_date + timedelta(days=4)
        exchanges  = ",".join(cfg.exchanges)

        params: list[tuple[str, str]] = [
            ("fields",       OI_FIELDS),
            ("orderBy",      "openInterestChange"),
            ("orderDir",     "desc"),
            ("baseSymbolTypes", asset_type),
            # ── confirmed filters from browser ─────────────────────────────
            (f"between(tradeTime,{trade_date.isoformat()},{end_date.isoformat()})", ""),
            ("between(lastPrice,.10,)",                         ""),
            (f"between(baseLastPrice,{cfg.min_stock_price},)",  ""),
            (f"between(volume,{cfg.min_oi_volume},)",           ""),  # lower floor for OI screen
            (f"between(openInterest,{cfg.min_open_interest},)", ""),
            (f"in(exchange,({exchanges}))",                     ""),
            (f"gt(openInterestChange,{cfg.min_oi_change})",     ""),
            ("meta",      "field.shortName,field.type,field.description"),
            ("page",      str(page)),
            ("limit",     str(cfg.page_size)),
            ("hasOptions", "true"),
            ("raw",        "1"),
        ]
        return "&".join(
            f"{k}={urllib.parse.quote(str(v), safe=',.()_-:')}"
            for k, v in params
        )

    def _fetch_page(
        self, url: str, label: str, page: int, retries: int = 3
    ) -> list[dict]:
        log.debug("GET %s", url)
        for attempt in range(1, retries + 1):
            req = urllib.request.Request(url, headers=self._headers())
            try:
                with urllib.request.urlopen(req, timeout=20) as resp:
                    return json.loads(resp.read().decode()).get("data", [])
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    wait = 2.0 * (2 ** (attempt - 1))
                    log.warning("Rate limited — %.0fs (attempt %d/%d)", wait, attempt, retries)
                    time.sleep(wait)
                    if attempt == retries:
                        return []
                else:
                    log.warning("HTTP %d [OI/%s] page %d", e.code, label, page)
                    return []
            except Exception as e:
                log.warning("OI fetch failed [%s] page %d attempt %d: %s", label, page, attempt, e)
                if attempt == retries:
                    return []
                time.sleep(self.delay)
        return []
