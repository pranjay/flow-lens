"""
reports/brief.py

Clean terminal summary — ticker, direction, strike, expiry.
Printed after every run. Full detail stays in Excel.

Output example:
  ╔══════════════════════════════════════════════════════╗
  ║   flow-lens  ·  2026-05-29  ·  8 signals             ║
  ╠══════════════════════════════════════════════════════╣
  ║  STRONG ✓  (volume + OI confirmed, 3+ days)          ║
  ║  ─────────────────────────────────────────────────   ║
  ║  MRVL   CALL  200.0   26JUN26   Long    Δ0.59  29d   ║
  ║  PLTR   CALL  138.0   05JUN26   Long    Δ0.71   8d   ║
  ║  BMY    PUT    62.0   02JUL26   Short   Δ-0.73 35d   ║
  ╠══════════════════════════════════════════════════════╣
  ║  STRONG  (volume, 3+ days, OI pending)               ║
  ║  ─────────────────────────────────────────────────   ║
  ║  MU     PUT   765.0   05JUN26   Short   Δ-0.10  8d ⚠ ║
  ╚══════════════════════════════════════════════════════╝

⚠ flag: far OTM (|delta| < 0.20) — lower conviction, likely hedge/event play
"""
from __future__ import annotations
from datetime import date
from models.options import TickerBias


_OTM_DELTA_THRESHOLD = 0.20   # |delta| below this gets the ⚠ flag
_W = 56                        # box width


def _line(content: str = "", pad: bool = True) -> str:
    if pad:
        return f"  ║  {content:<{_W - 6}}║"
    return f"  ║{content:^{_W - 2}}║"


def _divider() -> str:
    return f"  ╠{'═' * (_W - 2)}╣"


def _top() -> str:
    return f"  ╔{'═' * (_W - 2)}╗"


def _bottom() -> str:
    return f"  ╚{'═' * (_W - 2)}╝"


def _sep() -> str:
    return f"  ║  {'─' * (_W - 6)}║"


def _format_signal(b: TickerBias) -> str:
    dom = b.dominant_contract
    if not dom:
        return f"  {b.ticker:<6}  {'—'}"

    delta    = abs(dom.delta)
    warn     = " ⚠" if delta < _OTM_DELTA_THRESHOLD else "  "
    d_str    = f"Δ{dom.delta:+.2f}"
    dte_str  = f"{dom.dte}d"
    direction = b.bias

    return (
        f"  {b.ticker:<6} {dom.option_type.upper():<4} "
        f"{dom.strike:>7.1f}  {dom.expiration_label:<8} "
        f"{direction:<6}  {d_str:<7} {dte_str:>4}{warn}"
    )


def print_brief(
    biases:      list[TickerBias],
    report_date: date | None = None,
    etf_biases:  list[TickerBias] | None = None,
) -> None:
    report_date = report_date or date.today()

    confirmed = [b for b in biases if b.is_strong and b.oi_confirmed]
    strong    = [b for b in biases if b.is_strong and not b.oi_confirmed]
    moderate  = [b for b in biases if b.signal_strength == "Moderate"
                 and b.consecutive_days >= 2]

    # ETF signals
    etf_confirmed = [b for b in (etf_biases or []) if b.is_strong and b.oi_confirmed]
    etf_strong    = [b for b in (etf_biases or []) if b.is_strong and not b.oi_confirmed]

    total = len(confirmed) + len(strong)
    etf_total = len(etf_confirmed) + len(etf_strong)

    lines = [
        "",
        _top(),
        _line(f"flow-lens  ·  {report_date:%Y-%m-%d}  ·  {total} stock  {etf_total} ETF signals", pad=False),
    ]

    def _section(label: str, items: list[TickerBias]) -> None:
        if not items:
            return
        lines.append(_divider())
        lines.append(_line(label))
        lines.append(_sep())
        for b in items:
            lines.append(_line(_format_signal(b)))

    _section("STRONG ✓  volume + OI confirmed, 3+ days", confirmed)
    _section("STRONG    volume signal, 3+ days",          strong)
    _section("WATCH     2+ days, building",               moderate[:5])  # top 5 only

    if etf_confirmed or etf_strong:
        lines.append(_divider())
        lines.append(_line("ETFs"))
        lines.append(_sep())
        for b in etf_confirmed + etf_strong:
            lines.append(_line(_format_signal(b)))

    lines.append(_bottom())
    lines.append("")
    print("\n".join(lines))


def format_brief_text(
    biases:      list[TickerBias],
    report_date: date | None = None,
    etf_biases:  list[TickerBias] | None = None,
) -> str:
    """Same as print_brief but returns the string instead of printing."""
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        print_brief(biases, report_date, etf_biases)
    return buf.getvalue()
