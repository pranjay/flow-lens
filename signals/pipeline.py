"""
signals/pipeline.py

Orchestrates the full Options Volume Leaders pipeline:

  1. Fetch  — BarchartClient pulls raw data (stocks + ETFs)
  2. Parse  — OptionsTransformer converts to OptionContract objects
              and applies quality filters (DTE, Vol/OI, premium)
  3. Signal — BiasEngine aggregates into TickerBias objects
  4. Track  — PersistenceTracker stamps consecutive_days
  5. Report — ExcelReporter writes the workbook

This replaces the monolithic GenerateBarchartOptionReport() method
in Program.cs, broken into composable, testable stages.

Usage:
    pipeline = OptionsVolumePipeline()
    result   = pipeline.run()
    print(result.summary())
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

from config import OPTIONS_FILTER, REPORT_CFG, OUTPUT_DIR
from data.barchart_client import BarchartClient
from data.transformer import OptionsTransformer
from models.options import OptionContract, TickerBias
from reports.excel_reporter import ExcelReporter
from signals.bias_engine import BiasEngine
from signals.persistence import PersistenceTracker

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """Everything the pipeline produced — useful for testing and inspection."""
    report_date:      date
    stock_contracts:  list[OptionContract]
    etf_contracts:    list[OptionContract]
    stock_biases:     list[TickerBias]
    etf_biases:       list[TickerBias]
    report_path:      Optional[Path] = None

    # convenience views
    @property
    def all_contracts(self) -> list[OptionContract]:
        return self.stock_contracts + self.etf_contracts

    @property
    def all_biases(self) -> list[TickerBias]:
        return self.stock_biases + self.etf_biases

    @property
    def strong_signals(self) -> list[TickerBias]:
        return [b for b in self.all_biases if b.signal_strength == "Strong"]

    @property
    def multi_day_signals(self) -> list[TickerBias]:
        return [b for b in self.all_biases if b.consecutive_days >= 2]

    def summary(self) -> str:
        lines = [
            f"\n{'='*60}",
            f"  Options Volume Leaders — {self.report_date:%Y-%m-%d}",
            f"{'='*60}",
            f"  Stocks: {len(self.stock_contracts):,} contracts → "
            f"{len(self.stock_biases)} tickers",
            f"  ETFs:   {len(self.etf_contracts):,} contracts → "
            f"{len(self.etf_biases)} tickers",
            f"  Strong signals:     {len(self.strong_signals)}",
            f"  Multi-day signals:  {len(self.multi_day_signals)}",
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
        client:      Optional[BarchartClient]    = None,
        transformer: Optional[OptionsTransformer] = None,
        engine:      Optional[BiasEngine]         = None,
        tracker:     Optional[PersistenceTracker] = None,
        reporter:    Optional[ExcelReporter]      = None,
        output_dir:  Path                         = OUTPUT_DIR,
    ):
        self.client      = client      or BarchartClient()
        self.transformer = transformer or OptionsTransformer(OPTIONS_FILTER)
        self.engine      = engine      or BiasEngine()
        self.tracker     = tracker     or PersistenceTracker(output_dir)
        self.reporter    = reporter    or ExcelReporter(output_dir)

    def run(self) -> PipelineResult:
        logger.info("Starting Options Volume Leaders pipeline")
        report_date = date.today()

        # ------------------------------------------------------------------
        # Stage 1 + 2: Fetch and parse (stocks)
        # ------------------------------------------------------------------
        logger.info("Fetching stock options...")
        raw_stocks       = self.client.get_options_volume_leaders("stock", OPTIONS_FILTER)
        stock_contracts  = self.transformer.transform_all(raw_stocks)

        # ------------------------------------------------------------------
        # Stage 1 + 2: Fetch and parse (ETFs)
        # ------------------------------------------------------------------
        etf_contracts = []
        if REPORT_CFG.include_etfs:
            logger.info("Fetching ETF options...")
            raw_etfs      = self.client.get_options_volume_leaders("etf", OPTIONS_FILTER)
            etf_contracts = self.transformer.transform_all(raw_etfs)

        # ------------------------------------------------------------------
        # Stage 3: Compute bias signals
        # ------------------------------------------------------------------
        logger.info("Computing bias signals...")
        stock_biases = self.engine.compute(stock_contracts)
        etf_biases   = self.engine.compute(etf_contracts) if etf_contracts else []

        # ------------------------------------------------------------------
        # Stage 4: Stamp persistence (consecutive days)
        # ------------------------------------------------------------------
        logger.info("Updating persistence tracker...")
        self.tracker.annotate(stock_biases)
        self.tracker.annotate(etf_biases)

        # Trim to top N tickers for the report
        stock_biases = stock_biases[:REPORT_CFG.top_n_tickers]
        etf_biases   = etf_biases[:REPORT_CFG.top_n_tickers]

        # ------------------------------------------------------------------
        # Stage 5: Write Excel report
        # ------------------------------------------------------------------
        logger.info("Writing report...")
        report_path = self.reporter.write(
            stock_contracts = stock_contracts,
            stock_biases    = stock_biases,
            etf_contracts   = etf_contracts,
            etf_biases      = etf_biases,
            report_date     = report_date,
        )

        result = PipelineResult(
            report_date     = report_date,
            stock_contracts = stock_contracts,
            etf_contracts   = etf_contracts,
            stock_biases    = stock_biases,
            etf_biases      = etf_biases,
            report_path     = report_path,
        )

        print(result.summary())
        return result
