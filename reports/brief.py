"""
reports/brief.py

Clean terminal summary using tabulate rounded_outline format.

Output:
  flow-lens · 2026-05-29 · 8 stock  3 ETF signals

  STRONG ✓  volume + OI confirmed, 3+ days
  ╭────────┬──────┬────────┬─────────┬───────┬────────┬──────╮
  │ Ticker │ Type │ Strike │ Expiry  │ Bias  │ Delta  │ DTE  │
  │ MRVL   │ CALL │  200.0 │ 26JUN26 │ Long  │ Δ+0.59 │  29d │
  │ PLTR   │ CALL │  138.0 │ 05JUN26 │ Long  │ Δ+0.71 │   8d │
  │ BMY    │ PUT  │   62.0 │ 02JUL26 │ Short │ Δ-0.73 │  35d │
  ╰────────┴──────┴────────┴─────────┴───────┴────────┴──────╯

  STRONG  volume signal, 3+ days
  ╭────────┬──────┬────────┬─────────┬───────┬────────┬──────╮
  │ MU     │ PUT  │  765.0 │ 05JUN26 │ Short │ Δ-0.10 │  8d⚠ │
  ╰────────┴──────┴────────┴─────────┴───────┴────────┴──────╯

⚠ far OTM (|Δ| < 0.20) — likely hedge or event play, lower conviction
"""
from __future__ import annotations
from datetime import date
from tabulate import tabulate
from models.options import TickerBias

_OTM_THRESHOLD = 0.20
_HEADERS = ["Ticker", "Type", "Strike", "Expiry", "Bias", "Delta", "DTE"]


def _rows(biases: list[TickerBias]) -> list[list]:
    rows = []
    for b in biases:
        dom = b.dominant_contract
        if not dom:
            continue
        warn   = "⚠" if abs(dom.delta) < _OTM_THRESHOLD else ""
        rows.append([
            b.ticker,
            dom.option_type.upper(),
            dom.strike,
            dom.expiration_label,
            b.bias,
            f"Δ{dom.delta:+.2f}",
            f"{dom.dte}d{warn}",
        ])
    return rows


def _table(biases: list[TickerBias], show_headers: bool = True) -> str | None:
    rows = _rows(biases)
    if not rows:
        return None
    headers = _HEADERS if show_headers else ()
    return tabulate(rows, headers=headers, tablefmt="rounded_outline",
                    colalign=("left","left","right","left","left","left","right"))


def print_brief(
    biases:      list[TickerBias],
    report_date: date | None = None,
    etf_biases:  list[TickerBias] | None = None,
) -> None:
    report_date = report_date or date.today()

    confirmed = [b for b in biases if b.is_strong and b.oi_confirmed]
    strong    = [b for b in biases if b.is_strong and not b.oi_confirmed]
    watch     = [b for b in biases if b.signal_strength == "Moderate"
                 and b.consecutive_days >= 2][:5]

    etf_confirmed = [b for b in (etf_biases or []) if b.is_strong and b.oi_confirmed]
    etf_strong    = [b for b in (etf_biases or []) if b.is_strong and not b.oi_confirmed]

    n_stock = len(confirmed) + len(strong)
    n_etf   = len(etf_confirmed) + len(etf_strong)

    print(f"\n  flow-lens · {report_date:%Y-%m-%d} · {n_stock} stock  {n_etf} ETF signals\n")

    first_printed = [False]   # flag to show headers only on first table

    def _section(label: str, items: list[TickerBias]) -> None:
        t = _table(items, show_headers=not first_printed[0])
        if t is None:
            return
        first_printed[0] = True
        print(f"  {label}")
        for line in t.splitlines():
            print(f"  {line}")
        print()

    _section("STRONG ✓  volume + OI confirmed, 3+ days", confirmed)
    _section("STRONG    volume signal, 3+ days",          strong)
    _section("WATCH     2+ days, building",               watch)

    if etf_confirmed or etf_strong:
        _section("ETFs  STRONG ✓", etf_confirmed)
        _section("ETFs  STRONG",   etf_strong)

    has_warn = any(
        abs(b.dominant_contract.delta) < _OTM_THRESHOLD
        for b in confirmed + strong
        if b.dominant_contract
    )
    if has_warn:
        print("  ⚠ far OTM (|Δ| < 0.20) — likely hedge or event play, lower conviction\n")
