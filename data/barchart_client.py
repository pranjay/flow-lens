"""
data/barchart_client.py

Barchart API client for options volume leaders data.

Endpoint (confirmed from browser DevTools):
  https://www.barchart.com/proxies/core-api/v1/options/get

Auth: mirrors earnings_history/barchart.py exactly —
  1. Explicit cookie / xsrf_token args
  2. BARCHART_COOKIE / BARCHART_XSRF_TOKEN env vars (+ .env / ~/.barchart.env)
  3. Browser cookie store via browser_cookie3 (Firefox → Safari on macOS)
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from config import OptionsFilterConfig

log = logging.getLogger(__name__)

ENDPOINT = "https://www.barchart.com/proxies/core-api/v1/options/get"

# ── Fields (confirmed from live browser request) ──────────────────────────────
# Removed from original C# version: midpoint, lastPrice (used only as a filter)
# Added vs original C# version: moneyness, delta, hasOptions
OPTION_FIELDS = ",".join([
    "symbol",
    "baseSymbol",
    "baseLastPrice",
    "baseSymbolType",
    "expirationDate",
    "daysToExpiration",
    "symbolType",
    "strikePrice",
    "moneyness",          # NEW vs C#: ITM / ATM / OTM
    "bidPrice",
    "askPrice",
    "volume",
    "openInterest",
    "volumeOpenInterestRatio",
    "volatility",
    "delta",              # NEW vs C#: option delta
    "tradeTime",
    "symbolCode",
    "hasOptions",         # NEW vs C#: underlying has options flag
])


# ── Cookie loading (identical to earnings_history/barchart.py) ─────────────────

def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
        from pathlib import Path as _P
        for candidate in [
            _P(__file__).parent.parent / ".env",
            _P.home() / ".barchart.env",
        ]:
            if candidate.exists():
                load_dotenv(candidate)
                break
    except ImportError:
        pass


def load_barchart_cookies(
    cookie: str | None = None,
    xsrf_token: str | None = None,
) -> tuple[str, str]:
    """
    Resolve Barchart session cookie and XSRF token.
    Priority: explicit args → env vars → Firefox → Safari (macOS)
    """
    _load_dotenv()
    cookie     = cookie     or os.environ.get("BARCHART_COOKIE", "").strip()
    xsrf_token = xsrf_token or os.environ.get("BARCHART_XSRF_TOKEN", "").strip()

    if cookie:
        return cookie, xsrf_token

    try:
        import browser_cookie3
        import sys as _sys

        SESSION_COOKIE = "laravel_session"

        def _from_browser(loader, name):
            jar     = loader(domain_name=".barchart.com")
            cookies = {c.name: c.value for c in jar}
            if not cookies:
                raise ValueError(f"No barchart.com cookies in {name}")
            if SESSION_COOKIE not in cookies:
                raise ValueError(
                    f"{name}: no active session ({SESSION_COOKIE} missing) "
                    f"— log into barchart.com in {name} first"
                )
            cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
            xsrf_str   = urllib.parse.unquote(cookies.get("XSRF-TOKEN", xsrf_token or ""))
            log.info("Barchart auth: %d cookies from %s", len(cookies), name)
            return cookie_str, xsrf_str

        browsers = (
            [(browser_cookie3.firefox, "Firefox"), (browser_cookie3.safari, "Safari")]
            if _sys.platform == "darwin"
            else [(browser_cookie3.firefox, "Firefox")]
        )
        last_err = None
        for loader, name in browsers:
            try:
                return _from_browser(loader, name)
            except Exception as e:
                last_err = e

        raise ValueError(
            f"No active Barchart session found.\nLast error: {last_err}\n\n"
            "→ Log into barchart.com in Firefox or Safari, then retry.\n"
            "→ Or set env vars: BARCHART_COOKIE / BARCHART_XSRF_TOKEN"
        )

    except ImportError:
        raise ValueError(
            "browser-cookie3 not installed and no cookie provided.\n"
            "pip install browser-cookie3\n"
            "Or set BARCHART_COOKIE environment variable."
        )


# ── Client ─────────────────────────────────────────────────────────────────────

class BarchartClient:
    """
    Fetches options volume leaders from:
      https://www.barchart.com/proxies/core-api/v1/options/get

    Differences vs the original C# App.config URL:
      - volume floor:      500  → 5000       (10x — matches live browser request)
      - exchanges:         added INDEX-CBOE
      - new API filters:   lastPrice >= 0.10, baseLastPrice >= 2.00,
                           daysToExpiration > 0, tradeTime date range, hasOptions=true
      - new fields:        moneyness, delta, hasOptions
      - removed fields:    midpoint, lastPrice (lastPrice is filter-only now)
      - limit:             5000 → 100 per page  (API paginates — see get_all_pages)
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

    def _build_qs(
        self,
        asset_type: str,
        cfg: OptionsFilterConfig,
        trade_date: date,
        page: int,
    ) -> str:
        """
        Build the query string to exactly match the confirmed live browser request.
        Uses manual string joining (not urllib.urlencode) to preserve the
        Barchart filter syntax:  gt(x,y)=  between(x,a,b)=  in(x,(a,b,c))=
        """
        next_date = (trade_date + timedelta(days=1)).isoformat()

        params: list[tuple[str, str]] = [
            ("fields",               OPTION_FIELDS),
            ("orderBy",              "volume"),
            ("orderDir",             "desc"),
            ("baseSymbolTypes",      asset_type),
            # ── API-side filters (confirmed from browser) ──────────────────
            ("gt(volatility,.01)",                          ""),
            ("between(lastPrice,.10,)",                     ""),   # option price floor
            (f"between(baseLastPrice,{cfg.min_stock_price},)", ""),  # stock price floor
            ("gt(daysToExpiration,0)",                      ""),   # no expired
            (f"between(tradeTime,{trade_date.isoformat()},{next_date.isoformat()})", ""),  # today only
            (f"between(openInterest,{cfg.min_open_interest},)", ""),
            (f"in(exchange,({','.join(cfg.exchanges)}))",   ""),
            (f"between(volume,{cfg.min_volume},)",          ""),
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

    def get_options_volume_leaders(
        self,
        asset_type:  str,
        cfg:         OptionsFilterConfig,
        trade_date:  date | None = None,
    ) -> list[dict]:
        """
        Fetch all pages of option rows for a given asset type and date.
        Returns flat list of raw API dicts.
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
            log.info(
                "Page %d: %d rows (total so far: %d)",
                page, len(rows), len(all_rows),
            )

            # Stop if we got a partial page — no more data
            if len(rows) < cfg.page_size:
                break

            page += 1
            time.sleep(self.delay)

        log.info(
            "Barchart [%s] %s: %d total rows across %d page(s)",
            asset_type, trade_date, len(all_rows), page,
        )
        return all_rows

    def _fetch_page(
        self,
        url:       str,
        label:     str,
        page:      int,
        retries:   int = 3,
    ) -> list[dict]:
        log.debug("GET %s", url)
        for attempt in range(1, retries + 1):
            req = urllib.request.Request(url, headers=self._headers())
            try:
                with urllib.request.urlopen(req, timeout=20) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
                    return body.get("data", [])

            except urllib.error.HTTPError as e:
                if e.code == 429:
                    wait = 2.0 * (2 ** (attempt - 1))
                    log.warning("Rate limited — waiting %.0fs (attempt %d/%d)", wait, attempt, retries)
                    time.sleep(wait)
                    if attempt == retries:
                        return []
                else:
                    body_text = e.read().decode()[:200]
                    log.warning("HTTP %d [%s] page %d: %s", e.code, label, page, body_text)
                    return []

            except Exception as e:
                log.warning("Fetch failed [%s] page %d attempt %d: %s", label, page, attempt, e)
                if attempt == retries:
                    return []
                time.sleep(self.delay)

        return []
