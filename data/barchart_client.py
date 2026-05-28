"""
data/barchart_client.py

Barchart API client for options volume leaders data.

Auth: mirrors earnings_history/barchart.py exactly —
  1. Explicit cookie / xsrf_token args
  2. BARCHART_COOKIE / BARCHART_XSRF_TOKEN env vars  (+ .env / ~/.barchart.env)
  3. Browser cookie store via browser_cookie3  (Firefox → Safari on macOS)

When the browser store is available this just works — no config needed.
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from config import BARCHART_BASE_URL, OptionsFilterConfig

log = logging.getLogger(__name__)

# ── Cookie loading (copied verbatim from earnings_history/barchart.py) ────────

def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
        from pathlib import Path as _P
        for candidate in [_P(__file__).parent.parent / ".env", _P.home() / ".barchart.env"]:
            if candidate.exists():
                load_dotenv(candidate)
                log.debug("Loaded env from %s", candidate)
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
        log.debug("Barchart auth: using explicit/env cookie")
        return cookie, xsrf_token

    try:
        import browser_cookie3
        import sys as _sys

        SESSION_COOKIE = "laravel_session"

        def _load_from_browser(loader, name):
            jar     = loader(domain_name=".barchart.com")
            cookies = {c.name: c.value for c in jar}
            if not cookies:
                raise ValueError(f"No barchart.com cookies found in {name}")
            if SESSION_COOKIE not in cookies:
                raise ValueError(
                    f"{name} has Barchart cookies but no active session "
                    f"({SESSION_COOKIE} missing) — log into barchart.com in {name} first"
                )
            cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
            raw_xsrf   = cookies.get("XSRF-TOKEN", xsrf_token or "")
            xsrf_str   = urllib.parse.unquote(raw_xsrf)
            log.info("Barchart auth: loaded %d cookies from %s", len(cookies), name)
            return cookie_str, xsrf_str

        browsers = (
            [(browser_cookie3.firefox, "Firefox"), (browser_cookie3.safari, "Safari")]
            if _sys.platform == "darwin"
            else [(browser_cookie3.firefox, "Firefox")]
        )

        last_err = None
        for loader, name in browsers:
            try:
                return _load_from_browser(loader, name)
            except Exception as e:
                log.debug("Barchart auth: %s failed: %s", name, e)
                last_err = e

        raise ValueError(
            f"Could not find an active Barchart session in any browser.\n"
            f"Last error: {last_err}\n\n"
            "→ Log into barchart.com in Firefox or Safari, then retry.\n"
            "→ Or set credentials manually:\n"
            "    export BARCHART_COOKIE='your_cookie_here'\n"
            "    export BARCHART_XSRF_TOKEN='your_token_here'"
        )

    except ImportError:
        raise ValueError(
            "browser-cookie3 not installed and no cookie provided.\n"
            "Install it:  pip install browser-cookie3\n"
            "Or set BARCHART_COOKIE environment variable."
        )


# ── Field list ─────────────────────────────────────────────────────────────────

_OPTION_FIELDS = ",".join([
    "symbol", "baseSymbol", "baseLastPrice", "baseSymbolType",
    "symbolType", "strikePrice", "expirationDate", "daysToExpiration",
    "bidPrice", "midpoint", "askPrice", "lastPrice",
    "volume", "openInterest", "volumeOpenInterestRatio",
    "volatility", "tradeTime", "symbolCode",
])


# ── Client ─────────────────────────────────────────────────────────────────────

class BarchartClient:
    """
    Fetches options volume leaders from the Barchart proxy API.

    Identical auth chain to earnings_history.barchart.BarchartClient —
    once you're logged into barchart.com in your browser this just works.
    """

    BASE_URL = "https://www.barchart.com/proxies/core-api/v1/options/get"

    def __init__(
        self,
        cookie:     str | None = None,
        xsrf_token: str | None = None,
        delay:      float = 0.5,
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

    def get_options_volume_leaders(
        self,
        asset_type: str,           # "stock" or "etf"
        cfg: OptionsFilterConfig,
        retries: int = 3,
    ) -> list[dict]:
        """
        Fetch raw option rows ordered by volume descending.
        Returns list of raw API dicts — parsing is done by OptionsTransformer.
        """
        exchanges = ",".join(cfg.exchanges)
        # Build query string manually to avoid urllib encoding commas in filter syntax
        params: list[tuple[str, str]] = [
            ("fields",     _OPTION_FIELDS),
            ("orderBy",    "volume"),
            ("orderDir",   "desc"),
            ("baseSymbolTypes", asset_type),
            ("gt(volatility,0)", ""),
            (f"between(volume,{cfg.min_volume},)", ""),
            (f"between(openInterest,{cfg.min_open_interest},)", ""),
            (f"in(exchange,({exchanges}))", ""),
            ("meta",  "field.shortName,field.type,field.description"),
            ("page",  "1"),
            ("limit", str(cfg.max_results)),
            ("raw",   "1"),
        ]
        qs  = "&".join(f"{k}={urllib.parse.quote(str(v), safe=',.()_-')}" for k, v in params)
        url = f"{self.BASE_URL}?{qs}"
        log.debug("GET %s", url)

        for attempt in range(1, retries + 1):
            req = urllib.request.Request(url, headers=self._headers())
            try:
                with urllib.request.urlopen(req, timeout=20) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
                    rows = body.get("data", [])
                    log.info("Barchart options [%s]: %d rows", asset_type, len(rows))
                    time.sleep(self.delay)
                    return rows
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    wait = 2.0 * (2 ** (attempt - 1))
                    log.warning("Rate limited — waiting %.0fs (attempt %d/%d)", wait, attempt, retries)
                    time.sleep(wait)
                    if attempt == retries:
                        return []
                else:
                    log.warning("HTTP %d for options [%s]: %s", e.code, asset_type, e)
                    return []
            except Exception as e:
                log.warning("Options fetch failed [%s]: %s", asset_type, e)
                return []

        return []
