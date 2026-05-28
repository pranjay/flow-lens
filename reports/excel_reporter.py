"""
reports/excel_reporter.py

Generates the 4-sheet Excel workbook.
"""
from __future__ import annotations
import logging
from datetime import date
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from models.options import OptionContract, TickerBias

log = logging.getLogger(__name__)

_GREEN  = PatternFill("solid", fgColor="C6EFCE")
_RED    = PatternFill("solid", fgColor="FFC7CE")
_GOLD   = PatternFill("solid", fgColor="FFEB9C")
_HEADER = PatternFill("solid", fgColor="2F4F8F")
_HEADER_FONT = Font(color="FFFFFF", bold=True)


class ExcelReporter:

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir

    def write(
        self,
        stock_contracts: list[OptionContract],
        stock_biases:    list[TickerBias],
        etf_contracts:   list[OptionContract],
        etf_biases:      list[TickerBias],
        report_date:     date = None,
    ) -> Path:
        report_date = report_date or date.today()
        filename    = self.output_dir / f"{report_date:%Y-%m-%d}_OptionVolumeLeaders.xlsx"
        wb = openpyxl.Workbook()
        wb.remove(wb.active)
        self._write_contracts_sheet(wb, "Stocks",      stock_contracts)
        self._write_bets_sheet(     wb, "Stocks Bets", stock_biases)
        self._write_contracts_sheet(wb, "ETFs",        etf_contracts)
        self._write_bets_sheet(     wb, "ETFs Bets",   etf_biases)
        wb.save(filename)
        log.info("Report saved → %s", filename)
        return filename

    # ── Raw contracts sheet ────────────────────────────────────────────────────

    _CONTRACT_COLS = [
        ("Ticker",         12), ("Type",      6), ("Strike",     9),
        ("Moneyness",      10), ("Delta",      7), ("Aggressor",  10),
        ("Expiration",     12), ("DTE",        6), ("Bid",        8),
        ("Ask",             8), ("Last",       8), ("Volume",    10),
        ("Open Interest",  14), ("Vol/OI",     9), ("Premium ($)", 14),
        ("IV",              8), ("Underlying $", 12), ("Trade Time", 18),
        ("Symbol",         28),
    ]

    def _write_contracts_sheet(self, wb, name, contracts):
        ws = wb.create_sheet(name)
        self._write_header(ws, [c[0] for c in self._CONTRACT_COLS])
        for c in contracts:
            ws.append([
                c.ticker, c.option_type, c.strike,
                c.moneyness, round(c.delta, 3), c.aggressor,
                c.expiration_label, c.dte, c.bid, c.ask, c.last,
                c.volume, c.open_interest, c.vol_oi_ratio,
                round(c.premium_usd, 0), f"{c.volatility:.1%}",
                c.underlying_price,
                str(c.trade_time.strftime("%Y-%m-%d %H:%M")),
                c.symbol,
            ])
            fill = _GREEN if c.is_call else _RED
            for cell in ws[ws.max_row]:
                cell.fill = fill
        self._set_col_widths(ws, self._CONTRACT_COLS)
        ws.freeze_panes = "A2"

    # ── Bets summary sheet ─────────────────────────────────────────────────────

    _BETS_COLS = [
        ("Ticker",              10), ("Bias",            8), ("Signal Strength",  15),
        ("Consecutive Days",    16), ("Parity (Vol)",   13), ("Parity (Premium)", 15),
        ("Total Premium ($)",   16), ("Buyer Premium ($)", 16), ("Seller Premium ($)", 16),
        ("Flow Type",           12),
        ("Call Volume",         12), ("Put Volume",     12),
        ("Call Premium ($)",    14), ("Put Premium ($)", 14), ("Total Contracts",  15),
        ("OI Change",           11), ("Volume Change",  14),
        # Dominant contract
        ("Top Strike",          10), ("Top Type",        8), ("Top Moneyness",    12),
        ("Top Expiry",          10), ("Top DTE",          8), ("Top Delta",         9),
        ("Top Aggressor",       12), ("Top Premium ($)", 14), ("Top Vol/OI",       10),
        ("Top IV",               8),
    ]

    def _write_bets_sheet(self, wb, name, biases):
        ws = wb.create_sheet(name)
        self._write_header(ws, [c[0] for c in self._BETS_COLS])
        for b in biases:
            dom = b.dominant_contract
            ws.append([
                b.ticker, b.bias, b.signal_strength, b.consecutive_days,
                b.parity_label, b.premium_parity_label,
                round(b.total_premium, 0),
                round(b.buyer_premium, 0),
                round(b.seller_premium, 0),
                b.aggressor_label,
                b.call_volume, b.put_volume,
                round(b.call_premium, 0), round(b.put_premium, 0),
                b.total_contracts, b.oi_change, b.volume_change,
                dom.strike             if dom else "",
                dom.option_type        if dom else "",
                dom.moneyness          if dom else "",
                dom.expiration_label   if dom else "",
                dom.dte                if dom else "",
                round(dom.delta, 3)    if dom else "",
                dom.aggressor          if dom else "",
                round(dom.premium_usd, 0) if dom else "",
                dom.vol_oi_ratio       if dom else "",
                f"{dom.volatility:.1%}" if dom else "",
            ])
            if b.signal_strength == "Strong":
                fill = _GOLD
            elif b.bias == "Long":
                fill = _GREEN
            elif b.bias == "Short":
                fill = _RED
            else:
                continue
            for cell in ws[ws.max_row]:
                cell.fill = fill
        self._set_col_widths(ws, self._BETS_COLS)
        ws.freeze_panes = "A2"

    # ── Helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _write_header(ws, headers):
        ws.append(headers)
        for cell in ws[1]:
            cell.fill      = _HEADER
            cell.font      = _HEADER_FONT
            cell.alignment = Alignment(horizontal="center")

    @staticmethod
    def _set_col_widths(ws, col_defs):
        for i, (_, w) in enumerate(col_defs, 1):
            ws.column_dimensions[get_column_letter(i)].width = w
