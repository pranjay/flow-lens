"""
signals/pipeline.py — Orchestrates the full Options Volume Leaders pipeline.

Stage order:
  1. Fetch  — BarchartClient (paginated)
  2. Parse  — OptionsTransformer
  3. Signal — BiasEngine (with OI change from yesterday's ledger)
  4. Track  — PersistenceTracker (re-run safe)
  5. Report — ExcelReporter
"""
from __future__ import annotations
import json
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

from config import OptionsFilterConfig, OUTPUT_DIR
from data.barchart_client import BarchartClient
from data.transformer import OptionsTransformer
from models.options import OptionContract, TickerBias
from reports.excel_reporter import ExcelReporter
from signals.bias_engine import BiasEngine
from signals.persistence import PersistenceTracker

log = logging.getLogger(__name__)

OI_LEDGER_FILENAME = "oi_ledger.json"


@dataclass
class PipelineResult:
    report_date:      date
    stock_contracts:  list[OptionContract]
    etf_contracts:    list[OptionContract]
    stock_biases:     list[TickerBias]
    etf_biases:       list[TickerBias]
    report_path:      Optional[Path] = None

    @property
    def all_biases(self):
        return self.stock_biases + self.etf_biases

    @property
    def strong_signals(self):
        return [b for b in self.all_biases if b.signal_strength == "Strong"]

    @property
    def multi_day_signals(self):
        return [b for b in self.all_biases if b.consecutive_days >= 2]

    def summary(self) -> str:
        lines = [
            f"\n{'='*60}",
            f"  Options Volume Leaders — {self.report_date:%Y-%m-%d}",
            f"{'='*60}",
            f"  Stocks: {len(self.stock_contracts):,} contracts → {len(self.stock_biases)} tickers",
            f"  ETFs:   {len(self.etf_contracts):,} contracts → {len(self.etf_biases)} tickers",
            f"  Strong signals:    {len(self.strong_signals)}",
            f"  Multi-day signals: {len(self.multi_day_signals)}",
        ]
        if self.strong_signals:
            lines.append(f"\n  {'─'*56}")
            lines.append("  STRONG SIGNALS:")
            for b in self.strong_signals[:10]:
                lines.append(f"    {b}")
        if self.report_path:
            lines.append(f"\n  Report → {self.report_path}")
        lines.append(f"{'='*60}\n")
        return "\n".join(lines)


class OptionsVolumePipeline:

    def __init__(
        self,
        client:     Optional[BarchartClient]      = None,
        cfg:        Optional[OptionsFilterConfig]  = None,
        output_dir: Path                           = OUTPUT_DIR,
    ):
        self.cfg         = cfg or OptionsFilterConfig()
        self.client      = client or BarchartClient()
        self.transformer = OptionsTransformer(self.cfg)
        self.engine      = BiasEngine()
        self.tracker     = PersistenceTracker(output_dir)
        self.reporter    = ExcelReporter(output_dir)
        self.oi_ledger_path = output_dir / OI_LEDGER_FILENAME

    def run(self, trade_date: date | None = None) -> PipelineResult:
        trade_date = trade_date or date.today()
        log.info("Pipeline start — %s", trade_date)

        # Load yesterday's OI for change calculation
        prev_oi = self._load_oi_ledger()

        # Fetch + parse
        stock_contracts = self.transformer.transform_all(
            self.client.get_options_volume_leaders("stock", self.cfg, trade_date)
        )
        etf_contracts = []
        if self.cfg.include_etfs:
            etf_contracts = self.transformer.transform_all(
                self.client.get_options_volume_leaders("etf", self.cfg, trade_date)
            )

        all_contracts = stock_contracts + etf_contracts

        # Save today's OI to ledger (for tomorrow's change calculation)
        self._save_oi_ledger(all_contracts)

        # Compute signals
        stock_biases = self.engine.compute(stock_contracts, prev_oi=prev_oi)
        etf_biases   = self.engine.compute(etf_contracts,   prev_oi=prev_oi) if etf_contracts else []

        # Stamp persistence (re-run safe — won't double-count same day)
        self.tracker.annotate(stock_biases)
        self.tracker.annotate(etf_biases)

        stock_biases = stock_biases[:self.cfg.top_n_tickers]
        etf_biases   = etf_biases[:self.cfg.top_n_tickers]

        report_path = self.reporter.write(
            stock_contracts, stock_biases,
            etf_contracts,   etf_biases,
            report_date=trade_date,
        )

        result = PipelineResult(
            report_date=trade_date,
            stock_contracts=stock_contracts, etf_contracts=etf_contracts,
            stock_biases=stock_biases,       etf_biases=etf_biases,
            report_path=report_path,
        )
        print(result.summary())
        return result

    # ── OI ledger ──────────────────────────────────────────────────────────

    def _load_oi_ledger(self) -> dict[str, int]:
        """Load previous day's OI totals per ticker."""
        if self.oi_ledger_path.exists():
            try:
                with open(self.oi_ledger_path) as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                log.warning("OI ledger corrupted — starting fresh")
        return {}

    def _save_oi_ledger(self, contracts: list[OptionContract]) -> None:
        """
        Save today's OI totals per ticker.
        Summed across all qualifying contracts for that ticker.
        """
        from collections import defaultdict
        oi_by_ticker: dict[str, int] = defaultdict(int)
        for c in contracts:
            oi_by_ticker[c.ticker] += c.open_interest
        with open(self.oi_ledger_path, "w") as f:
            json.dump(dict(oi_by_ticker), f, indent=2)
        log.debug("OI ledger saved → %s", self.oi_ledger_path)
